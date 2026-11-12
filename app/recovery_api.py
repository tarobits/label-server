"""Verified recovery addresses, single-use password resets, and personal subscriptions."""

import hmac
import logging
import secrets
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.account_audit import record_account
from app.auth import (
    check_csrf,
    check_origin,
    hash_password,
    session_user,
    token_hash,
    verify_password,
)
from app.auth_api import Password, throttle
from app.config import Settings
from app.db import begin_write
from app.email_delivery import EmailAddress, email_enabled, send_email
from app.models import AuthSession, NotificationEndpoint, RecoveryToken, User
from app.notification_api import EndpointInput, update_configuration, validate_references
from app.notification_types import NotificationKind, PrinterNotificationKind

router = APIRouter(prefix="/api/auth", tags=["account recovery"])
logger = logging.getLogger(__name__)
TOKEN_SECONDS = 30 * 60


class RecoveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailInput(RecoveryInput):
    email: EmailAddress | None
    current_password: str = Field(min_length=1, max_length=256)


class TokenInput(RecoveryInput):
    token: str = Field(min_length=1, max_length=256)


class ResetInput(TokenInput):
    new_password: Password


class ForgotInput(RecoveryInput):
    username: str = Field(min_length=1, max_length=64)


class SubscriptionInput(RecoveryInput):
    enabled: bool = False
    all_printers: bool = False
    destination_ids: list[str] = Field(default_factory=list, max_length=1000)
    kinds: list[NotificationKind] = Field(default=["general"], max_length=8)
    printer_kinds: dict[str, list[PrinterNotificationKind]] = Field(
        default_factory=dict, max_length=1000
    )


def require_user(request: Request, session: Session) -> User:
    current = session_user(request, session)
    if current is None:
        raise HTTPException(401, "Sign in to manage your account")
    check_csrf(request, current[1])
    return current[0]


def require_email(request: Request) -> None:
    if not email_enabled(request.app.state.settings):
        raise HTTPException(503, "Email delivery is not configured; contact your administrator")


