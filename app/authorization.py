"""Resource visibility shared by list queries and object endpoints."""

from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.access import Action, Resource, access_context
from app.models import (
    Base,
    Batch,
    Cartridge,
    FlushRequest,
    LabelCopy,
    LabelTemplate,
    PrinterDevice,
    PrinterGroup,
    PrintJob,
    PrintRun,
    State,
    TapeProfile,
)
from app.request_models import PrintRequest


def require_record(request: Request, value: Base, action: Action = Action.READ) -> None:
    context = access_context(request)
    if isinstance(value, LabelTemplate):
        from app.deletion import is_deleted

        with request.app.state.factory() as session:
            if is_deleted(session, "templates", value.id):
                raise HTTPException(410, "Template has been deleted")
        context.require(
            action,
            Resource(
                "template", value.id, value.owner_id, scope=value.scope, group_id=value.group_id
            ),
        )
    elif isinstance(value, (PrintJob, PrintRun)):
        kind = "job" if isinstance(value, PrintJob) else "run"
        if action == Action.READ and value.owner_id != context.actor.id:
            query = select(LabelCopy.id).where(
                LabelCopy.state.in_([State.QUEUED, State.PRINTING, State.NEEDS_REVIEW])
            )
            if isinstance(value, PrintJob):
                query = query.where(LabelCopy.job_id == value.id)
            else:
                query = query.join(PrintJob).where(PrintJob.run_id == value.id)
            with request.app.state.factory() as lookup:
                active = lookup.scalar(query.limit(1))
            if active is None:
                kind += "_history"
        if (
            isinstance(value, PrintRun)
            and value.submitted_at is None
            and value.owner_id != context.actor.id
            and not context.actor.is_admin
        ):
            raise HTTPException(403, "This draft belongs to another user")
        context.require(
            action,
            Resource(
                kind,
                value.id,
                value.owner_id,
                value.destination_id,
            ),
        )
    elif isinstance(value, Batch):
        if not (
            value.state == State.NEEDS_REVIEW and context.can_printer(value.printer_id, "review")
        ):
            context.require_printer(value.printer_id, "view_activity")
    elif isinstance(value, FlushRequest):
        if not context.can_printer(value.destination_id, "manage_queue"):
            with request.app.state.factory() as session:
                owners = set(
                    session.scalars(
                        select(PrintJob.owner_id)
                        .join(LabelCopy)
                        .where(LabelCopy.id.in_(value.copy_ids))
                    )
                )
            if owners != {context.actor.id}:
                raise HTTPException(403, "This queue reservation is not yours")
    elif isinstance(value, (PrinterDevice, PrinterGroup)):
        context.require(action, Resource("destination", value.id, destination_id=value.id))
    elif isinstance(value, Cartridge):
        operation = "view"
        if request.url.path.startswith("/api/cartridges/") and request.method not in (
            "GET",
            "HEAD",
        ):
            operation = "edit_notes" if request.url.path.endswith("/notes") else "edit_details"
        context.require_cartridge(value.id, operation)


def visible_destinations(request: Request, session: Session, permission: str = "view") -> list[str]:
    context = access_context(request)
    identifiers = [value.id for value in session.scalars(select(PrinterDevice))]
    identifiers.extend(value.id for value in session.scalars(select(PrinterGroup)))
    return [identifier for identifier in identifiers if context.can_printer(identifier, permission)]


def rendering_destination(
    request: Request, session: Session, identifier: str | None, *, allow_unassigned: bool = False
) -> str | None:
    from app.destinations import resolve_destination

    context = access_context(request)
    if identifier is not None:
        context.require_printer(identifier, "view")
        return resolve_destination(session, identifier)
    printers = [
        device.id
        for device in session.scalars(select(PrinterDevice))
        if not device.config.get("retired") and context.can_printer(device.id, "view")
    ]
    groups = [
        group.id
        for group in session.scalars(select(PrinterGroup))
        if context.can_printer(group.id, "view")
    ]
    choices = printers or groups
    if len(choices) == 1:
        return choices[0]
    if allow_unassigned:
        # Editing an owned template does not require access to physical hardware.
        return None
    if not choices:
        if session.scalar(select(PrinterDevice.id).limit(1)) or session.scalar(
            select(PrinterGroup.id).limit(1)
        ):
            raise HTTPException(403, "No permitted print destination")
        raise HTTPException(409, "No available print destination; ask an administrator for access")
    raise HTTPException(422, "Choose a printer or distribution group")


