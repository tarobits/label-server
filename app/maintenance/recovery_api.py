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

from app.audit.account_audit import record_account
from app.authn.auth import (
    check_csrf,
    check_origin,
    hash_password,
    session_user,
    token_hash,
    verify_password,
)
from app.authn.auth_api import Password, throttle
from app.config import Settings
from app.db import begin_write
from app.i18n import Language, Message, render, request_language, user_language
from app.models import AuthSession, NotificationEndpoint, RecoveryToken, User
from app.notifications.email_delivery import EmailAddress, email_enabled, send_email
from app.notifications.notification_api import (
    EndpointInput,
    update_configuration,
    validate_references,
)
from app.notifications.notification_types import NotificationKind, PrinterNotificationKind

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
        raise HTTPException(401, Message("recoveryMessages.signIn"))
    check_csrf(request, current[1])
    return current[0]


def require_email(request: Request) -> None:
    if not email_enabled(request.app.state.settings):
        raise HTTPException(503, Message("recoveryMessages.unavailable"))


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


def deliver_link(
    settings: Settings, recipient: str, purpose: str, token: str, language: Language = "en"
) -> None:
    try:
        route = "verify-email" if purpose == "verify" else "reset-password"
        action = render(
            "recoveryMessages.verifyAction"
            if purpose == "verify"
            else "recoveryMessages.resetAction",
            language,
        )
        link = settings.public_url.rstrip("/") + f"/#/{route}?token={token}"
        send_email(
            settings,
            recipient,
            render("recoveryMessages.subject", language, action=action),
            render("recoveryMessages.linkBody", language, action=action, link=link),
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
            language = user_language(user)
            token = issue_token(session, user, "reset", recipient)
            record_account(session, "auth.reset_link_issued", user, system=True)
        deliver_link(settings, recipient, "reset", token, language)
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
        raise HTTPException(400, Message("recoveryMessages.password"))
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        begin_write(session)
        user = require_user(request, session)
        if (user.id, user.password_hash) != identity:
            raise HTTPException(409, Message("authMessages.accountChangedSignInAgain"))
        if body.email is None:
            user.email = None
            session.execute(delete(RecoveryToken).where(RecoveryToken.user_id == user.id))
            endpoint = session.get(NotificationEndpoint, f"personal-email:{user.id}")
            if endpoint:
                update_configuration(session, endpoint, {"enabled": False, "email": ""})
            message = "recoveryMessages.removed"
        else:
            require_email(request)
            token = issue_token(session, user, "verify", body.email)
            tasks.add_task(
                deliver_link,
                request.app.state.settings,
                body.email,
                "verify",
                token,
                user_language(user),
            )
            message = "recoveryMessages.checkMail"
        record_account(session, "auth.email_changed", user, configured=body.email is not None)
        session.commit()
        return {"message": render(message, request_language(request))}


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
        raise HTTPException(400, Message("recoveryMessages.invalidLink"))
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
            raise HTTPException(409, Message("recoveryMessages.usedEmail"))
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
    return {"message": render("recoveryMessages.resetRequested", request_language(request))}


def password_changed_email(settings: Settings, recipient: str, language: Language = "en") -> None:
    try:
        send_email(
            settings,
            recipient,
            render("recoveryMessages.changedSubject", language),
            render("recoveryMessages.changedBody", language),
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
        from app.companion.companion_auth import revoke_sessions

        revoke_sessions(session, user.id)
        session.execute(delete(RecoveryToken).where(RecoveryToken.user_id == user.id))
        tasks.add_task(
            password_changed_email, request.app.state.settings, token.email, user_language(user)
        )
        record_account(session, "auth.password_reset", user)
        session.commit()


@router.put("/email/subscription", status_code=204)
def save_subscription(body: SubscriptionInput, request: Request) -> None:
    from app.authn.access import AccountPolicy
    from app.authn.auth import actor_for_user

    with request.app.state.fleet.lock, request.app.state.factory() as session:
        begin_write(session)
        user = require_user(request, session)
        if body.enabled:
            require_email(request)
            if not user.email:
                raise HTTPException(409, Message("recoveryMessages.verifyFirst"))
        if not user.email:
            record_account(session, "auth.subscription_changed", user, configured=False)
            session.commit()
            return
        actor = actor_for_user(session, user)
        if "approval_digest" in body.kinds and not actor.is_admin:
            raise HTTPException(403, Message("recoveryMessages.adminOnly"))
        if any(
            not actor.is_admin
            and not AccountPolicy({identifier: None}).can_printer(
                actor, identifier, "view_activity"
            )
            for identifier in {*body.destination_ids, *body.printer_kinds}
        ):
            raise HTTPException(403, Message("recoveryMessages.destinations"))
        try:
            values = EndpointInput(
                name=render("recoveryMessages.personal", user_language(user)),
                transport="email",
                email=user.email,
                **body.model_dump(),
            )
        except ValidationError as error:
            raise HTTPException(422, Message("recoveryMessages.invalidSubscription")) from error
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
