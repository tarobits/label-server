"""Font library HTTP operations. Hidden fonts remain available to saved layouts."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.access import Action, access_context
from app.asset_access import (
    AssetSharingInput,
    asset_record,
    delete_asset,
    library_asset_visible,
    require_asset,
    require_asset_scope,
    share_asset,
)
from app.font_assets import MAX_FONT_BYTES
from app.http import db

router = APIRouter(prefix="/api/font-assets")


@router.get("")
def list_fonts(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    return [
        asset_record(request, "font_asset", asset)
        for asset in request.app.state.fonts.list()
        if library_asset_visible(request, "font_asset", asset)
    ]


@router.post("", status_code=201)
async def upload_font(
    request: Request,
    scope: Literal["personal", "group", "global"] = "personal",
    group_id: str | None = None,
) -> dict[str, Any]:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_FONT_BYTES:
            raise HTTPException(413, "Upload a font of at most 5 MB")
        chunks.append(chunk)
    data = b"".join(chunks)

    def store() -> dict[str, Any]:
        with request.app.state.fleet.lock, request.app.state.factory() as session:
            context = access_context(request)
            require_asset_scope(request, session, "font_asset", scope, group_id)
            try:
                return asset_record(
                    request,
                    "font_asset",
                    request.app.state.fonts.add(
                        data, owner_id=context.actor.id, scope=scope, group_id=group_id
                    ),
                )
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
    return delete_asset(request, session, "font_asset", identifier)


@router.post("/{identifier}/restore")
def restore_font(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return change_visibility(identifier, False, request, session)


def change_visibility(
    identifier: str, archived: bool, request: Request, session: Session
) -> dict[str, Any]:
    require_asset(
        request, session, "font_asset", identifier, Action.DELETE if archived else Action.WRITE
    )
    try:
        return asset_record(
            request, "font_asset", request.app.state.fonts.set_archived(identifier, archived)
        )
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.put("/{identifier}/sharing")
def sharing(
    identifier: str,
    body: AssetSharingInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    return share_asset(request, session, "font_asset", identifier, body)
