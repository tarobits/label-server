"""First-run enrollment and browser sessions; no anonymous production API access."""

import hmac
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.audit.account_audit import record_account
from app.authn.auth import (
    COOKIE_NAME,
    check_csrf,
    check_origin,
    find_login_user,
    hash_password,
    new_session,
    session_record,
    session_user,
    token_hash,
    verify_password,
)
from app.authn.identity import LOCAL_OWNER_ID
from app.db import begin_write
from app.maintenance.releases import release_version
from app.models import (
    AuthSession,
    AuthSettings,
    RecoveryToken,
    RegistrationCode,
    Role,
    User,
    UserGroup,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
Password = Annotated[str, Field(min_length=12, max_length=256)]
Username = Annotated[
    str,
    StringConstraints(to_lower=True, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"),
]


class Credentials(BaseModel):
    username: Username
    password: Password


class SetupInput(Credentials):
    setup_token: str = Field(min_length=1, max_length=256)


class RegistrationInput(Credentials):
    registration_code: str | None = Field(default=None, max_length=256)


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeInput(BaseModel):
    model_config = {"extra": "forbid"}
    current_password: str = Field(min_length=1, max_length=256)
    new_password: Password


class LanguageInput(BaseModel):
    model_config = {"extra": "forbid"}
    language: Literal["browser", "en", "de"]
    browser_language: Literal["en", "de"]


@router.put("/language")
def save_language(body: LanguageInput, request: Request, response: Response) -> dict[str, str]:
    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        current = session_user(request, session)
        if current is None:
            raise HTTPException(401, "Sign in to change your language")
        check_csrf(request, current[1])
        user = current[0]
        user.language = body.language
        user.browser_language = body.browser_language
    response.headers["Cache-Control"] = "private, no-store"
    return {"language": body.language}


def throttle(request: Request, username: str) -> None:
    request.app.state.auth_limiter.check(request, username)


def setup_path(request: Request) -> Path:
    return Path(request.app.state.settings.state_directory) / "auth-setup-token"


@router.get("/session")
def current_session(request: Request, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    with request.app.state.factory() as session:
        current = session_user(request, session)
        if current:
            return session_record(session, *current)
        settings = session.get(AuthSettings, 1)
        return {
            "setup_required": session.scalar(select(User.id).limit(1)) is None,
            "registration_code_required": settings.registration_code_required if settings else True,
            "user": None,
            "csrf_token": None,
        }


@router.get("/sessions")
def list_sessions(request: Request, response: Response) -> list[dict[str, Any]]:
    from app.authn.session_details import client_description

    response.headers["Cache-Control"] = "no-store"
    with request.app.state.factory() as session:
        current = session_user(request, session)
        if current is None:
            raise HTTPException(401, "Sign in to view your sessions")
        return [
            {
                "id": record.id,
                "current": record.token_hash == current[1].token_hash,
                "created_at": record.created_at,
                "last_seen_at": record.last_seen_at,
                "expires_at": record.expires_at,
                "ip_address": record.ip_address,
                "user_agent": record.user_agent,
                "location": record.location,
                **client_description(record.user_agent),
            }
            for record in session.scalars(
                select(AuthSession)
                .where(AuthSession.user_id == current[0].id, AuthSession.expires_at > time.time())
                .order_by(AuthSession.created_at.desc(), AuthSession.id)
            )
        ]


@router.delete("/sessions/others", status_code=204)
def revoke_other_sessions(request: Request, response: Response) -> None:
    from app.authn.session_details import revoke_session

    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        current = session_user(request, session)
        if current is None:
            raise HTTPException(401, "Sign in to manage your sessions")
        check_csrf(request, current[1])
        for record in session.scalars(
            select(AuthSession).where(
                AuthSession.user_id == current[0].id,
                AuthSession.token_hash != current[1].token_hash,
            )
        ):
            revoke_session(session, record)
        record_account(session, "auth.sessions_revoked", current[0])
    response.headers["Cache-Control"] = "no-store"


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_one_session(session_id: str, request: Request, response: Response) -> None:
    from app.authn.session_details import revoke_session

    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        current = session_user(request, session)
        if current is None:
            raise HTTPException(401, "Sign in to manage your sessions")
        check_csrf(request, current[1])
        record = session.scalar(
            select(AuthSession).where(
                AuthSession.id == session_id, AuthSession.user_id == current[0].id
            )
        )
        if record is None:
            raise HTTPException(404, "Session not found")
        if record.token_hash == current[1].token_hash:
            response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
        revoke_session(session, record)
        record_account(session, "auth.session_revoked", current[0])
    response.headers["Cache-Control"] = "no-store"


@router.post("/setup", status_code=201)
def setup(body: SetupInput, request: Request, response: Response) -> dict[str, Any]:
    check_origin(request)
    throttle(request, body.username)
    try:
        secret = setup_path(request).read_text().strip()
    except FileNotFoundError:
        raise HTTPException(409, "Initial administrator setup is not available") from None
    if not hmac.compare_digest(secret.encode(), body.setup_token.encode()):
        raise HTTPException(403, "Invalid setup token")
    encoded = hash_password(body.password)
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        begin_write(session)
        if session.scalar(select(User.id).limit(1)) is not None:
            raise HTTPException(409, "Initial administrator setup is already complete")
        user = User(
            id=LOCAL_OWNER_ID,
            username=body.username,
            password_hash=encoded,
            role_ids=["administrator"],
        )
        session.add(user)
        session.flush()
        result = new_session(request, response, session, user)
        record_account(session, "auth.setup_completed", user)
        session.commit()
    setup_path(request).unlink(missing_ok=True)
    return result


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response) -> dict[str, Any]:
    check_origin(request)
    with request.app.state.factory() as session:
        user = find_login_user(session, body.username)
        throttle(request, user.username if user else body.username.strip())
        identity = (user.id, user.password_hash) if user else None
    if identity is None:
        hash_password(body.password)
        raise HTTPException(401, "Invalid sign-in details")
    valid = verify_password(body.password, identity[1])
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        # Recheck the exact credential after hashing without a transaction or lock.
        begin_write(session)
        user = find_login_user(session, body.username)
        if not valid or user is None or user.disabled or (user.id, user.password_hash) != identity:
            raise HTTPException(401, "Invalid sign-in details")
        result = new_session(request, response, session, user)
        record_account(session, "auth.signed_in", user)
        session.commit()
        return result


@router.post("/register", status_code=201)
def register(body: RegistrationInput, request: Request, response: Response) -> dict[str, Any]:
    check_origin(request)
    throttle(request, body.username)
    encoded = hash_password(body.password)
    try:
        with request.app.state.fleet.lock, request.app.state.factory() as session:
            begin_write(session)
            if session.scalar(select(User.id).limit(1)) is None:
                raise HTTPException(409, "An administrator must complete initial setup first")
            settings = session.get(AuthSettings, 1)
            code = None
            if body.registration_code:
                code = session.scalar(
                    select(RegistrationCode).where(
                        RegistrationCode.token_hash == token_hash(body.registration_code)
                    )
                )
                if (
                    code is None
                    or code.revoked
                    or code.redeemed_at is not None
                    or code.expires_at <= time.time()
                ):
                    raise HTTPException(400, "Invalid or expired registration code")
            elif settings is None or settings.registration_code_required:
                raise HTTPException(400, "A registration code is required")
            role_ids = code.role_ids if code else ["member"]
            role_ids = [
                role.id for role in session.scalars(select(Role).where(Role.id.in_(role_ids)))
            ]
            user = User(
                username=body.username,
                password_hash=encoded,
                role_ids=[identifier for identifier in role_ids if identifier != "administrator"],
            )
            session.add(user)
            session.flush()
            if code:
                code.redeemed_at = time.time()
                code.redeemed_by = user.id
                for group in session.scalars(
                    select(UserGroup).where(UserGroup.id.in_(code.group_ids))
                ):
                    group.members = [
                        *group.members,
                        {
                            "user_id": user.id,
                            **code.group_permissions.get(
                                group.id,
                                {
                                    "can_create": True,
                                    "can_edit_others": False,
                                    "can_delete_others": False,
                                },
                            ),
                        },
                    ]
            result = new_session(request, response, session, user)
            record_account(session, "auth.registered", user)
            session.commit()
            return result
    except IntegrityError as error:
        raise HTTPException(409, "That username is not available") from error


@router.post("/password", status_code=204)
def change_password(body: PasswordChangeInput, request: Request, response: Response) -> None:
    with request.app.state.factory() as session:
        current = session_user(request, session)
        if current is None:
            raise HTTPException(401, "Sign in to change your password")
        user, record = current
        check_csrf(request, record)
        throttle(request, user.username)
        identity = (user.id, user.password_hash)
    if not verify_password(body.current_password, identity[1]):
        raise HTTPException(
            400,
            detail=[{"loc": ["body", "current_password"], "msg": "Current password is incorrect."}],
        )
    encoded = hash_password(body.new_password)
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        begin_write(session)
        current = session_user(request, session)
        if current is None or (current[0].id, current[0].password_hash) != identity:
            raise HTTPException(409, "Account changed; sign in again")
        user, record = current
        check_csrf(request, record)
        user.password_hash = encoded
        from app.companion.companion_auth import revoke_sessions

        revoke_sessions(session, user.id)
        session.execute(delete(RecoveryToken).where(RecoveryToken.user_id == user.id))
        session.execute(
            delete(AuthSession).where(
                AuthSession.user_id == user.id,
                AuthSession.token_hash != record.token_hash,
            )
        )
        record_account(session, "auth.password_changed", user)
        session.commit()
    response.headers["Cache-Control"] = "no-store"


@router.post("/changelog")
def visit_release(request: Request) -> dict[str, str | None]:
    # Claim the release atomically: another browser for this account must not
    # receive the same unseen history. A first visit establishes the baseline.
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        begin_write(session)
        current = session_user(request, session)
        if current is None:
            raise HTTPException(401, "Sign in to view your changelog")
        user, record = current
        check_csrf(request, record)
        previous = user.last_seen_version
        if previous is None or release_version(previous) < release_version(__version__):
            user.last_seen_version = __version__
        session.commit()
        return {"current_version": __version__, "previous_version": previous}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        current = session_user(request, session)
        if current:
            check_csrf(request, current[1])
            from app.authn.session_details import revoke_session

            revoke_session(session, current[1])
            record_account(session, "auth.signed_out", current[0])
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
