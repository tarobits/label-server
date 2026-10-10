"""HTTP transaction boundary and shared record serialization."""

import time
from collections.abc import Iterator
from contextlib import nullcontext
from typing import Any, TypeVar

from fastapi import HTTPException, Request
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.destinations import resolve_destination
from app.models import Base, LabelCopy, PrintJob, PrintRun, State
from app.notifications import schedule_reminders
from app.queue import complete_empty_flushes, require_idle

T = TypeVar("T", bound=Base)


def db(request: Request) -> Iterator[Session]:
    # The single-process lock serializes API mutations with batch reservation.
    request.state.after_commit = []
    request.state.held_locks = []
    readonly = request.method in ("GET", "HEAD") or request.url.path in (
        "/api/preview",
        "/api/image-jobs/preview",
    )
    with nullcontext() if readonly else request.app.state.fleet.lock:
        try:
            with request.app.state.factory() as session:
                from app.access import authorize_current_request

                authorize_current_request(request)
                session.info["request"] = request
                yield session
                if not readonly:
                    complete_empty_flushes(session)
                    schedule_reminders(session, time.time())
                session.commit()
            for callback in request.state.after_commit:
                callback()
        finally:
            for lock in request.state.held_locks:
                lock.release()
    if not readonly:
        request.app.state.fleet.sync()
        request.app.state.wake.set()


def get(session: Session, model: type[T], identifier: str | int) -> T:
    value = session.get(model, identifier)
    if value is None:
        raise HTTPException(404, f"{model.__name__} not found")
    if request := session.info.get("request"):
        from app.authorization import require_record

        require_record(request, value)
    return value


def record(value: Base) -> dict[str, Any]:
    return {column.key: getattr(value, column.key) for column in inspect(type(value)).columns}


def idle(session: Session, printer_id: str | None = None) -> None:
    printer_id = resolve_destination(session, printer_id)
    try:
        require_idle(session, printer_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


def job_record(session: Session, job: PrintJob) -> dict[str, Any]:
    from app.print_audit import job_attribution

    copies = list(
        session.scalars(
            select(LabelCopy).where(LabelCopy.job_id == job.id).order_by(LabelCopy.ordinal)
        )
    )
    states = {item.state for item in copies}
    status = next(
        (
            state.value
            for state in [State.NEEDS_REVIEW, State.PRINTING, State.QUEUED]
            if state in states
        ),
        None,
    )
    if status is None:
        status = next(iter(states)).value if len(states) == 1 else "mixed"
    run = session.get(PrintRun, job.run_id) if job.run_id else None
    from app.job_access_models import JobAccessHold

    hold = session.get(JobAccessHold, job.id)
    held = hold is not None and hold.status == "held" and State.QUEUED in states
    permissions = {}
    if request := session.info.get("request"):
        from app.access import access_context

        context = access_context(request)
        owns = context.actor.id == job.owner_id
        moderates = context.can_destination(job.destination_id, "moderator")
        permissions = {
            "can_cancel": owns or moderates,
            "can_print": not held
            and (moderates or owns and context.can_destination(job.destination_id, "print")),
        }
    return {
        **record(job),
        "attribution": job_attribution(session, job),
        **permissions,
        "access_hold": record(hold) if hold is not None else None,
        "assigned_printer_id": run.assigned_printer_id if run else None,
        "status": status,
        "labels": [record(item) for item in copies],
    }
