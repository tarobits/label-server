"""Image library operations; hidden assets remain available to saved labels."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import Field, field_validator
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
from app.http import db
from app.image_assets import MAX_IMAGE_BYTES
from app.schemas import Input

router = APIRouter(prefix="/api/image-assets")


class ImageNameInput(Input):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Image name must not be blank")
        return value.strip()


def image_metadata(
    identifier: str, request: Request, action: Action, session: Session
) -> dict[str, Any]:
    return require_asset(request, session, "image_asset", identifier, action)


@router.get("/{identifier}/preview")
def preview_image(
    identifier: str,
    request: Request,
    size: Literal["thumbnail", "large"] = "thumbnail",
    session: Session = Depends(db, scope="function"),
) -> Response:
    image_metadata(identifier, request, Action.READ, session)
    return Response(
        request.app.state.images.preview(identifier, size),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/{identifier}")
def rename_image(
    identifier: str,
    body: ImageNameInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    image_metadata(identifier, request, Action.WRITE, session)
    return asset_record(
        request, "image_asset", request.app.state.images.rename(identifier, body.name)
    )


@router.delete("/{identifier}/permanent")
def delete_image(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, bool]:
    return delete_asset(request, session, "image_asset", identifier)


@router.get("")
def list_images(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    return [
        asset_record(request, "image_asset", asset)
        for asset in request.app.state.images.list()
        if library_asset_visible(request, "image_asset", asset)
    ]


@router.post("", status_code=201)
async def upload_image(
    request: Request,
    scope: Literal["personal", "group", "global"] = "personal",
    group_id: str | None = None,
) -> dict[str, Any]:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Upload an image of at most 5 MB")
        chunks.append(chunk)
    data = b"".join(chunks)

    def store() -> dict[str, Any]:
        with request.app.state.fleet.lock, request.app.state.factory() as session:
            context = access_context(request)
            require_asset_scope(request, session, "image_asset", scope, group_id)
            try:
                return asset_record(
                    request,
                    "image_asset",
                    request.app.state.images.add(
                        data,
                        request.query_params.get("name", "Uploaded image"),
                        owner_id=context.actor.id,
                        scope=scope,
                        group_id=group_id,
                    ),
                )
            except ValueError as error:
                raise HTTPException(422, str(error)) from error

    return await run_in_threadpool(store)


@router.delete("/{identifier}")
def hide_image(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return change_visibility(identifier, True, request, session)


@router.post("/{identifier}/restore")
def restore_image(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return change_visibility(identifier, False, request, session)


def change_visibility(
    identifier: str, archived: bool, request: Request, session: Session
) -> dict[str, Any]:
    image_metadata(identifier, request, Action.DELETE if archived else Action.WRITE, session)
    try:
        return asset_record(
            request, "image_asset", request.app.state.images.set_archived(identifier, archived)
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
    return share_asset(request, session, "image_asset", identifier, body)
