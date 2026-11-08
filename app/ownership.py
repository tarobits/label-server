"""Owner snapshots are independent of the identities that currently own inventory."""

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Cartridge, PrinterDevice, ResourceOwnership, User


def record_ownership(
    session: Session, kind: str, value: Cartridge | PrinterDevice, *, at: float | None = None
) -> None:
    current = session.scalar(
        select(ResourceOwnership).where(
            ResourceOwnership.kind == kind,
            ResourceOwnership.resource_id == value.id,
            ResourceOwnership.ended_at.is_(None),
        )
    )
    if current and current.owner_id == value.owner_id:
        return
    stamp = time.time() if at is None else at
    if current:
        current.ended_at = stamp
    if value.owner_id is None:
        session.flush()
        return
    owner = session.get(User, value.owner_id)
    session.add(
        ResourceOwnership(
            kind=kind,
            resource_id=value.id,
            owner_id=value.owner_id,
            owner_name=owner.username if owner else value.owner_id,
            effective_at=stamp,
        )
    )
    session.flush()


def owner_at(session: Session, cartridge: Cartridge, stamp: float) -> tuple[str | None, str | None]:
    history = session.scalar(
        select(ResourceOwnership)
        .where(
            ResourceOwnership.kind == "cartridge",
            ResourceOwnership.resource_id == cartridge.id,
            ResourceOwnership.effective_at <= stamp,
            (ResourceOwnership.ended_at.is_(None)) | (ResourceOwnership.ended_at > stamp),
        )
        .order_by(ResourceOwnership.effective_at.desc())
        .limit(1)
    )
    if history:
        return history.owner_id, history.owner_name
    # Inventory created without a transfer still has its first owner. Once history
    # exists, never substitute a later owner for an unknown historical owner.
    if session.scalar(
        select(ResourceOwnership.id)
        .where(ResourceOwnership.kind == "cartridge", ResourceOwnership.resource_id == cartridge.id)
        .limit(1)
    ):
        return None, None
    owner = session.get(User, cartridge.owner_id) if cartridge.owner_id else None
    return cartridge.owner_id, owner.username if owner else cartridge.owner_id
