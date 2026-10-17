"""Durable, bounded administrator summary windows; never change print state."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import active_administrators
from app.models import AuthSettings
from app.notifications import enqueue
from app.request_models import PrintRequest, RequestDigest


def schedule_request_digest(session: Session, now: float) -> None:
    digest = session.get(RequestDigest, 1)
    if digest is None or digest.due_at > now:
        return
    settings = session.get(AuthSettings, 1)
    has_admin = active_administrators(session)
    pending = (
        session.scalar(
            select(func.count()).select_from(PrintRequest).where(PrintRequest.status == "pending")
        )
        or 0
    )
    if settings and settings.approval_notifications_enabled and pending and has_admin:
        enqueue(
            session,
            "Print requests awaiting approval",
            f"{pending} print request(s) await administrator review.",
            "/#/requests",
            now=now,
            recipient_id="administrators",
            kind="approval_digest",
        )
    session.delete(digest)
