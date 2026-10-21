"""Font library HTTP operations. Hidden fonts remain available to saved layouts."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.access import Action, Resource, access_context
from app.asset_access import library_asset_visible, require_asset
from app.deletion import retain
from app.font_assets import MAX_FONT_BYTES
from app.http import db

router = APIRouter(prefix="/api/font-assets")


@router.get("")
def list_fonts(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    return [
        asset
        for asset in request.app.state.fonts.list()
        if library_asset_visible(request, "font_asset", asset)
    ]


@router.post("", status_code=201)
async def upload_font(request: Request) -> dict[str, Any]:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_FONT_BYTES:
            raise HTTPException(413, "Upload a font of at most 5 MB")
        chunks.append(chunk)
    data = b"".join(chunks)

    def store() -> dict[str, Any]:
        with request.app.state.fleet.lock:
            context = access_context(request)
            context.require(Action.WRITE, Resource("font_asset", owner_id=context.actor.id))
            try:
                return dict(request.app.state.fonts.add(data, owner_id=context.actor.id))
            except ValueError as error:
                raise HTTPException(422, str(error)) from error

    return await run_in_threadpool(store)


@router.delete("/{identifier}")
def hide_font(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return change_visibility(identifier, True, request, session)


@router.delete("/{identifier}/permanent")
def delete_font(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, bool]:
    actor = access_context(request).actor
    if not actor.is_admin:
        raise HTTPException(403, "Administrator access is required")
    metadata = require_asset(request, session, "font_asset", identifier, Action.WRITE)
    retain(session, "fonts", identifier, metadata["family"], metadata["owner_id"], actor.id)
    from app.job_access import reconcile_access_holds

    reconcile_access_holds(session)
    return {"deleted": True}


@router.post("/{identifier}/restore")
def restore_font(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return change_visibility(identifier, False, request, session)


def change_visibility(
    identifier: str, archived: bool, request: Request, session: Session
) -> dict[str, Any]:
    require_asset(request, session, "font_asset", identifier, Action.WRITE)
    try:
        return dict(request.app.state.fonts.set_archived(identifier, archived))
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
