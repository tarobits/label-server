"""Audit confirmed access changes without copying role payloads or credentials."""

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import Actor
from app.audit import AuditField, AuditRequirement, AuditScope, ScopeKind, append_audit
from app.models import Cartridge, PrinterDevice, new_id


def record_access_change(
    session: Session,
    actor: Actor,
    resource: str,
    method: str,
    identifier: str | None,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> None:
    now = time.time()
    attribution = {
        "actor_id": AuditField(actor.id, ()),
        "actor_name": AuditField(actor.username, ()),
    }
    global_rule = (AuditRequirement("application", "", "audit.view_all"),)
    append_audit(
        session,
        event_id=new_id(),
        action="access.changed",
        outcome="succeeded",
        occurred_at=now,
        scopes=(AuditScope("global"),),
        fields={
            **attribution,
            "resource_kind": AuditField(resource, global_rule),
            "resource_id": AuditField(identifier, global_rule),
            "method": AuditField(method, global_rule),
        },
    )
    identifiers = {
        "printer": set(session.scalars(select(PrinterDevice.id))),
        "cartridge": set(session.scalars(select(Cartridge.id))),
    }
    resource_fields: tuple[tuple[ScopeKind, str], ...] = (
        ("printer", "destination_permissions"),
        ("cartridge", "cartridge_permissions"),
    )
    for user_id in before.keys() | after.keys():
        for kind, field in resource_fields:
            old = before.get(user_id, {}).get(field, {})
            new = after.get(user_id, {}).get(field, {})
            for resource_id in (old.keys() | new.keys()) & identifiers[kind]:
                previous, current = (
                    sorted(old.get(resource_id, [])),
                    sorted(new.get(resource_id, [])),
                )
                if previous == current:
                    continue
                scope = AuditScope(kind, resource_id)
                rule = (AuditRequirement(kind, resource_id, f"{kind}.view_audit"),)
                append_audit(
                    session,
                    event_id=new_id(),
                    action="permission.changed",
                    outcome="succeeded",
                    occurred_at=now,
                    scopes=(scope,),
                    fields={
                        **attribution,
                        "victim_ids": AuditField([user_id], rule),
                        "victim_names": AuditField(
                            [(after.get(user_id) or before[user_id])["username"]], rule
                        ),
                        "principal_kind": AuditField("user", rule),
                        "principal_id": AuditField(user_id, rule),
                        "old_permissions": AuditField(previous, rule),
                        "new_permissions": AuditField(current, rule),
                    },
                )
