"""Explicit, authorized printer substitutions for frozen queued work."""

import copy
import time
from typing import Any

from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.activity_redaction import personal_printer_change
from app.audit.print_audit import actor_snapshot, unknown_attribution
from app.authn.access import access_context
from app.authn.authorization import visible_destinations
from app.http import db, job_template_name, record
from app.models import (
    FlushRequest,
    LabelCopy,
    PrinterDevice,
    PrinterGroup,
    PrintJob,
    PrintRun,
    State,
)
from app.printing.job_access import job_eligible
from app.printing.queue_routing_models import QueueDestinationChange
from app.schemas import CopySelectionInput
from app.transaction_routes import TransactionRouter

router = TransactionRouter(prefix="/api")


class ChangePrinterInput(CopySelectionInput):
    printer_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=1000)


def destination_snapshot(session: Session, identifier: str) -> dict[str, str]:
    value = session.get(PrinterDevice, identifier) or session.get(PrinterGroup, identifier)
    return {"id": identifier, "name": value.name if value else identifier}


@router.post("/queue/change-printer")
def change_printer(
    body: ChangePrinterInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    context = access_context(request)
    if not context.has_permission("queue.change_printer"):
        raise HTTPException(403, "The Change printers for queued work permission is required")
    context.require_printer(body.printer_id, "manage_queue")
    target = session.get(PrinterDevice, body.printer_id)
    if target is None or target.config.get("retired"):
        raise HTTPException(422, "Choose an active replacement printer")
    fleet = request.app.state.fleet
    if target.id not in fleet.workers:
        raise HTTPException(409, "The replacement printer's configuration is unavailable")
    wanted = set(body.copy_ids)
    if len(wanted) != len(body.copy_ids):
        raise HTTPException(422, "Select each copy once")
    copies = list(session.scalars(select(LabelCopy).where(LabelCopy.id.in_(wanted))))
    if len(copies) != len(wanted):
        raise HTTPException(409, "Some selected copies are no longer available. Refresh the queue")
    jobs = list(
        session.scalars(select(PrintJob).where(PrintJob.id.in_({c.job_id for c in copies})))
    )
    for job in jobs:
        context.require_printer(job.destination_id, "manage_queue")
    if any(label.state != State.QUEUED for label in copies):
        raise HTTPException(409, "Only queued copies can change printer. Refresh the queue")
    job_ids = {job.id for job in jobs}
    run_ids = {job.run_id for job in jobs if job.run_id}
    scope = list(
        session.scalars(
            select(LabelCopy)
            .join(PrintJob)
            .where(or_(PrintJob.id.in_(job_ids), PrintJob.run_id.in_(run_ids)))
        )
    )
    if any(label.state in (State.PRINTING, State.NEEDS_REVIEW) for label in scope):
        raise HTTPException(
            409,
            "A selected item or CSV run is printing or awaiting review. Finish or review its batch first",
        )
    if any(label.state == State.QUEUED and label.id not in wanted for label in scope):
        raise HTTPException(
            409,
            "Select all remaining queued copies of each item and CSV run before changing printer",
        )
    for pending in session.scalars(select(FlushRequest).where(FlushRequest.completed.is_(False))):
        if wanted.intersection(pending.copy_ids):
            raise HTTPException(
                409,
                "Selected copies are reserved for printing. Cancel their pending print reservation first",
            )
    for job in jobs:
        if job.destination_id == target.id:
            raise HTTPException(
                409, "Some selected items already use this printer. Choose another printer"
            )
        if fleet.enforce_job_access and not job_eligible(session, job):
            raise HTTPException(
                409,
                "A selected item has an access or content hold. An administrator must review it first",
            )
        if not fleet.supports_geometry(job, target.id):
            raise HTTPException(
                409,
                "The replacement printer does not support the selected labels' saved resolution or printable area",
            )
    stamp = time.time()
    person = actor_snapshot(context.actor) or {
        "id": context.actor.id,
        "name": context.actor.username,
    }
    changes = []
    for job in jobs:
        run = session.get(PrintRun, job.run_id) if job.run_id else None
        event = QueueDestinationChange(
            job_id=job.id,
            run_id=job.run_id,
            job_name=job_template_name(session, job),
            copy_ids=[label.id for label in copies if label.job_id == job.id],
            actor=person,
            source_id=job.destination_id,
            target_id=target.id,
            source=destination_snapshot(session, job.destination_id),
            target=destination_snapshot(session, target.id),
            previous_assignment=destination_snapshot(session, run.assigned_printer_id)
            if run and run.assigned_printer_id
            else None,
            reason=body.reason.strip(),
            created_at=stamp,
        )
        session.add(event)
        session.flush()
        snapshot = record(event)
        attribution = copy.deepcopy(job.attribution or unknown_attribution())
        attribution["destination_changes"] = [*attribution.get("destination_changes", []), snapshot]
        job.attribution = attribution
        job.destination_id = target.id
        changes.append(snapshot)
    for identifier in run_ids:
        run = session.get(PrintRun, identifier)
        assert run is not None
        run.destination_id = target.id
        run.assigned_printer_id = target.id
    session.flush()
    return {"changes": changes, "copies": len(copies)}


@router.get("/printer-changes/page")
def change_history(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    before: float | None = Query(default=None, ge=0, allow_inf_nan=False),
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    stamp = time.time() if before is None else before
    query = select(QueueDestinationChange).where(QueueDestinationChange.created_at <= stamp)
    context = access_context(request)
    if not context.actor.is_admin:
        allowed = visible_destinations(request, session, "view_activity")
        query = query.where(
            or_(
                QueueDestinationChange.source_id.in_(allowed),
                QueueDestinationChange.target_id.in_(allowed),
                QueueDestinationChange.job_id.in_(
                    select(PrintJob.id).where(PrintJob.owner_id == context.actor.id)
                ),
            )
        )
    return {
        "items": [
            record(event)
            if context.can_printer(event.source_id, "view_activity")
            or context.can_printer(event.target_id, "view_activity")
            else personal_printer_change(context, record(event))
            for event in session.scalars(
                query.order_by(QueueDestinationChange.created_at.desc(), QueueDestinationChange.id)
                .offset(offset)
                .limit(limit)
            )
        ],
        "total": session.scalar(select(func.count()).select_from(query.subquery())),
        "before": stamp,
    }
