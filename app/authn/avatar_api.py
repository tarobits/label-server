"""Account-only profile picture editing and retrieval."""

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.audit.account_audit import record_account
from app.authn.auth import check_csrf, session_user
from app.authn.avatars import (
    MAX_UPLOAD,
    avatar_version,
    normalize_avatar,
    read_avatar,
    remove_avatar,
    save_avatar,
)
from app.models import User

router = APIRouter(prefix="/api/auth/avatar", tags=["account"])


def account(request: Request, session: Session, *, write: bool = False) -> User:
    current = session_user(request, session)
    if current is None:
        raise HTTPException(401, "Sign in to manage your profile picture")
    if write:
        check_csrf(request, current[1])
    return current[0]


@router.get("/info")
def picture_info(request: Request) -> dict[str, str | None]:
    with request.app.state.factory() as session:
        user = account(request, session)
        return {"avatar_version": avatar_version(session, user.id)}


@router.get("")
def picture(request: Request) -> Response:
    with request.app.state.factory() as session:
        user = account(request, session)
        try:
            data = read_avatar(session, user.id)
        except FileNotFoundError:
            raise HTTPException(404, "No profile picture") from None
        return Response(
            data, media_type="image/png", headers={"Cache-Control": "private, no-store"}
        )


@router.put("")
async def upload(request: Request) -> dict[str, str | None]:
    def authenticate() -> None:
        with request.app.state.factory() as session:
            account(request, session, write=True)

    await run_in_threadpool(authenticate)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_UPLOAD:
            raise HTTPException(413, "Profile pictures are limited to 5 MB")
        data.extend(chunk)

    def persist() -> dict[str, str | None]:
        try:
            normalized = normalize_avatar(bytes(data))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
            user = account(request, session, write=True)
            save_avatar(session, user.id, normalized)
            record_account(session, "account.picture_changed", user, configured=True)
            return {"avatar_version": avatar_version(session, user.id)}

    return await run_in_threadpool(persist)


@router.delete("", status_code=204)
def remove(request: Request) -> None:
    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        user = account(request, session, write=True)
        remove_avatar(session, user.id)
        record_account(session, "account.picture_changed", user, configured=False)
