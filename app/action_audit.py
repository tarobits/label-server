"""Small helpers for explicit, classified action producers."""

import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access import access_context
from app.audit import AuditField, AuditRequirement, AuditScope, ScopeKind, append_audit
from app.models import Batch, BatchItem, new_id


def record_action(
    session: Session,
    action: str,
    kind: ScopeKind,
    identifier: str,
    details: dict[str, Any] | None = None,
    *,
    permission: str | None = None,
) -> None:
    request = session.info.get("request")
    actor = access_context(request).actor if request else session.info.get("companion_operator")
    companion = session.info.get("companion")
    guard = (
        AuditRequirement(
            "application" if kind == "global" else kind,
            identifier,
            permission or ("audit.view_all" if kind == "global" else f"{kind}.view"),
        ),
    )
    append_audit(
        session,
        event_id=new_id(),
        action=action,
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope(kind, identifier),),
        fields={
            "actor_id": AuditField(actor.id if actor else None, ()),
            "actor_name": AuditField(actor.username if actor else None, ()),
            "source": AuditField("user" if actor else "companion" if companion else "system", ()),
            **{key: AuditField(value, guard) for key, value in (details or {}).items()},
        },
    )


def record_swap(
    session: Session, printer_id: str, previous: str | None, current: str | None, confirmed: bool
) -> None:
    request = session.info["request"]
    actor = access_context(request).actor
    cartridges = set(value for value in (previous, current) if value)
    scopes = (AuditScope("printer", printer_id),) + tuple(
        AuditScope("cartridge", value) for value in sorted(cartridges)
    )
    printer_guard = (AuditRequirement("printer", printer_id, "printer.view"),)
    fields = {
        "actor_id": AuditField(actor.id, ()),
        "actor_name": AuditField(actor.username, ()),
        "confirmed": AuditField(confirmed, printer_guard),
    }
    for key, value in (("old_cartridge_id", previous), ("new_cartridge_id", current)):
        guard = (
            (AuditRequirement("cartridge", value, "cartridge.view"),) if value else printer_guard
        )
        fields[key] = AuditField(value, guard)
    append_audit(
        session,
        event_id=new_id(),
        action="cartridge.swapped" if previous != current else "cartridge.confirmed",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=scopes,
        fields=fields,
    )


def record_batch_event(
    session: Session, batch: Batch, action: str, *, failed: bool = False
) -> None:
    request = session.info.get("request")
    actor = access_context(request).actor if request else None
    guard = (AuditRequirement("printer", batch.printer_id, "printer.view_activity"),)
    count = (
        session.scalar(
            select(func.count()).select_from(BatchItem).where(BatchItem.batch_id == batch.id)
        )
        or 0
    )
    append_audit(
        session,
        event_id=new_id(),
        action=action,
        outcome="failed" if failed else "succeeded",
        occurred_at=time.time(),
        scopes=(
            AuditScope("printer", batch.printer_id),
            AuditScope("cartridge", batch.cartridge_id),
        ),
        fields={
            "actor_id": AuditField(actor.id if actor else None, ()),
            "actor_name": AuditField(actor.username if actor else None, ()),
            "source": AuditField("user" if actor else "system", ()),
            "batch_id": AuditField(batch.id, guard),
            "copy_count": AuditField(count, guard),
            "state": AuditField(batch.state.value, guard),
            "consumed_mm": AuditField(batch.consumed_mm, guard),
            "initiator_id": AuditField(((batch.trigger or {}).get("actor") or {}).get("id"), guard),
        },
    )
