"""Asset ownership and the assets embedded in readable saved documents.

Sharing a template shares the graphics needed to render it, without sharing the
owner's library or allowing its entries to be renamed, hidden or deleted.
"""

from typing import Any, Literal, cast

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import Action, Resource, access_context
from app.asset_store import ASSET_ID
from app.models import LabelTemplate, PrintJob, PrintRun, TemplateRevision
from app.request_models import PrintRequest

AssetKind = Literal["image_asset", "font_asset"]


def asset_references(value: Any) -> set[tuple[AssetKind, str]]:
    if isinstance(value, dict):
        references: set[tuple[AssetKind, str]] = set()
        image = value.get("image_asset")
        font = value.get("font")
        if isinstance(image, str) and ASSET_ID.fullmatch(image):
            references.add(("image_asset", image))
        if isinstance(font, str) and ASSET_ID.fullmatch(font):
            references.add(("font_asset", font))
        for child in value.values():
            references.update(asset_references(child))
        return references
    if isinstance(value, list):
        return set().union(*(asset_references(child) for child in value))
    return set()


def library_asset_visible(request: Request, kind: AssetKind, metadata: dict[str, Any]) -> bool:
    context = access_context(request)
    return context.policy.allows(
        context.actor, Action.READ, Resource(kind, metadata["id"], metadata["owner_id"])
    )


def referenced_by_readable_document(
    request: Request, session: Session, kind: AssetKind, identifier: str
) -> bool:
    context = access_context(request)
    reference = (kind, identifier)
    for template in session.scalars(select(LabelTemplate)):
        from app.deletion import is_deleted

        if is_deleted(session, "templates", template.id):
            continue
        resource = Resource(
            "template",
            template.id,
            template.owner_id,
            scope=template.scope,
            group_id=template.group_id,
        )
        if context.policy.allows(context.actor, Action.READ, resource):
            if reference in asset_references(template.document):
                return True
            # Reading a template includes its saved history and the artwork
            # needed to inspect or restore those immutable revisions.
            for revision in session.scalars(
                select(TemplateRevision).where(TemplateRevision.template_id == template.id)
            ):
                if reference in asset_references(revision.document):
                    return True
    for model, field, resource_kind in (
        (PrintJob, PrintJob.template_snapshot, "job"),
        (PrintRun, PrintRun.manifest, "run"),
        (PrintRequest, PrintRequest.labels, "request"),
    ):
        for record in session.scalars(select(model)):
            saved = cast(PrintJob | PrintRun | PrintRequest, record)
            if (
                isinstance(saved, PrintRun)
                and saved.submitted_at is None
                and saved.owner_id != context.actor.id
                and not context.actor.is_admin
            ):
                continue
            resource = Resource(resource_kind, saved.id, saved.owner_id, saved.destination_id)
            if context.policy.allows(
                context.actor, Action.READ, resource
            ) and reference in asset_references(getattr(saved, field.key)):
                return True
    return False


def require_asset(
    request: Request,
    session: Session,
    kind: AssetKind,
    identifier: str,
    action: Action = Action.READ,
) -> dict[str, Any]:
    store = request.app.state.images if kind == "image_asset" else request.app.state.fonts
    try:
        metadata = dict(store.metadata(identifier))
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    context = access_context(request)
    resource = Resource(kind, identifier, metadata["owner_id"])
    if context.policy.allows(context.actor, action, resource):
        return metadata
    if action == Action.READ and referenced_by_readable_document(
        request, session, kind, identifier
    ):
        return metadata
    context.require(action, resource)
    return metadata


def require_document_assets(
    request: Request, session: Session, document: Any, *, allow_missing: bool = False
) -> None:
    for kind, identifier in asset_references(document):
        try:
            require_asset(request, session, kind, identifier)
        except HTTPException as error:
            if error.status_code == 404:
                from app.deletion import is_deleted

                if allow_missing and is_deleted(
                    session, "images" if kind == "image_asset" else "fonts", identifier
                ):
                    continue
                raise HTTPException(422, "A referenced image or font is missing") from error
            raise
