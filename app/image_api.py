"""Image library operations; hidden assets remain available to saved labels."""

from collections.abc import Iterable
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.access import Action, Resource, access_context
from app.api import db
from app.image_assets import MAX_IMAGE_BYTES
from app.models import LabelTemplate, PrintJob, PrintRun, TemplateRevision
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


def image_metadata(identifier: str, request: Request, action: Action) -> dict[str, Any]:
    try:
        asset = dict(request.app.state.images.metadata(identifier))
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    access_context(request).require(action, Resource("image_asset", identifier, asset["owner_id"]))
    return asset


@router.get("/{identifier}/preview")
def preview_image(
    identifier: str,
    request: Request,
    size: Literal["thumbnail", "large"] = "thumbnail",
    session: Session = Depends(db, scope="function"),
) -> Response:
    image_metadata(identifier, request, Action.READ)
    return Response(
        request.app.state.images.preview(identifier, size),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/{identifier}")
def rename_image(
    identifier: str,
    body: ImageNameInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    image_metadata(identifier, request, Action.WRITE)
    return dict(request.app.state.images.rename(identifier, body.name))


def references_image(value: Any, identifier: str) -> bool:
    if isinstance(value, dict):
        return value.get("image_asset") == identifier or any(
            references_image(child, identifier) for child in value.values()
        )
    if isinstance(value, list):
        return any(references_image(child, identifier) for child in value)
    return False


@router.delete("/{identifier}/permanent")
def delete_image(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, bool]:
    image_metadata(identifier, request, Action.WRITE)
    # The db dependency serializes this check and deletion with submission, saves and rendering.
    columns: tuple[InstrumentedAttribute[dict[str, Any]], ...] = (
        LabelTemplate.document,
        TemplateRevision.document,
        PrintJob.template_snapshot,
        PrintRun.manifest,
    )
    for column in columns:
        documents: Iterable[dict[str, Any]] = session.scalars(
            select(column).execution_options(yield_per=100)
        )
        if any(references_image(value, identifier) for value in documents):
            raise HTTPException(
                409,
                "Image is used by a saved template, template revision, job or CSV run. "
                "Hide it instead to preserve existing labels.",
            )
    request.app.state.images.delete(identifier)
    return {"deleted": True}


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
