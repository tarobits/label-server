"""Resource visibility shared by list queries and object endpoints."""

from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.access import Action, Resource, access_context
from app.models import (
    Base,
    Batch,
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


def require_record(request: Request, value: Base, action: Action = Action.READ) -> None:
    context = access_context(request)
    if isinstance(value, LabelTemplate):
        context.require(
            action,
            Resource(
                "template", value.id, value.owner_id, scope=value.scope, group_id=value.group_id
            ),
        )
    elif isinstance(value, (PrintJob, PrintRun)):
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
                "job" if isinstance(value, PrintJob) else "run",
                value.id,
                value.owner_id,
                value.destination_id,
            ),
        )
    elif isinstance(value, Batch):
        context.require_destination(value.printer_id, "moderator")
    elif isinstance(value, FlushRequest):
        if not context.can_destination(value.destination_id, "moderator"):
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


def visible_destinations(request: Request, session: Session, minimum: str = "request") -> list[str]:
    context = access_context(request)
    identifiers = [value.id for value in session.scalars(select(PrinterDevice))]
    identifiers.extend(value.id for value in session.scalars(select(PrinterGroup)))
    return [
        identifier for identifier in identifiers if context.can_destination(identifier, minimum)
    ]


def rendering_destination(
    request: Request, session: Session, identifier: str | None, *, allow_unassigned: bool = False
) -> str | None:
    from app.destinations import resolve_destination

    context = access_context(request)
    if identifier is not None:
        context.require_destination(identifier)
        return resolve_destination(session, identifier)
    printers = [
        device.id
        for device in session.scalars(select(PrinterDevice))
        if not device.config.get("retired") and context.can_destination(device.id)
    ]
    groups = [
        group.id
        for group in session.scalars(select(PrinterGroup))
        if context.can_destination(group.id)
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
    return query.where(
        or_(
            PrintJob.owner_id == context.actor.id,
            PrintJob.destination_id.in_(visible_destinations(request, session, "moderator")),
        )
    )


def template_access(
    request: Request, template: LabelTemplate, action: Action = Action.READ
) -> bool:
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
    if scope == "global" and not context.actor.is_admin:
        raise HTTPException(403, "Only administrators can publish global templates")
    if scope == "group":
        if not group_id or session.get(UserGroup, group_id) is None:
            raise HTTPException(422, "Choose a user group")
        membership = context.actor.group_memberships.get(group_id)
        if not context.actor.is_admin and (membership is None or not membership.can_create):
            raise HTTPException(403, "You cannot create templates in this group")
    elif group_id is not None:
        raise HTTPException(422, "Only group templates may select a user group")
