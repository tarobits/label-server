"""Read-only per-printer status projection."""

from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import Action, Resource, access_context
from app.authorization import visible_copy_count, visible_jobs
from app.destinations import printer_state, resolve_destination
from app.http import get, record
from app.models import Batch, FlushRequest, LabelCopy, PrinterDevice, PrintJob, State, TapeProfile
from app.notification_routing import notifications_enabled
from app.printer.base import PrinterStatus


def status_record(
    request: Request, session: Session, printer_id: str | None = None
) -> dict[str, Any]:
    printer_id = resolve_destination(session, printer_id)
    context = access_context(request)
    context.require(Action.READ, Resource("destination", printer_id, destination_id=printer_id))
    manages = context.can_destination(printer_id, "moderator")
    state = printer_state(session, printer_id)
    device = get(session, PrinterDevice, printer_id)
    worker = request.app.state.fleet.workers.get(printer_id)
    hardware = (
        worker.latest_status
        if worker
        else PrinterStatus(
            False,
            None,
            request.app.state.fleet.configuration_errors.get(printer_id, "Printer unavailable"),
        )
    )
    active = session.scalar(
        select(Batch).where(Batch.printer_id == printer_id, Batch.state == State.PRINTING)
    )
    return {
        **record(state),
        "backend": device.driver,
        "printer_name": device.name,
        "printer_error": hardware.error,
        "renderer": "svg",
        "connected": hardware.connected,
        "detected_width_mm": hardware.tape_width_mm,
        "needs_review": list(
            session.scalars(
                select(Batch.id).where(
                    Batch.printer_id == printer_id, Batch.state == State.NEEDS_REVIEW
                )
            )
        )
        if manages
        else [],
        "notifications_enabled": notifications_enabled(session),
        "printing": active.id if active else None,
        "stop_requested": (active.trigger or {}).get("stop_request", {}).get("mode")
        if active
        else None,
        "pending_flush": session.scalar(
            select(FlushRequest.id)
            .where(
                FlushRequest.printer_id == printer_id,
                FlushRequest.completed.is_(False),
            )
            .limit(1)
        )
        if manages
        else None,
        "total_queued": session.scalar(
            visible_jobs(
                request, session, select(func.count()).select_from(LabelCopy).join(PrintJob)
            ).where(LabelCopy.state == State.QUEUED)
        ),
        "queues": [
            {
                "profile_id": p.id,
                "queued_copies": visible_copy_count(request, session, printer_id, p),
                "threshold": p.auto_print_threshold,
            }
            for p in session.scalars(select(TapeProfile))
        ],
    }