def visible_jobs(request: Request, session: Session, query: Select[Any]) -> Select[Any]:
    context = access_context(request)
    if context.actor.is_admin:
        return query
    active = (
        exists()
        .where(
            LabelCopy.job_id == PrintJob.id,
            LabelCopy.state.in_([State.QUEUED, State.PRINTING, State.NEEDS_REVIEW]),
        )
        .correlate(PrintJob)
    )
    return query.where(
        or_(
            PrintJob.owner_id == context.actor.id,
            and_(
                active,
                PrintJob.destination_id.in_(visible_destinations(request, session, "view_queue")),
            ),
            and_(
                ~active,
                PrintJob.destination_id.in_(
                    visible_destinations(request, session, "view_activity")
                ),
            ),
        )
    )


def visible_runs(request: Request, session: Session, query: Select[Any]) -> Select[Any]:
    context = access_context(request)
    if context.actor.is_admin:
        return query
    active = (
        select(LabelCopy.id)
        .join(PrintJob)
        .where(
            PrintJob.run_id == PrintRun.id,
            LabelCopy.state.in_([State.QUEUED, State.PRINTING, State.NEEDS_REVIEW]),
        )
        .correlate(PrintRun)
        .exists()
    )
    return query.where(
        or_(
            PrintRun.owner_id == context.actor.id,
            and_(
                PrintRun.submitted_at.is_not(None),
                or_(
                    and_(
                        active,
                        PrintRun.destination_id.in_(
                            visible_destinations(request, session, "view_queue")
                        ),
                    ),
                    and_(
                        ~active,
                        PrintRun.destination_id.in_(
                            visible_destinations(request, session, "view_activity")
                        ),
                    ),
                ),
            ),
        )
    )


def visible_requests(request: Request, session: Session, query: Select[Any]) -> Select[Any]:
    context = access_context(request)
    if context.actor.is_admin:
        return query
    return query.where(
        or_(
            PrintRequest.owner_id == context.actor.id,
            PrintRequest.destination_id.in_(
                visible_destinations(request, session, "approve_requests")
            ),
        )
    )


def template_access(
    request: Request, template: LabelTemplate, action: Action = Action.READ
) -> bool:
    from app.deletion import is_deleted

    with request.app.state.factory() as session:
        if is_deleted(session, "templates", template.id):
            return False
    context = access_context(request)
    return context.policy.allows(
        context.actor,
        action,
        Resource(
            "template",
            template.id,
            template.owner_id,
            scope=template.scope,
            group_id=template.group_id,
        ),
    )


def visible_copy_count(
    request: Request, session: Session, destination: str, profile: TapeProfile
) -> int:
    query = visible_jobs(
        request, session, select(func.count()).select_from(LabelCopy).join(PrintJob)
    )
    return (
        session.scalar(
            query.where(
                LabelCopy.state == State.QUEUED,
                PrintJob.destination_id == destination,
                PrintJob.profile_id == profile.id,
                PrintJob.width_mm == profile.width_mm,
            )
        )
        or 0
    )


def template_scope(request: Request, session: Session, scope: str, group_id: str | None) -> None:
    from app.models import UserGroup

    context = access_context(request)
    if scope == "global" and not context.has_permission("templates.create_global"):
        raise HTTPException(403, "You cannot create global templates")
    if scope == "personal" and not context.has_permission("templates.create_personal"):
        raise HTTPException(403, "You cannot create personal templates")
    if scope == "group":
        if not group_id or session.get(UserGroup, group_id) is None:
            raise HTTPException(422, "Choose a user group")
        membership = context.actor.group_memberships.get(group_id)
        if not context.actor.is_admin and (membership is None or not membership.can_create):
            raise HTTPException(403, "You cannot create templates in this group")
    elif group_id is not None:
        raise HTTPException(422, "Only group templates may select a user group")
