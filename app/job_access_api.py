"""Administrator decisions for access-related holds on frozen queued jobs."""

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import access_context
from app.http import db, job_record, record
from app.job_access_models import JobAccessHold
from app.models import LabelCopy, PrintJob, State, User
from app.print_audit import actor_snapshot

router = APIRouter(prefix="/api/access-holds")


def administrator(request: Request) -> str:
    actor = access_context(request).actor
    if not actor.is_admin:
        raise HTTPException(403, "Administrator access is required")
    return actor.id


def hold_record(session: Session, hold: JobAccessHold) -> dict[str, Any]:
    job = session.get(PrintJob, hold.job_id)
    assert job is not None
    owner = session.get(User, job.owner_id)
    return {
        **record(hold),
        "owner_name": owner.username if owner else job.owner_id,
        "job": job_record(session, job),
    }


@router.get("")
def list_holds(
    request: Request, session: Session = Depends(db, scope="function")
) -> list[dict[str, Any]]:
    administrator(request)
    return [
        hold_record(session, hold)
        for hold in session.scalars(
            select(JobAccessHold)
            .where(
                JobAccessHold.status == "held",
                select(LabelCopy.id)
                .where(LabelCopy.job_id == JobAccessHold.job_id, LabelCopy.state == State.QUEUED)
                .exists(),
            )
            .order_by(JobAccessHold.held_at, JobAccessHold.job_id)
        )
    ]


def resolve_hold(
    request: Request, session: Session, identifier: str, decision: str
) -> dict[str, Any]:
    reviewer = administrator(request)
    hold = session.get(JobAccessHold, identifier)
    if hold is None:
        raise HTTPException(404, "Access hold not found")
    if hold.status == decision:
        return hold_record(session, hold)
    if hold.status != "held":
        raise HTTPException(409, "This hold has already been resolved")
    copies = list(
        session.scalars(
            select(LabelCopy).where(LabelCopy.job_id == identifier, LabelCopy.state == State.QUEUED)
        )
    )
    if not copies:
        raise HTTPException(409, "This job no longer has queued copies")
    if decision == "cancelled":
        for label in copies:
            label.state = State.CANCELLED
    hold.status, hold.resolved_at, hold.resolved_by = decision, time.time(), reviewer
    hold.resolved_by_snapshot = actor_snapshot(access_context(request).actor)
    session.flush()
    return hold_record(session, hold)


@router.post("/{identifier}/release")
def release_hold(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return resolve_hold(request, session, identifier, "released")


@router.post("/{identifier}/cancel")
def cancel_hold(
    identifier: str, request: Request, session: Session = Depends(db, scope="function")
) -> dict[str, Any]:
    return resolve_hold(request, session, identifier, "cancelled")
