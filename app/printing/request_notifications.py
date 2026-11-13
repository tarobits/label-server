"""Durable, bounded administrator summary windows; never change print state."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.authn.auth import active_administrators
from app.i18n import Message
from app.models import AuthSettings
from app.notifications.notifications import enqueue
from app.printing.request_models import PrintRequest, RequestDigest


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
            Message("notificationMessages.approvalTitle"),
            Message("notificationMessages.approvalBody", count=pending),
            "/#/requests",
            now=now,
            recipient_id="administrators",
            kind="approval_digest",
        )
    session.delete(digest)
