"""Retire registrations and adopt an existing companion connection without losing identity."""

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.access import access_context
from app.action_audit import record_action, record_swap
from app.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.destinations import printer_state
from app.http import db, get
from app.models import (
    Companion,
    CompanionBatch,
    CompanionPrinter,
    FlushRequest,
    LabelCopy,
    PrinterDevice,
    PrinterGroup,
    PrintJob,
    PrintRun,
    State,
    new_id,
)
from app.queue import require_idle
from app.request_models import PrintRequest
from app.schemas import Input

router = APIRouter(prefix="/api/printers")
DB = Annotated[Session, Depends(db, scope="function")]


def idle_locked(request: Request, session: Session, identifier: str) -> None:
    try:
        require_idle(session, identifier)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    results: list[Any] = list(
        session.scalars(
            select(CompanionBatch.result).where(CompanionBatch.printer_id == identifier)
        )
    )
    if any(result is None for result in results):
        raise HTTPException(
            409, "Reconcile outstanding companion batches before changing this printer"
        )
    link = session.get(CompanionPrinter, identifier)
    if link and link.blocked:
        raise HTTPException(409, "Investigate and clear the companion printer block first")
    worker = request.app.state.fleet.workers.get(identifier)
    if worker:
        if not worker.printer_lock.acquire(blocking=False):
            raise HTTPException(409, "Printer is busy; try again when it is idle")
        request.state.held_locks.append(worker.printer_lock)


def require_empty(session: Session, identifier: str) -> None:
    # Do not change another group's routing or silently strand work.
    if any(identifier in group.printer_ids for group in session.scalars(select(PrinterGroup))):
        raise HTTPException(409, "Remove this printer from its groups before retiring it")
    job_ids = (
        select(PrintJob.id)
        .outerjoin(PrintRun, PrintJob.run_id == PrintRun.id)
        .where(
            or_(PrintJob.destination_id == identifier, PrintRun.assigned_printer_id == identifier)
        )
    )
    if (
        session.scalar(
            select(LabelCopy.id)
            .where(
                LabelCopy.job_id.in_(job_ids),
                LabelCopy.state.in_([State.QUEUED, State.PRINTING, State.NEEDS_REVIEW]),
            )
            .limit(1)
        )
        or session.scalar(
            select(PrintRequest.id)
            .where(PrintRequest.destination_id == identifier, PrintRequest.status == "pending")
            .limit(1)
        )
        or session.scalar(
            select(PrintRun.id)
            .where(
                or_(
                    PrintRun.destination_id == identifier,
                    PrintRun.assigned_printer_id == identifier,
                ),
                PrintRun.submitted_at.is_(None),
            )
            .limit(1)
        )
        or session.scalar(
            select(FlushRequest.id)
            .where(FlushRequest.printer_id == identifier, FlushRequest.completed.is_(False))
            .limit(1)
        )
    ):
        raise HTTPException(
            409,
            "Finish, reroute or cancel queued work, pending requests, flushes and drafts before retiring this printer",
        )


def retire(request: Request, session: Session, device: PrinterDevice) -> None:
    state = printer_state(session, device.id)
    if state.active_cartridge_id:
        record_swap(session, device.id, state.active_cartridge_id, None, False)
    state.active_cartridge_id = None
    state.media_confirmation = None
    state.media_verified_fingerprint = None
    state.cartridge_check_pending = False
    state.automatic_printing_held = True
    device.config = {**device.config, "retired": True}
    link = session.get(CompanionPrinter, device.id)
    if link:
        link.enabled = False
        link.last_seen_at = None
    record_action(session, "printer.retired", "printer", device.id)
    request.state.after_commit.append(lambda: request.app.state.fleet.retire(device.id))


@router.delete("/{identifier}")
def retire_printer(identifier: str, request: Request, session: DB) -> dict[str, bool]:
    access_context(request).require_printer(identifier, "configure")
    device = get(session, PrinterDevice, identifier)
    idle_locked(request, session, identifier)
    require_empty(session, identifier)
    retire(request, session, device)
    return {"retired": True}


