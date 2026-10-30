"""Asset ownership and the assets embedded in readable saved documents.

Sharing a template shares the graphics needed to render it, without sharing the
owner's library or allowing its entries to be renamed, hidden or deleted.
"""

from typing import Any, Iterable, Literal, cast

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.access import Action, Resource, access_context
from app.asset_store import ASSET_ID
from app.models import LabelTemplate, PrintJob, PrintRun, TemplateRevision, User, UserGroup
from app.request_models import PrintRequest

AssetKind = Literal["image_asset", "font_asset"]


class AssetSharingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["personal", "group", "global"] = "personal"
    group_id: str | None = None


def asset_resource(kind: AssetKind, metadata: dict[str, Any]) -> Resource:
    return Resource(
        kind,
        metadata["id"],
        metadata["owner_id"],
        scope=metadata.get("scope", "personal"),
        group_id=metadata.get("group_id"),
    )


def asset_record(request: Request, kind: AssetKind, metadata: dict[str, Any]) -> dict[str, Any]:
    context = access_context(request)
    resource = asset_resource(kind, metadata)
    owner = {}
    if context.actor.is_admin:
        names = getattr(request.state, "asset_owner_names", None)
        if names is None:
            with request.app.state.factory() as session:
                names = dict(session.execute(select(User.id, User.username)).all())
            request.state.asset_owner_names = names
        owner["owner_name"] = names.get(metadata["owner_id"])
    group_name = None
    if metadata.get("group_id"):
        with request.app.state.factory() as session:
            group = session.get(UserGroup, metadata["group_id"])
            group_name = group.name if group else "Deleted group"
    return {
        **metadata,
        **owner,
        "group_name": group_name,
        "can_edit": context.can(Action.WRITE, resource),
        "can_delete": context.can(Action.DELETE, resource),
        "can_share": context.actor.is_admin or metadata["owner_id"] == context.actor.id,
    }


def require_asset_scope(
    request: Request, session: Session, kind: AssetKind, scope: str, group_id: str | None
) -> None:
    context = access_context(request)
    namespace = "images" if kind == "image_asset" else "fonts"
    if scope == "group":
        if not group_id or session.get(UserGroup, group_id) is None:
            raise HTTPException(422, "Choose a user group")
        member = context.actor.group_memberships.get(group_id)
        if not context.actor.is_admin and (
            member is None or not getattr(member, namespace).can_create
        ):
            raise HTTPException(403, f"You cannot upload {namespace} in this group")
    else:
        if group_id is not None:
            raise HTTPException(422, "Only group assets may select a user group")
        if scope not in ("personal", "global"):
            raise HTTPException(422, "Invalid asset visibility")
        if not context.has_permission(f"{namespace}.create_{scope}"):
            raise HTTPException(403, f"You cannot upload {scope} {namespace}")


def share_asset(
    request: Request, session: Session, kind: AssetKind, identifier: str, body: AssetSharingInput
) -> dict[str, Any]:
    metadata = require_asset(request, session, kind, identifier, Action.WRITE)
    actor = access_context(request).actor
    if not actor.is_admin and metadata["owner_id"] != actor.id:
        raise HTTPException(403, "Only the owner or an administrator can change asset sharing")
    if (metadata["scope"], metadata["group_id"]) != (body.scope, body.group_id):
        require_asset_scope(request, session, kind, body.scope, body.group_id)
        store = request.app.state.images if kind == "image_asset" else request.app.state.fonts
        metadata = store.set_sharing(identifier, body.scope, body.group_id)
    return asset_record(request, kind, metadata)


def delete_asset(
    request: Request, session: Session, kind: AssetKind, identifier: str
) -> dict[str, bool]:
    from app.deletion import retain
    from app.job_access import reconcile_access_holds

    metadata = require_asset(request, session, kind, identifier, Action.DELETE)
    context = access_context(request)
    namespace = "images" if kind == "image_asset" else "fonts"
    if not context.actor.is_admin and not (
        metadata["scope"] == "global" and context.has_permission(f"{namespace}.delete_global")
    ):
        columns: tuple[InstrumentedAttribute[Any], ...] = (
            LabelTemplate.document,
            TemplateRevision.document,
            PrintJob.template_snapshot,
            PrintRun.manifest,
            PrintRequest.labels,
        )
        for column in columns:
            documents: Iterable[Any] = session.scalars(
                select(column).execution_options(yield_per=100)
            )
            if any((kind, identifier) in asset_references(value) for value in documents):
                raise HTTPException(
                    409,
                    "Asset is used by a saved template, template revision, job, CSV run or print request. Hide it instead to preserve existing labels.",
                )
    retain(
        session,
        namespace,
        identifier,
        metadata.get("name", metadata.get("family", namespace)),
        metadata["owner_id"],
        context.actor.id,
    )
    reconcile_access_holds(session)
    return {"deleted": True}


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
    return context.policy.allows(context.actor, Action.READ, asset_resource(kind, metadata))


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
    resource = asset_resource(kind, metadata)
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
