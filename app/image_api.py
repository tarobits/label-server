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
from app.asset_access import library_asset_visible, require_asset
from app.deletion import retain
from app.http import db
from app.image_assets import MAX_IMAGE_BYTES
from app.models import LabelTemplate, PrintJob, PrintRun, TemplateRevision
from app.request_models import PrintRequest
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
    metadata = image_metadata(identifier, request, Action.WRITE, session)
    actor = access_context(request).actor
    if actor.is_admin:
        retain(session, "images", identifier, metadata["name"], metadata["owner_id"], actor.id)
        from app.job_access import reconcile_access_holds

        reconcile_access_holds(session)
        return {"deleted": True}
    # Hold the mutation lock across reference checks and deletion.
    columns: tuple[InstrumentedAttribute[Any], ...] = (
        LabelTemplate.document,
        TemplateRevision.document,
        PrintJob.template_snapshot,
        PrintRun.manifest,
        PrintRequest.labels,
    )
    for column in columns:
        documents: Iterable[Any] = session.scalars(select(column).execution_options(yield_per=100))
        if any(references_image(value, identifier) for value in documents):
            raise HTTPException(
                409,
                "Image is used by a saved template, template revision, job, CSV run or print request. "
                "Hide it instead to preserve existing labels.",
            )
    retain(session, "images", identifier, metadata["name"], metadata["owner_id"], actor.id)
    return {"deleted": True}


@router.get("")
def list_images(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    return [
        asset
        for asset in request.app.state.images.list()
        if library_asset_visible(request, "image_asset", asset)
    ]


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
        with request.app.state.fleet.lock:
            context = access_context(request)
            context.require(Action.WRITE, Resource("image_asset", owner_id=context.actor.id))
            try:
                return dict(
                    request.app.state.images.add(
                        data,
                        request.query_params.get("name", "Uploaded image"),
                        owner_id=context.actor.id,
                    )
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
    image_metadata(identifier, request, Action.WRITE, session)
    try:
        return dict(request.app.state.images.set_archived(identifier, archived))
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
