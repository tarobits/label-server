"""Quantity changes must never rewrite attempted or reserved physical work."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BatchItem, FlushRequest, LabelCopy, PrintJob, State
from app.printing.job_access import job_eligible


def copy_count_blocker(session: Session, job: PrintJob, enforce_access: bool) -> str | None:
    labels = list(session.scalars(select(LabelCopy).where(LabelCopy.job_id == job.id)))
    if not labels or any(label.state != State.QUEUED for label in labels):
        return "Copies can only be changed while the entire item is queued"
    identifiers = {label.id for label in labels}
    if session.scalar(select(BatchItem.copy_id).where(BatchItem.copy_id.in_(identifiers)).limit(1)):
        return "This item has already been attempted; use Activity to print another copy"
    if any(
        identifiers.intersection(reservation.copy_ids)
        for reservation in session.scalars(
            select(FlushRequest).where(FlushRequest.completed.is_(False))
        )
    ):
        return "Cancel the pending print reservation before changing copies"
    if enforce_access and not job_eligible(session, job):
        return "Resolve this item's access or content hold before changing copies"
    return None
