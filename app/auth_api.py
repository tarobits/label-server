"""First-run enrollment and browser sessions; no anonymous production API access."""

import hmac
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.auth import (
    COOKIE_NAME,
    check_csrf,
    check_origin,
    hash_password,
    new_session,
    session_record,
    session_user,
    token_hash,
    verify_password,
)
from app.identity import LOCAL_OWNER_ID
from app.models import AuthSession, AuthSettings, RegistrationCode, Role, User, UserGroup

router = APIRouter(prefix="/api/auth", tags=["authentication"])
Password = Annotated[str, Field(min_length=12, max_length=256)]


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: Password

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


class SetupInput(Credentials):
    setup_token: str = Field(min_length=1, max_length=256)


class RegistrationInput(Credentials):
    registration_code: str | None = Field(default=None, max_length=256)


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def throttle(request: Request, username: str) -> None:
    request.app.state.auth_limiter.check(request, username)


def setup_path(request: Request) -> Path:
    database = make_url(request.app.state.settings.database_url).database
    return Path(database or "data/labels.db").resolve().parent / "auth-setup-token"


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
        session.execute(text("BEGIN IMMEDIATE"))
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
        session.commit()
    setup_path(request).unlink(missing_ok=True)
    return result


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response) -> dict[str, Any]:
    check_origin(request)
    throttle(request, body.username)
    with request.app.state.fleet.lock, request.app.state.factory() as session:
        # Serialize password verification and session creation against account resets.
        session.execute(text("BEGIN IMMEDIATE"))
        user = session.scalar(select(User).where(User.username == body.username.lower()))
        if user is None:
            hash_password(body.password)
            raise HTTPException(401, "Invalid username or password")
        valid = verify_password(body.password, user.password_hash)
        if not valid or user.disabled:
            raise HTTPException(401, "Invalid username or password")
        result = new_session(request, response, session, user)
        session.commit()
        return result


@router.post("/register", status_code=201)
def register(body: RegistrationInput, request: Request, response: Response) -> dict[str, Any]:
    check_origin(request)
    throttle(request, body.username)
    encoded = hash_password(body.password)
    try:
        with request.app.state.fleet.lock, request.app.state.factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
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
                            "can_create": True,
                            "can_edit_others": False,
                            "can_delete_others": False,
                        },
                    ]
            result = new_session(request, response, session, user)
            session.commit()
            return result
    except IntegrityError as error:
        raise HTTPException(409, "That username is not available") from error


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        current = session_user(request, session)
        if current:
            check_csrf(request, current[1])
            session.execute(
                delete(AuthSession).where(AuthSession.token_hash == current[1].token_hash)
            )
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
