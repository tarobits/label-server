"""Manual queue reservation, shared by physical and group destinations."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.destinations import members, printer_state, resolve_destination
from app.http import get, idle, record
from app.models import Cartridge, FlushRequest, PrinterGroup, PrintJob, PrintRun, TapeProfile
from app.print_audit import actor_snapshot
from app.queue import compatible_copies
from app.schemas import CopySelectionInput


def reserve_flush(
    session: Session,
    printer_id: str | None = None,
    destination_id: str | None = None,
    body: CopySelectionInput | None = None,
    *,
    hold_unselected: bool = True,
) -> dict[str, Any]:
    printer_id = resolve_destination(session, printer_id)
    idle(session, printer_id)
    destination_id = destination_id or printer_id
    context = None
    if request_context := session.info.get("request"):
        from app.access import access_context
        from app.job_access import reconcile_access_holds

        context = access_context(request_context)
        context.require_destination(destination_id, "print")
        if request_context.app.state.fleet.enforce_job_access:
            reconcile_access_holds(session)
        hold_unselected = hold_unselected and context.can_destination(destination_id, "moderator")
    if printer_id not in members(session, destination_id):
        raise HTTPException(422, "Printer is not a member of the destination")
    state = printer_state(session, printer_id)
    if not state.active_cartridge_id:
        raise HTTPException(409, "Select an installed cartridge first")
    cartridge = get(session, Cartridge, state.active_cartridge_id)
    profile = get(session, TapeProfile, cartridge.profile_id)
    pending = session.scalar(
        select(FlushRequest.id)
        .where(FlushRequest.cartridge_id == cartridge.id, FlushRequest.completed.is_(False))
        .limit(1)
    )
    if pending:
        raise HTTPException(409, "A manual flush is already pending for this cartridge")
    compatible = compatible_copies(session, profile, destination_id)
    reserved = {
        identifier
        for flush in session.scalars(select(FlushRequest).where(FlushRequest.completed.is_(False)))
        for identifier in flush.copy_ids
    }
    eligible = []
    for label in compatible:
        if context and not context.can_destination(destination_id, "moderator"):
            candidate = session.get(PrintJob, label.job_id)
            if candidate is None or candidate.owner_id != context.actor.id:
                continue
        job = get(session, PrintJob, label.job_id)
        if request_context and request_context.app.state.fleet.enforce_job_access:
            from app.job_access import job_eligible

            if not job_eligible(session, job):
                continue
        run = session.get(PrintRun, job.run_id) if job.run_id else None
        if label.id not in reserved and (not run or run.assigned_printer_id in (None, printer_id)):
            eligible.append(label)
    compatible = eligible
    if body is not None:
        wanted = set(body.copy_ids)
        if len(wanted) != len(body.copy_ids):
            raise HTTPException(422, "Select each copy only once")
        if not wanted.issubset({copy.id for copy in compatible}):
            raise HTTPException(
                409,
                "Selection changed or includes copies incompatible with the installed tape; refresh the queue",
            )
        compatible = [copy for copy in compatible if copy.id in wanted]
        # Keep all unselected work queued even if it meets an automatic threshold.
        if hold_unselected:
            group = session.get(PrinterGroup, destination_id)
            if group:
                group.automatic_printing_held = True
            else:
                state.automatic_printing_held = True
    for label in compatible:
        job = get(session, PrintJob, label.job_id)
        if job.run_id:
            get(session, PrintRun, job.run_id).assigned_printer_id = printer_id
    request = FlushRequest(
        started_by=actor_snapshot(context.actor) if context else None,
        printer_id=printer_id,
        destination_id=destination_id,
        cartridge_id=cartridge.id,
        copy_ids=[c.id for c in compatible],
    )
    session.add(request)
    session.flush()
    return record(request)
