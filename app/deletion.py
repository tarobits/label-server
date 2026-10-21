"""Administrator deletion, recoverable retention, and dependency availability."""

import time
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.asset_store import AssetStore
from app.models import (
    AccessChangeConfirmation,
    AuthSession,
    DeletedContent,
    LabelTemplate,
    RegistrationCode,
    TemplateRevision,
    User,
    UserGroup,
)

RETENTION_SECONDS = 30 * 24 * 3600


def is_deleted(session: Session, kind: str, identifier: str) -> bool:
    return session.get(DeletedContent, (kind, identifier)) is not None


def retain(
    session: Session,
    kind: str,
    identifier: str,
    name: str,
    owner_id: str,
    actor_id: str,
    *,
    account_id: str | None = None,
    details: dict[str, Any] | None = None,
    now: float | None = None,
) -> DeletedContent:
    existing = session.get(DeletedContent, (kind, identifier))
    if existing is not None:
        return existing  # Retrying deletion never extends the recovery window.
    stamp = time.time() if now is None else now
    item = DeletedContent(
        kind=kind,
        identifier=identifier,
        name=name,
        owner_id=owner_id,
        deleted_by=actor_id,
        deleted_at=stamp,
        purge_after=stamp + RETENTION_SECONDS,
        account_id=account_id,
        details=details or {},
    )
    session.add(item)
    session.flush()
    return item


def delete_account(
    session: Session, user: User, actor_id: str, fonts: AssetStore, images: AssetStore
) -> None:
    if is_deleted(session, "users", user.id):
        raise HTTPException(404, "Account has been deleted")
    memberships = []
    for group in session.scalars(select(UserGroup)):
        for member in group.members:
            if member["user_id"] == user.id:
                memberships.append({"group_id": group.id, "member": member})
        group.members = [member for member in group.members if member["user_id"] != user.id]
    item = retain(
        session,
        "users",
        user.id,
        user.username,
        user.id,
        actor_id,
        account_id=user.id,
        details={"disabled": user.disabled, "memberships": memberships},
    )
    user.disabled = True
    session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    session.execute(
        delete(AccessChangeConfirmation).where(AccessChangeConfirmation.actor_id == user.id)
    )
    for template in session.scalars(select(LabelTemplate).where(LabelTemplate.owner_id == user.id)):
        retain(
            session,
            "templates",
            template.id,
            template.name,
            user.id,
            actor_id,
            account_id=user.id,
            now=item.deleted_at,
        )
    for kind, store in (("fonts", fonts), ("images", images)):
        for asset in store.list(include_deleted=True):
            if asset["owner_id"] == user.id:
                retain(
                    session,
                    kind,
                    asset["id"],
                    asset.get("name", asset.get("family", kind)),
                    user.id,
                    actor_id,
                    account_id=user.id,
                    now=item.deleted_at,
                )
    session.flush()


def restorable(session: Session, kind: str, identifier: str) -> DeletedContent:
    item = session.get(DeletedContent, (kind, identifier))
    if item is None:
        raise HTTPException(404, "Deleted item not found")
    if item.purged_at is not None or item.purge_after <= time.time():
        raise HTTPException(409, "The 30-day restoration period has expired")
    return item


def restore_account(session: Session, identifier: str) -> User:
    item = restorable(session, "users", identifier)
    user = session.get(User, identifier)
    if user is None:
        raise HTTPException(409, "The account is no longer available")
    user.disabled = item.details["disabled"]
    for membership in item.details["memberships"]:
        group = session.get(UserGroup, membership["group_id"])
        if group and not any(member["user_id"] == user.id for member in group.members):
            group.members = [*group.members, membership["member"]]
    for related in session.scalars(
        select(DeletedContent).where(DeletedContent.account_id == identifier)
    ):
        session.delete(related)
    session.flush()
    return user


def restore_content(session: Session, kind: str, identifier: str) -> None:
    item = restorable(session, kind, identifier)
    if item.account_id and is_deleted(session, "users", item.account_id):
        raise HTTPException(409, "Restore the owning account to restore this content")
    session.delete(item)
    session.flush()


def purge_expired(session: Session, fonts: AssetStore, images: AssetStore, now: float) -> None:
    """Idempotent removal: files first, then mark completion in the transaction.

    Tombstones remain so old references never resolve to newly uploaded content.
    A crash during filesystem cleanup can safely retry at the next maintenance tick.
    """
    for item in session.scalars(
        select(DeletedContent)
        .where(DeletedContent.purge_after <= now, DeletedContent.purged_at.is_(None))
        .order_by(DeletedContent.kind)
    ):
        if item.kind in ("images", "fonts"):
            (images if item.kind == "images" else fonts).purge(item.identifier)
        elif item.kind == "templates":
            session.execute(
                delete(TemplateRevision).where(TemplateRevision.template_id == item.identifier)
            )
            session.execute(delete(LabelTemplate).where(LabelTemplate.id == item.identifier))
        elif item.kind == "users":
            session.execute(delete(AuthSession).where(AuthSession.user_id == item.identifier))
            session.execute(
                delete(AccessChangeConfirmation).where(
                    AccessChangeConfirmation.actor_id == item.identifier
                )
            )
            session.execute(
                update(RegistrationCode)
                .where(RegistrationCode.redeemed_by == item.identifier)
                .values(redeemed_by=None)
            )
            session.execute(delete(User).where(User.id == item.identifier))
        item.details = {}
        item.purged_at = now


def document_notices(session: Session, document: Any) -> list[dict[str, str]]:
    from app.asset_access import asset_references

    notices = []
    for reference, identifier in sorted(asset_references(document)):
        kind = "images" if reference == "image_asset" else "fonts"
        if is_deleted(session, kind, identifier):
            label = "Image" if kind == "images" else "Font"
            notices.append(
                {
                    "kind": kind,
                    "id": identifier,
                    "message": f"{label} deleted. Restore it or choose a replacement before printing.",
                }
            )
    return notices


def content_hold_reason(session: Session, job: Any) -> str | None:
    if is_deleted(session, "templates", job.template_id):
        return "The job's template has been deleted; restore it before printing"
    if document_notices(session, job.template_snapshot):
        return "A referenced image or font has been deleted; restore it before printing"
    return None
