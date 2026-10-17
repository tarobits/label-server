"""Printer registrations and explicit group destinations."""

import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.access import access_context
from app.authorization import visible_copy_count
from app.destinations import members, printer_state
from app.http import db, get, record
from app.models import (
    Batch,
    FlushRequest,
    LabelCopy,
    PrinterDevice,
    PrinterGroup,
    PrinterState,
    PrintJob,
    PrintRun,
    State,
    TapeProfile,
)
from app.print_audit import actor_snapshot
from app.printer.base import ControlledPrinterBackend
from app.printer_status import status_record
from app.request_models import PrintRequest
from app.reservations import check_tape_shortage, reserve_flush, select_flush
from app.schemas import (
    AutomaticPrintingInput,
    CopySelectionInput,
    PrinterGroupInput,
    PrinterInput,
    PrinterStopInput,
)

router = APIRouter(prefix="/api")


def validate_device(body: PrinterInput, session: Session, identifier: str | None = None) -> None:
    if body.driver != "brother-pt-p710bt":
        return
    body.usb_serial = body.usb_serial.strip() if body.usb_serial else None
    others = list(
        session.scalars(
            select(PrinterDevice).where(
                PrinterDevice.driver == body.driver,
                PrinterDevice.id != (identifier or ""),
            )
        )
    )
    if others and (not body.usb_serial or any(not d.config.get("usb_serial") for d in others)):
        raise HTTPException(
            422,
            "Set a USB serial number for each Brother printer in its configuration before adding another",
        )
    if body.usb_serial and any(d.config.get("usb_serial") == body.usb_serial for d in others):
        raise HTTPException(409, "This USB printer is already registered")