def issue_token(session: Session, user: User, purpose: str, email: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    session.execute(delete(RecoveryToken).where(RecoveryToken.expires_at <= now))
    if purpose == "verify":
        session.execute(
            delete(RecoveryToken).where(
                RecoveryToken.user_id == user.id, RecoveryToken.purpose == "verify"
            )
        )
    session.add(
        RecoveryToken(
            token_hash=token_hash(token),
            user_id=user.id,
            purpose=purpose,
            email=email,
            password_fingerprint=token_hash(user.password_hash),
            expires_at=now + TOKEN_SECONDS,
        )
    )
    return token


def deliver_link(settings: Settings, recipient: str, purpose: str, token: str) -> None:
    try:
        route = "verify-email" if purpose == "verify" else "reset-password"
        action = "Verify your email address" if purpose == "verify" else "Reset your password"
        link = settings.public_url.rstrip("/") + f"/#/{route}?token={token}"
        send_email(
            settings,
            recipient,
            f"{action} · Taro's Label Room",
            f"{action}:\n\n{link}\n\nThis link expires in 30 minutes and can be used once. If you did not request it, ignore this email.",
        )
    except Exception:
        logger.warning("Account email delivery failed")


def send_reset_link(
    factory: sessionmaker[Session],
    settings: Settings,
    username: str,
) -> None:
    """Run outside the response so SMTP latency never reveals registered accounts."""
    try:
        with factory.begin() as session:
            user = session.scalar(select(User).where(User.username == username.lower()))
            if user is None or user.disabled or not user.email:
                return
            recipient = user.email
            token = issue_token(session, user, "reset", recipient)
            record_account(session, "auth.reset_link_issued", user, system=True)
        deliver_link(settings, recipient, "reset", token)
    except Exception:
        logger.warning("Account email delivery failed")


@router.get("/email")
def email_settings(request: Request) -> dict[str, Any]:
    with request.app.state.factory() as session:
        user = require_user(request, session)
        pending = session.scalar(
            select(RecoveryToken).where(
                RecoveryToken.user_id == user.id,
                RecoveryToken.purpose == "verify",
                RecoveryToken.expires_at > time.time(),
                RecoveryToken.password_fingerprint == token_hash(user.password_hash),
            )
        )
        endpoint = session.get(NotificationEndpoint, f"personal-email:{user.id}")
        return {
            "available": email_enabled(request.app.state.settings),
            "email": user.email,
            "pending_email": pending.email if pending else None,
            "subscription": {
                "enabled": endpoint.enabled if endpoint else False,
                "all_printers": endpoint.all_printers if endpoint else False,
                "destination_ids": endpoint.destination_ids if endpoint else [],
                "kinds": endpoint.kinds if endpoint else ["general"],
                "printer_kinds": endpoint.printer_kinds if endpoint else {},
            },
        }


@router.put("/email", status_code=202)
def change_email(body: EmailInput, request: Request, tasks: BackgroundTasks) -> dict[str, str]:
    with request.app.state.factory() as session:
        user = require_user(request, session)
        throttle(request, "email:" + user.username)
        identity = (user.id, user.password_hash)
    if not verify_password(body.current_password, identity[1]):
        raise HTTPException(400, "Current password is incorrect")
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        begin_write(session)
        user = require_user(request, session)
        if (user.id, user.password_hash) != identity:
            raise HTTPException(409, "Account changed; sign in again")
        if body.email is None:
            user.email = None
            session.execute(delete(RecoveryToken).where(RecoveryToken.user_id == user.id))
            endpoint = session.get(NotificationEndpoint, f"personal-email:{user.id}")
            if endpoint:
                update_configuration(session, endpoint, {"enabled": False, "email": ""})
            message = "Account email removed."
        else:
            require_email(request)
            token = issue_token(session, user, "verify", body.email)
            tasks.add_task(
                deliver_link,
                request.app.state.settings,
                body.email,
                "verify",
                token,
            )
            message = "Check your email for a verification link."
        record_account(session, "auth.email_changed", user, configured=body.email is not None)
        session.commit()
        return {"message": message}


def consume_token(session: Session, value: str, purpose: str) -> tuple[RecoveryToken, User]:
    token = session.get(RecoveryToken, token_hash(value))
    user = session.get(User, token.user_id) if token else None
    if (
        token is None
        or token.purpose != purpose
        or token.expires_at <= time.time()
        or user is None
        or user.disabled
        or not hmac.compare_digest(token.password_fingerprint, token_hash(user.password_hash))
        or (purpose == "reset" and token.email != user.email)
    ):
        raise HTTPException(400, "This link is invalid or expired. Request a new one.")
    return token, user


@router.post("/email/verify", status_code=204)
def verify_email(body: TokenInput, request: Request) -> None:
    check_origin(request)
    throttle(request, "verify:" + token_hash(body.token))
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        begin_write(session)
        token, user = consume_token(session, body.token, "verify")
        if session.scalar(
            select(User.id).where(func.lower(User.email) == token.email, User.id != user.id)
        ):
            raise HTTPException(409, "This email address is already used by another account")
        user.email = token.email
        session.execute(delete(RecoveryToken).where(RecoveryToken.user_id == user.id))
        endpoint = session.get(NotificationEndpoint, f"personal-email:{user.id}")
        if endpoint:
            update_configuration(session, endpoint, {"email": user.email})
        record_account(session, "auth.email_verified", user)
        session.commit()


@router.post("/password/forgot", status_code=202)
def forgot_password(body: ForgotInput, request: Request, tasks: BackgroundTasks) -> dict[str, str]:
    check_origin(request)
    throttle(request, "forgot:" + body.username)
    require_email(request)
    with request.app.state.factory.begin() as session:
        record_account(session, "auth.reset_requested", None)
    tasks.add_task(
        send_reset_link, request.app.state.factory, request.app.state.settings, body.username
    )
    return {"message": "If this account has a verified email address, a reset link will be sent."}


def password_changed_email(settings: Settings, recipient: str) -> None:
    try:
        send_email(
            settings,
            recipient,
            "Password reset · Taro's Label Room",
            "Your password was reset and all sessions were signed out. If you did not make this change, contact your administrator.",
        )
    except Exception:
        logger.warning("Account email delivery failed")


@router.post("/password/reset", status_code=204)
def reset_password(body: ResetInput, request: Request, tasks: BackgroundTasks) -> None:
    check_origin(request)
    throttle(request, "reset:" + token_hash(body.token))
    with request.app.state.factory() as session:
        consume_token(session, body.token, "reset")
    encoded = hash_password(body.new_password)
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        begin_write(session)
        token, user = consume_token(session, body.token, "reset")
        user.password_hash = encoded
        session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        from app.companion_auth import revoke_sessions

        revoke_sessions(session, user.id)
        session.execute(delete(RecoveryToken).where(RecoveryToken.user_id == user.id))
        tasks.add_task(password_changed_email, request.app.state.settings, token.email)
        record_account(session, "auth.password_reset", user)
        session.commit()


@router.put("/email/subscription", status_code=204)
def save_subscription(body: SubscriptionInput, request: Request) -> None:
    from app.access import AccountPolicy
    from app.auth import actor_for_user

    with request.app.state.fleet.lock, request.app.state.factory() as session:
        begin_write(session)
        user = require_user(request, session)
        if body.enabled:
            require_email(request)
            if not user.email:
                raise HTTPException(
                    409, "Verify an email address before enabling email notifications"
                )
        if not user.email:
            record_account(session, "auth.subscription_changed", user, configured=False)
            session.commit()
            return
        actor = actor_for_user(session, user)
        if "approval_digest" in body.kinds and not actor.is_admin:
            raise HTTPException(403, "Only administrators can subscribe to pending print requests")
        if any(
            not actor.is_admin
            and not AccountPolicy({identifier: None}).can_printer(
                actor, identifier, "view_activity"
            )
            for identifier in {*body.destination_ids, *body.printer_kinds}
        ):
            raise HTTPException(403, "Choose destinations whose print activity you can view")
        try:
            values = EndpointInput(
                name="Personal email",
                transport="email",
                email=user.email,
                **body.model_dump(),
            )
        except ValidationError as error:
            raise HTTPException(
                422, "Choose valid notification types and printer scopes"
            ) from error
        validate_references(session, values)
        identifier = f"personal-email:{user.id}"
        endpoint = session.get(NotificationEndpoint, identifier)
        if endpoint is None:
            endpoint = NotificationEndpoint(
                id=identifier, owner_id=user.id, **values.model_dump(exclude={"token"})
            )
            session.add(endpoint)
        else:
            update_configuration(session, endpoint, values.model_dump(exclude={"token"}))
        record_account(session, "auth.subscription_changed", user, configured=body.enabled)
        session.commit()