class MoveInput(Input):
    target_printer_id: str = Field(min_length=1, max_length=100)


@router.post("/{identifier}/move-to-companion")
def move_printer(identifier: str, body: MoveInput, request: Request, session: DB) -> dict[str, Any]:
    context = access_context(request)
    # A transport binding controls which machine receives rendered jobs. Only an
    # administrator may bind it, as with companion enrollment and user bindings.
    if not context.actor.is_admin:
        raise HTTPException(403, "Administrator access is required to move a printer")
    source = get(session, PrinterDevice, identifier)
    target = get(session, PrinterDevice, body.target_printer_id)
    if source.id == target.id or source.config.get("retired") or target.config.get("retired"):
        raise HTTPException(409, "Select two different active printer registrations")
    if session.get(CompanionPrinter, source.id):
        raise HTTPException(409, "Select a main-server printer to move to a companion")
    link = session.get(CompanionPrinter, target.id)
    companion = session.get(Companion, link.companion_id) if link else None
    if not link or not link.enabled or not companion or not companion.key_hash:
        raise HTTPException(409, "Select an enabled companion printer")
    fleet = request.app.state.fleet
    source_definition, _ = fleet.backend_factory(source.driver, source.config)
    target_definition, _ = fleet.backend_factory(target.driver, target.config)
    if (
        source.driver != target.driver
        or source_definition.capabilities != target_definition.capabilities
    ):
        raise HTTPException(
            409, "Printer driver and rendering capabilities must match before moving"
        )
    if session.scalar(
        select(FlushRequest.id)
        .where(FlushRequest.printer_id == source.id, FlushRequest.completed.is_(False))
        .limit(1)
    ):
        raise HTTPException(
            409, "Cancel the pending flush before moving this printer; its labels remain queued"
        )
    idle_locked(request, session, source.id)
    idle_locked(request, session, target.id)
    require_empty(session, target.id)
    if printer_state(session, target.id).active_cartridge_id:
        raise HTTPException(
            409, "Remove the cartridge from the duplicate companion registration first"
        )
    # Keep the retired link for historical event attribution. The physical local
    # slot now resolves to the original printer ID during registration.
    local_id = link.local_id
    link.local_id = f"retired:{target.id}"
    retire(request, session, target)
    target.config = {**target.config, "moved_to": source.id}
    session.flush()
    session.add(
        CompanionPrinter(
            printer_id=source.id,
            companion_id=companion.id,
            local_id=local_id,
            clearance=link.clearance,
        )
    )
    # Move the connection while preserving planning settings used by queued jobs.
    source.config = {**source.config, "usb_serial": target.config.get("usb_serial")}
    source.location_id = companion.location_id
    state = printer_state(session, source.id)
    state.automatic_printing_held = True
    state.media_confirmation = None
    state.media_verified_fingerprint = None
    state.cartridge_check_pending = bool(state.active_cartridge_id)
    append_audit(
        session,
        event_id=new_id(),
        action="printer.moved_to_companion",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("printer", source.id), AuditScope("printer", target.id)),
        fields={
            "actor_id": AuditField(context.actor.id, ()),
            "actor_name": AuditField(context.actor.username, ()),
            "retired_printer_id": AuditField(
                target.id, (AuditRequirement("printer", target.id, "printer.view_audit"),)
            ),
            "companion_id": AuditField(
                companion.id, (AuditRequirement("application", "", "audit.view_all"),)
            ),
            "location_id": AuditField(
                companion.location_id, (AuditRequirement("application", "", "audit.view_all"),)
            ),
        },
    )
    request.state.after_commit.append(lambda: fleet.reconfigure(source))
    session.flush()
    return {"printer_id": source.id, "retired_printer_id": target.id}
