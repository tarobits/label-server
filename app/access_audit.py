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


def record_role_rules(
    session: Session,
    actor: Actor,
    identifier: str,
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> None:
    from app.models import PrinterGroup
    from app.resource_access import legacy_permissions

    group_ids = set(session.scalars(select(PrinterGroup.id)))

    def grouped(
        entries: list[dict[str, Any]],
    ) -> dict[tuple[str, str], tuple[list[str], list[str]]]:
        result = {}
        for entry in entries:
            kind = entry["kind"]
            if kind == "application":
                continue
            scope = (
                "location"
                if kind == "location_permissions"
                else "printer_group"
                if entry["destination_id"] in group_ids
                else "printer"
            )
            key = entry.get("location_id") or entry["destination_id"]
            allowed = (
                list(legacy_permissions(entry["level"], group=scope == "printer_group"))
                if kind == "destination"
                else entry["permissions"]
            )
            result[(scope, key)] = (sorted(allowed), sorted(entry.get("denied_permissions", [])))
        return result

    old, new = grouped(before), grouped(after)
    for kind, scope_id in old.keys() | new.keys():
        previous, current = old.get((kind, scope_id), ([], [])), new.get((kind, scope_id), ([], []))
        if previous == current:
            continue
        guard = (
            (AuditRequirement("printer", scope_id, "printer.view_audit"),)
            if kind == "printer"
            else (AuditRequirement("application", "", "audit.view_all"),)
        )
        append_audit(
            session,
            event_id=new_id(),
            action="permission.changed",
            outcome="succeeded",
            occurred_at=time.time(),
            scopes=(AuditScope("printer", scope_id),)
            if kind == "printer"
            else (AuditScope("global"),),
            fields={
                "actor_id": AuditField(actor.id, ()),
                "actor_name": AuditField(actor.username, ()),
                "principal_kind": AuditField("role", guard),
                "principal_id": AuditField(identifier, guard),
                "resource_kind": AuditField(kind, guard),
                "resource_id": AuditField(scope_id, guard),
                "old_permissions": AuditField(previous[0], guard),
                "new_permissions": AuditField(current[0], guard),
                "old_denied_permissions": AuditField(previous[1], guard),
                "new_denied_permissions": AuditField(current[1], guard),
            },
        )
