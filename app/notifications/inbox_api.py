"""Private inbox with read state independent of delivery attempts and endpoints."""

import time
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import Select, and_, delete, func, select
from sqlalchemy.orm import Session

from app.audit.audit import AuditField, AuditScope, append_audit
from app.authn.access import access_context
from app.http import db
from app.i18n import Message, notice_text, request_language
from app.models import Notification, NotificationRead, new_id
from app.schemas import Input
from app.transaction_routes import TransactionRouter

router = TransactionRouter(prefix="/api/inbox", tags=["notification inbox"])
DB = Annotated[Session, Depends(db, scope="function")]


class ReadInput(Input):
    read: bool = True


def visible(request: Request, session: Session) -> Select[Notification, float]:
    actor = access_context(request).actor
    recipients = [actor.id, "administrators"] if actor.is_admin else [actor.id]
    from app.accounts.billing_notifications import visible as billing_visible

    hidden = [
        notice.id
        for notice in session.scalars(
            select(Notification).where(Notification.recipient_id.in_(recipients))
        )
        if notice.context.get("billing_request_id") and not billing_visible(session, actor, notice)
    ]
    return (
        select(Notification, NotificationRead.read_at)
        .outerjoin(
            NotificationRead,
            and_(
                NotificationRead.notification_id == Notification.id,
                NotificationRead.user_id == actor.id,
            ),
        )
        .where(Notification.recipient_id.in_(recipients), Notification.id.not_in(hidden))
    )


@router.get("")
def inbox(
    request: Request,
    session: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = False,
) -> dict[str, Any]:
    query = visible(request, session)
    unread = (
        session.scalar(
            select(func.count()).select_from(
                query.where(NotificationRead.read_at.is_(None)).subquery()
            )
        )
        or 0
    )
    if unread_only:
        query = query.where(NotificationRead.read_at.is_(None))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    return {
        "total": total,
        "unread": unread,
        "items": [
            {
                "id": notice.id,
                "title": notice_text(notice, "title", request_language(request)),
                "message": notice_text(notice, "message", request_language(request)),
                "path": notice.path if notice.path.startswith("/#/") else "/#/",
                "kind": notice.kind,
                "created_at": notice.created_at,
                "read_at": read_at,
            }
            for notice, read_at in session.execute(
                query.order_by(Notification.created_at.desc(), Notification.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ],
    }


def audit_inbox(request: Request, session: Session, action: str) -> None:
    actor = access_context(request).actor
    append_audit(
        session,
        event_id=new_id(),
        action=action,
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("global"),),
        fields={"actor_id": AuditField(actor.id, ()), "actor_name": AuditField(actor.username, ())},
    )


@router.post("/opened", status_code=204)
def opened(request: Request, session: DB) -> None:
    audit_inbox(request, session, "inbox.viewed")


@router.put("/read", status_code=204)
def mark_all(body: ReadInput, request: Request, session: DB) -> None:
    actor = access_context(request).actor
    for notice, stamp in session.execute(visible(request, session)):
        if body.read and stamp is None:
            session.add(NotificationRead(notification_id=notice.id, user_id=actor.id))
        elif not body.read and stamp is not None:
            session.execute(
                delete(NotificationRead).where(
                    NotificationRead.notification_id == notice.id,
                    NotificationRead.user_id == actor.id,
                )
            )
    audit_inbox(request, session, "inbox.read_changed")


@router.put("/{identifier}/read", status_code=204)
def mark_one(identifier: str, body: ReadInput, request: Request, session: DB) -> None:
    actor = access_context(request).actor
    entry = session.execute(visible(request, session).where(Notification.id == identifier)).first()
    if entry is None:
        raise HTTPException(404, Message("serverMessages.notificationNotFound"))
    row = session.get(NotificationRead, (identifier, actor.id))
    if body.read and row is None:
        session.add(NotificationRead(notification_id=identifier, user_id=actor.id))
    elif not body.read and row is not None:
        session.delete(row)
    audit_inbox(request, session, "inbox.read_changed")
