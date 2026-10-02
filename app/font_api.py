"""Font library HTTP operations. Hidden fonts remain available to saved layouts."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api import db
from app.font_assets import MAX_FONT_BYTES

router = APIRouter(prefix="/api/font-assets")


@router.get("")
def list_fonts(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    return list(request.app.state.fonts.list())


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
        with request.app.state.worker.lock:
            try:
                return dict(request.app.state.fonts.add(data))
            except ValueError as error:
                raise HTTPException(422, str(error)) from error

    return await run_in_threadpool(store)


@router.delete("/{identifier}")
def hide_font(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return change_visibility(identifier, True, request)


@router.post("/{identifier}/restore")
def restore_font(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return change_visibility(identifier, False, request)


def change_visibility(identifier: str, archived: bool, request: Request) -> dict[str, Any]:
    try:
        return dict(request.app.state.fonts.set_archived(identifier, archived))
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