@router.post("/printers", status_code=201)
def register_printer(
    body: PrinterInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    try:
        request.app.state.fleet.backend_factory(body.driver, body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    validate_device(body, session)
    device = PrinterDevice(
        name=body.name, driver=body.driver, config=body.model_dump(exclude={"name", "driver"})
    )
    session.add(device)
    session.flush()
    session.add(PrinterState(printer_id=device.id))
    session.flush()
    return record(device)


@router.put("/printers/{identifier}")
def edit_printer(
    identifier: str,
    body: PrinterInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    from app.destinations import busy
    from app.models import FlushRequest

    device = get(session, PrinterDevice, identifier)
    try:
        definition, _ = request.app.state.fleet.backend_factory(body.driver, body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    validate_device(body, session, identifier)
    config = body.model_dump(exclude={"name", "driver"})
    changed = device.driver != body.driver or device.config != config
    if changed and identifier in request.app.state.fleet.workers:
        affected = [identifier] + [
            g.id for g in session.scalars(select(PrinterGroup)) if identifier in g.printer_ids
        ]
        if (
            busy(session, identifier)
            or session.scalar(
                select(PrintRequest.id)
                .where(PrintRequest.destination_id.in_(affected), PrintRequest.status == "pending")
                .limit(1)
            )
            or session.scalar(
                select(LabelCopy.id)
                .join(PrintJob)
                .where(
                    PrintJob.destination_id.in_(affected),
                    LabelCopy.state.in_([State.QUEUED, State.PRINTING, State.NEEDS_REVIEW]),
                )
                .limit(1)
            )
            or session.scalar(
                select(PrintRun.id)
                .where(
                    PrintRun.destination_id.in_(affected),
                    PrintRun.submitted_at.is_(None),
                )
                .limit(1)
            )
            or session.scalar(
                select(FlushRequest.id)
                .where(
                    FlushRequest.printer_id == identifier,
                    FlushRequest.completed.is_(False),
                )
                .limit(1)
            )
        ):
            raise HTTPException(
                409,
                "Finish queued work, pending flushes and drafts before changing printer configuration",
            )
        for group in session.scalars(select(PrinterGroup)):
            if identifier in group.printer_ids:
                for member in group.printer_ids:
                    if (
                        member != identifier
                        and definition.capabilities
                        != request.app.state.registry.definition(member).capabilities
                    ):
                        raise HTTPException(
                            409,
                            "Remove this printer from its groups before changing rendering capabilities",
                        )
    worker = request.app.state.fleet.workers.get(identifier)
    if worker:
        if not worker.printer_lock.acquire(blocking=False):
            raise HTTPException(409, "Printer is busy; try again when it is idle")
        request.state.held_locks.append(worker.printer_lock)
    device.name, device.driver, device.config = body.name, body.driver, config
    request.state.after_commit.append(lambda: request.app.state.fleet.reconfigure(device))
    session.flush()
    return record(device)


@router.get("/destinations")
def destinations(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    result = [
        {
            "id": p.id,
            "name": p.name,
            "kind": "printer",
            "printer_ids": [p.id],
            "automatic_printing_held": printer_state(session, p.id).automatic_printing_held,
        }
        for p in session.scalars(select(PrinterDevice))
        if p.id in request.app.state.fleet.workers and access_context(request).can_destination(p.id)
    ]
    result.extend(
        {**record(g), "kind": "group"}
        for g in session.scalars(select(PrinterGroup))
        if access_context(request).can_destination(g.id)
    )
    for destination in result:
        context = access_context(request)
        identifier = str(destination["id"])
        configured_members = [
            member
            for member in members(session, identifier)
            if member in request.app.state.fleet.workers
        ]
        destination["available"] = bool(configured_members)
        destination["member_names"] = {
            member: device.name
            for member in members(session, identifier)
            if (device := session.get(PrinterDevice, member)) is not None
        }
        destination["capabilities"] = (
            asdict(request.app.state.registry.definition(configured_members[0]).capabilities)
            if configured_members
            else None
        )
        destination["access_level"] = (
            "full"
            if context.actor.is_admin
            else context.actor.destination_levels.get(identifier, "none")
        )
        destination["queues"] = [
            {
                "profile_id": p.id,
                "queued_copies": visible_copy_count(request, session, str(destination["id"]), p),
                "threshold": p.auto_print_threshold,
            }
            for p in session.scalars(select(TapeProfile))
        ]
    return result


@router.get("/printers/status")
def all_status(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    return [
        status_record(request, session, device.id)
        for device in session.scalars(select(PrinterDevice))
        if not device.config.get("retired") and access_context(request).can_destination(device.id)
    ]


def validate_group(
    body: PrinterGroupInput,
    request: Request,
    session: Session,
    existing_members: list[str] | None = None,
) -> None:
    if len(set(body.printer_ids)) != len(body.printer_ids):
        raise HTTPException(422, "Select each printer once")
    capabilities = []
    for identifier in body.printer_ids:
        if identifier not in (existing_members or []):
            access_context(request).require_destination(identifier, "full")
        if session.get(PrinterDevice, identifier) is None:
            raise HTTPException(404, "Printer not found")
        if identifier not in request.app.state.fleet.workers:
            raise HTTPException(422, "Select a configured printer")
        capabilities.append(asdict(request.app.state.registry.definition(identifier).capabilities))
    if any(value != capabilities[0] for value in capabilities):
        raise HTTPException(
            422,
            "Group members must have matching media, printable geometry and resolution capabilities",
        )


@router.post("/printer-groups", status_code=201)
def create_group(
    body: PrinterGroupInput, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    validate_group(body, request, session)
    group = PrinterGroup(**body.model_dump())
    session.add(group)
    session.flush()
    return record(group)


@router.put("/printer-groups/{identifier}")
def edit_group(
    identifier: str,
    body: PrinterGroupInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    group = get(session, PrinterGroup, identifier)
    access_context(request).require_destination(identifier, "full")
    validate_group(body, request, session, group.printer_ids)
    if body.printer_ids != group.printer_ids:
        if session.scalar(
            select(PrintRequest.id)
            .where(PrintRequest.destination_id == identifier, PrintRequest.status == "pending")
            .limit(1)
        ):
            raise HTTPException(409, "Resolve pending print requests before changing group members")
        if session.scalar(
            select(PrintJob.id)
            .join(LabelCopy)
            .where(
                PrintJob.destination_id == identifier,
                LabelCopy.state.in_([State.QUEUED, State.PRINTING, State.NEEDS_REVIEW]),
            )
            .limit(1)
        ) or session.scalar(
            select(PrintRun.id)
            .where(PrintRun.destination_id == identifier, PrintRun.submitted_at.is_(None))
            .limit(1)
        ):
            raise HTTPException(
                409, "Finish queued work and saved drafts before changing group members"
            )
    group.name, group.printer_ids = body.name, body.printer_ids
    session.flush()
    return record(group)


@router.put("/destinations/{identifier}/automatic-printing")
def hold_destination(
    identifier: str, body: AutomaticPrintingInput, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    group = session.get(PrinterGroup, identifier)
    target = group or printer_state(session, identifier)
    target.automatic_printing_held = body.held
    session.flush()
    return record(target)


@router.post("/printers/{identifier}/stop", status_code=202)
def stop_printer(
    identifier: str,
    body: PrinterStopInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    context = access_context(request)
    context.require_destination(identifier, "full" if body.mode == "emergency" else "moderator")
    get(session, PrinterDevice, identifier)
    fleet = request.app.state.fleet
    worker = fleet.workers.get(identifier)
    if worker is None:
        raise HTTPException(409, "Printer is unavailable")
    caps = fleet.registry.definition(identifier).capabilities
    supported = (
        caps.supports_emergency_stop
        if body.mode == "emergency"
        else caps.supports_stop_after_current
    )
    if not supported or not isinstance(worker.backend, ControlledPrinterBackend):
        raise HTTPException(409, "This printer driver does not support the requested stop mode")
    state = printer_state(session, identifier)
    state.automatic_printing_held = True
    for pending in session.scalars(
        select(FlushRequest).where(
            FlushRequest.printer_id == identifier, FlushRequest.completed.is_(False)
        )
    ):
        pending.completed = True
    batch = session.scalar(
        select(Batch).where(Batch.printer_id == identifier, Batch.state == State.PRINTING)
    )
    mode = body.mode
    if batch is not None:
        previous = (batch.trigger or {}).get("stop_request")
        # A later graceful request cannot downgrade an emergency cancellation.
        if previous and previous["mode"] == "emergency":
            mode = "emergency"
        else:
            batch.trigger = {
                **(batch.trigger or {}),
                "stop_request": {
                    "mode": mode,
                    "actor": actor_snapshot(context.actor),
                    "at": time.time(),
                },
            }
        request.state.after_commit.append(lambda: worker.control.request(mode))
    session.flush()
    return {"printer_id": identifier, "batch_id": batch.id if batch else None, "mode": mode}


@router.post("/destinations/{identifier}/print", status_code=202)
def print_destination(
    identifier: str,
    request: Request,
    body: CopySelectionInput | None = None,
    session: Session = Depends(db, scope="function"),
) -> dict[str, Any]:
    members(session, identifier)
    context = access_context(request)
    context.require_destination(identifier, "print")
    moderates = context.can_destination(identifier, "moderator")
    if request.app.state.fleet.enforce_job_access:
        from app.job_access import reconcile_access_holds

        reconcile_access_holds(session)
    wanted = set(body.copy_ids) if body else None
    if body and wanted is not None and len(wanted) != len(body.copy_ids):
        raise HTTPException(422, "Select each copy once")
    copies = list(
        session.scalars(
            select(LabelCopy)
            .join(PrintJob)
            .where(
                PrintJob.destination_id == identifier,
                LabelCopy.state == State.QUEUED,
                true() if moderates else PrintJob.owner_id == context.actor.id,
            )
            .order_by(PrintJob.created_at, PrintJob.run_position, LabelCopy.ordinal)
        )
    )
    choices: dict[str, list[str]] = {}
    for copy in copies:
        if wanted is not None and copy.id not in wanted:
            continue
        job = get(session, PrintJob, copy.job_id)
        selected = request.app.state.fleet.choose(session, job, manual=True)
        if selected:
            choices.setdefault(selected, []).append(copy.id)
            if job.run_id:
                run = get(session, PrintRun, job.run_id)
                run.assigned_printer_id = selected
    selected_ids = {copy for group in choices.values() for copy in group}
    if wanted is not None and wanted != selected_ids:
        raise HTTPException(
            409,
            "Selection changed or no ready matching printer is available for every selected copy",
        )
    if not choices:
        raise HTTPException(409, "No queued labels have a ready matching printer")
    selections = [
        select_flush(session, printer_id, identifier, CopySelectionInput(copy_ids=ids))
        for printer_id, ids in choices.items()
    ]
    check_tape_shortage(session, selections)
    requests = [
        reserve_flush(
            session,
            printer_id,
            identifier,
            CopySelectionInput(copy_ids=ids),
            hold_unselected=body is not None and moderates,
            shortage_checked=True,
        )
        for printer_id, ids in choices.items()
    ]
    return {"requests": requests}
