"""Manual queue reservation, shared by physical and group destinations."""

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.destinations import members, printer_state, resolve_destination
from app.http import get, idle, record
from app.models import (
    Cartridge,
    FlushRequest,
    LabelCopy,
    PrinterDevice,
    PrinterGroup,
    PrinterState,
    PrintJob,
    PrintRun,
    TapeProfile,
)
from app.print_audit import actor_snapshot
from app.printer.base import LabelGeometry
from app.queue import compatible_copies
from app.schemas import CopySelectionInput


@dataclass(frozen=True)
class FlushSelection:
    printer_id: str
    destination_id: str
    state: PrinterState
    cartridge: Cartridge
    copies: tuple[LabelCopy, ...]


def select_flush(
    session: Session,
    printer_id: str | None = None,
    destination_id: str | None = None,
    body: CopySelectionInput | None = None,
) -> FlushSelection:
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
    return FlushSelection(printer_id, destination_id, state, cartridge, tuple(compatible))


def check_tape_shortage(session: Session, selections: list[FlushSelection]) -> None:
    """Warn before reserving any device; acknowledgment is bound to this exact plan."""
    request_context = session.info.get("request")
    if request_context is None:
        return
    from app.access import access_context

    plans: list[dict[str, Any]] = []
    shortages: list[dict[str, Any]] = []
    for selection in selections:
        labels = []
        for copy in selection.copies:
            job = get(session, PrintJob, copy.job_id)
            spec = job.template_snapshot.get("render_spec", {})
            labels.append(
                LabelGeometry(
                    copy.id,
                    job.width_mm,
                    job.length_mm,
                    spec.get("dpi_x") or spec.get("dpi", 180),
                    spec.get("dpi", 180),
                )
            )
        backend = request_context.app.state.registry.backend(selection.printer_id)
        estimate = backend.estimate_consumption(labels) if labels else 0.0
        if not math.isfinite(estimate) or estimate < 0:
            raise HTTPException(422, "Invalid printer tape consumption estimate")
        # The authorized group may route to members the user cannot access directly.
        device = session.get(PrinterDevice, selection.printer_id)
        if device is None:
            raise HTTPException(409, "Printer is unavailable")
        plan = {
            "printer_id": selection.printer_id,
            "printer_name": device.name,
            "cartridge_id": selection.cartridge.id,
            "cartridge_name": selection.cartridge.name,
            "copies": len(labels),
            "estimated_mm": estimate,
            "remaining_mm": selection.cartridge.remaining_mm,
        }
        plans.append(
            {
                **plan,
                "destination_id": selection.destination_id,
                "copy_ids": [label.copy_id for label in labels],
                "config": device.config,
                "consumption_uncertain": selection.cartridge.consumption_uncertain,
            }
        )
        if estimate > selection.cartridge.remaining_mm:
            shortages.append(plan)
    if not shortages:
        return
    fingerprint = json.dumps(
        {"actor": access_context(request_context).actor.id, "plans": plans},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    confirmation = hashlib.sha256(fingerprint.encode()).hexdigest()
    if request_context.headers.get("X-Tape-Shortage-Confirmation") == confirmation:
        return
    descriptions = [
        f"{item['printer_name']} ({item['cartridge_name']}): {item['copies']} copies need "
        f"an estimated {item['estimated_mm'] / 1000:.2f} m; "
        f"{item['remaining_mm'] / 1000:.2f} m remains."
        for item in shortages
    ]
    raise HTTPException(
        409,
        {
            "code": "tape_shortage",
            "message": "Estimated tape use exceeds the remaining tape.\n\n"
            + "\n".join(descriptions)
            + "\n\nEstimates include feed and cuts. Print anyway?",
            "shortages": shortages,
            "confirmation": confirmation,
        },
    )


def reserve_flush(
    session: Session,
    printer_id: str | None = None,
    destination_id: str | None = None,
    body: CopySelectionInput | None = None,
    *,
    hold_unselected: bool = True,
    shortage_checked: bool = False,
) -> dict[str, Any]:
    selection = select_flush(session, printer_id, destination_id, body)
    if not shortage_checked:
        check_tape_shortage(session, [selection])
    printer_id, destination_id = selection.printer_id, selection.destination_id
    compatible, state, cartridge = selection.copies, selection.state, selection.cartridge
    context = None
    if request_context := session.info.get("request"):
        from app.access import access_context

        context = access_context(request_context)
        hold_unselected = hold_unselected and context.can_destination(destination_id, "moderator")
    if body is not None and hold_unselected:
        # Keep all unselected work queued even if it meets an automatic threshold.
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
