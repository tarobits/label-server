"""Image library operations; hidden assets remain available to saved labels."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api import db
from app.image_assets import MAX_IMAGE_BYTES

router = APIRouter(prefix="/api/image-assets")


@router.get("")
def list_images(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    return list(request.app.state.images.list())


@router.post("", status_code=201)
async def upload_image(request: Request) -> dict[str, Any]:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Upload an image of at most 5 MB")
        chunks.append(chunk)
    data = b"".join(chunks)

    def store() -> dict[str, Any]:
        with request.app.state.worker.lock:
            try:
                return dict(
                    request.app.state.images.add(
                        data, request.query_params.get("name", "Uploaded image")
                    )
                )
            except ValueError as error:
                raise HTTPException(422, str(error)) from error

    return await run_in_threadpool(store)


@router.delete("/{identifier}")
def hide_image(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return change_visibility(identifier, True, request)


@router.post("/{identifier}/restore")
def restore_image(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return change_visibility(identifier, False, request)


def change_visibility(identifier: str, archived: bool, request: Request) -> dict[str, Any]:
    try:
        return dict(request.app.state.images.set_archived(identifier, archived))
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
