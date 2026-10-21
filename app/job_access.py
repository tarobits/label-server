"""Pause queued work when its submitter loses the original authorization.

These checks concern application intent, not printer protocols. A recorded
administrator release applies to the frozen job even if its owner remains
disabled. Restoring ordinary permissions never silently clears a durable hold.
"""

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import LEVELS
from app.auth import actor_for_user
from app.deletion import content_hold_reason
from app.job_access_models import JobAccessHold
from app.models import FlushRequest, LabelCopy, PrinterDevice, PrinterGroup, PrintJob, State, User


def principal_access_reason(
    session: Session,
    user_id: str | None,
    destination_id: str,
    required: str,
    *,
    principal: str = "submitter",
) -> str | None:
    owner = session.get(User, user_id) if user_id else None
    if owner is None:
        return f"The {principal}'s account is unavailable"
    if owner.disabled:
        return f"The {principal}'s account is disabled"
    destination = session.get(PrinterDevice, destination_id) or session.get(
        PrinterGroup, destination_id
    )
    if destination is None or (
        isinstance(destination, PrinterDevice) and destination.config.get("retired")
    ):
        return "The original print destination is unavailable"
    actor = actor_for_user(session, owner)
    if actor.is_admin:
        return None
    current = actor.destination_levels.get(destination_id, "none")
    if LEVELS.get(current, 0) < LEVELS[required]:
        return f"The {principal} no longer has {required} access to this destination"
    return None


def access_hold_reason(session: Session, job: PrintJob) -> str | None:
    if reason := content_hold_reason(session, job):
        return reason
    if job.authorization_basis == "override":
        authorization = (job.attribution or {}).get("authorization", {})
        actor = authorization.get("actor") or {}
        return principal_access_reason(
            session, actor.get("id"), job.destination_id, "print", principal="authorizer"
        )
    required = "request" if job.authorization_basis == "request" else "print"
    return principal_access_reason(session, job.owner_id, job.destination_id, required)


def job_eligible(session: Session, job: PrintJob) -> bool:
    if content_hold_reason(session, job):
        return False
    hold = session.get(JobAccessHold, job.id)
    if hold is not None:
        return hold.status == "released"
    return access_hold_reason(session, job) is None


def reconcile_access_holds(session: Session, now: float | None = None) -> int:
    """Persist new holds inside the existing queue/admin transaction and lock."""
    stamp = time.time() if now is None else now
    jobs = session.scalars(
        select(PrintJob).join(LabelCopy).where(LabelCopy.state == State.QUEUED).distinct()
    )
    created = 0
    for job in jobs:
        existing = session.get(JobAccessHold, job.id)
        if existing is not None:
            reason = content_hold_reason(session, job)
            if existing.status == "cancelled" or (existing.status == "released" and reason):
                # Review can requeue uncertain copies after an earlier access-hold cancellation.
                existing.status = "held"
                existing.reason = reason or "Copies were requeued after an access-hold cancellation"
                existing.held_at = stamp
                existing.resolved_at = existing.resolved_by = None
                existing.resolved_by_snapshot = None
                created += 1
            continue
        reason = access_hold_reason(session, job)
        if reason:
            session.add(JobAccessHold(job_id=job.id, reason=reason, held_at=stamp))
            created += 1
    session.flush()
    for pending in session.scalars(select(FlushRequest).where(FlushRequest.completed.is_(False))):
        queued = list(
            session.scalars(
                select(PrintJob)
                .join(LabelCopy)
                .where(
                    LabelCopy.id.in_(pending.copy_ids),
                    LabelCopy.state == State.QUEUED,
                )
                .distinct()
            )
        )
        if queued and all(not job_eligible(session, job) for job in queued):
            # Release the revoked flush so it cannot block other work or resume after release.
            pending.completed = True
    session.flush()
    return created
