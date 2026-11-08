"""Transactional audit evidence and permission-aware projections.

Action definitions are an explicit safe-field allowlist, not a serializer for
request bodies or ORM records. Add each producer with its action definition and
coverage; this module alone does not constitute application-wide audit coverage.
"""

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from sqlalchemy import Connection, event, select
from sqlalchemy.orm import Mapper, Session

from app.auth import PERMISSIONS
from app.models import AuditEvent
from app.resource_access import (
    GLOBAL_PERMISSIONS,
    GROUP_PERMISSIONS,
    OWNER_PERMISSIONS,
    ResourceAccess,
)

ScopeKind = Literal["printer", "cartridge", "global"]
FieldType = Literal["text", "integer", "number", "boolean", "identifiers", "permissions"]

# Each field is flat and typed: there are no arbitrary nested payloads or settings.
COMMON_FIELDS: dict[str, FieldType] = {
    "source": "text",
    "status_code": "integer",
    "actor_id": "text",
    "actor_name": "text",
    "victim_ids": "identifiers",
    "victim_names": "identifiers",
}
ACTION_FIELDS: dict[str, dict[str, FieldType]] = {
    **{
        action: {"configured": "boolean"}
        for action in (
            "auth.setup_completed",
            "auth.signed_in",
            "auth.registered",
            "auth.password_changed",
            "auth.signed_out",
            "auth.sessions_revoked",
            "auth.session_revoked",
            "auth.changelog_viewed",
            "auth.email_changed",
            "auth.email_verified",
            "auth.reset_requested",
            "auth.reset_link_issued",
            "auth.password_reset",
            "auth.subscription_changed",
        )
    },
    **{
        action: {
            "offer_id": "text",
            "job_id": "text",
            "currency": "text",
            "maximum_micros": "integer",
        }
        for action in ("price.acceptance_requested", "price.accepted", "price.declined")
    },
    "companion.printer_enabled_changed": {"enabled": "boolean"},
    "companion.local_stop_requested": {"mode": "text", "offline": "boolean", "locked": "boolean"},
    "companion.printer_registered": {"companion_id": "text", "name": "text"},
    "companion.printer_blocked": {},
    "companion.printer_cleared": {},
    "companion.batch_authorized": {"batch_id": "text"},
    "companion.result_received": {"batch_id": "text", "state": "text", "copy_count": "integer"},
    "account.pin_changed": {"configured": "boolean"},
    "companion.created": {"companion_id": "text", "name": "text"},
    "companion.settings_changed": {
        "companion_id": "text",
        "name": "text",
        "location_id": "text",
        "bound_user_id": "text",
        "principal_ids": "identifiers",
    },
    **{
        action: {"companion_id": "text"}
        for action in (
            "companion.key_rotated",
            "companion.revoked",
            "companion.unlocked",
            "companion.locked",
        )
    },
    **{
        action: {
            "batch_id": "text",
            "copy_count": "integer",
            "state": "text",
            "consumed_mm": "number",
            "initiator_id": "text",
        }
        for action in (
            "batch.reserved",
            "batch.started",
            "batch.completed",
            "batch.not_started",
            "batch.interrupted",
            "batch.reviewed",
        )
    },
    "cartridge.created": {
        "name": "text",
        "owner_id": "text",
        "profile_id": "text",
        "nominal_length_mm": "number",
        "remaining_mm": "number",
    },
    "cartridge.renamed": {"old_name": "text", "new_name": "text"},
    "cartridge.archived": {},
    "cartridge.restored": {},
    "cartridge.deleted": {"name": "text"},
    "cartridge.notes_changed": {},
    "cartridge.remaining_corrected": {"old_remaining_mm": "number", "new_remaining_mm": "number"},
    "cartridge.confirmed": {
        "old_cartridge_id": "text",
        "new_cartridge_id": "text",
        "confirmed": "boolean",
    },
    "printer.cartridge_check_changed": {"old_enabled": "boolean", "new_enabled": "boolean"},
    "printer.hold_changed": {"old_held": "boolean", "new_held": "boolean"},
    "printer_group.hold_changed": {
        "group_id": "text",
        "old_held": "boolean",
        "new_held": "boolean",
    },
    "printer.retired": {},
    "printer.moved_to_companion": {
        "retired_printer_id": "text",
        "companion_id": "text",
        "location_id": "text",
    },
    "printer.stop_requested": {"mode": "text", "batch_id": "text"},
    **{
        action: {
            "offer_id": "text",
            "batch_id": "text",
            "copy_ids": "identifiers",
            "funding": "text",
        }
        for action in ("retry.authorized", "retry.requested", "retry.accepted", "retry.declined")
    },
    "account.repayment_allocated": {
        "adjustment_id": "text",
        "recipient_id": "text",
        "allocated_micros": "integer",
        "currency": "text",
    },
    "cartridge.debt_assigned": {"batch_id": "text", "recipient_id": "text"},
    "cartridge.use_approved": {"copy_ids": "identifiers", "flush_id": "text"},
    "charge.settled": {
        "batch_id": "text",
        "actual_micros": "integer",
        "charged_micros": "integer",
        "currency": "text",
        "recipient_id": "text",
    },
    "inbox.viewed": {},
    "inbox.read_changed": {},
    "account.adjusted": {
        "adjustment_id": "text",
        "recipient_id": "text",
        "amount_minor": "integer",
        "currency": "text",
    },
    "migration.adjustment_assigned": {"adjustment_id": "text", "recipient_id": "text"},
    "migration.completed": {"version": "text", "resource_ids": "identifiers"},
    "resource.access_changed": {
        "resource_kind": "text",
        "resource_id": "text",
        "old_owner_id": "text",
        "new_owner_id": "text",
        "old_location_id": "text",
        "new_location_id": "text",
    },
    "access.changed": {"resource_kind": "text", "resource_id": "text", "method": "text"},
    "location.created": {"location_id": "text", "name": "text", "parent_id": "text"},
    "location.updated": {
        "location_id": "text",
        "old_name": "text",
        "new_name": "text",
        "old_parent_id": "text",
        "new_parent_id": "text",
    },
    "printer.ownership_changed": {"old_owner_id": "text", "new_owner_id": "text"},
    "location.ownership_changed": {"old_owner_id": "text", "new_owner_id": "text"},
    "cartridge.ownership_changed": {"old_owner_id": "text", "new_owner_id": "text"},
    "permission.changed": {
        "resource_kind": "text",
        "resource_id": "text",
        "old_denied_permissions": "permissions",
        "new_denied_permissions": "permissions",
        "principal_kind": "text",
        "principal_id": "text",
        "old_permissions": "permissions",
        "new_permissions": "permissions",
    },
    "cartridge.swapped": {
        "old_cartridge_id": "text",
        "new_cartridge_id": "text",
        "confirmed": "boolean",
    },
    "cartridge.price_changed": {
        "old_price_minor": "integer",
        "new_price_minor": "integer",
        "currency": "text",
        "old_currency": "text",
    },
    "audit.viewed": {},
}


@dataclass(frozen=True)
class AuditScope:
    kind: ScopeKind
    identifier: str = ""

    def encoded(self) -> dict[str, str]:
        if not isinstance(self.kind, str) or self.kind not in {"printer", "cartridge", "global"}:
            raise ValueError("Unknown audit scope")
        if (
            not isinstance(self.identifier, str)
            or (self.kind == "global") != (self.identifier == "")
            or len(self.identifier) > 100
        ):
            raise ValueError("Invalid audit scope identifier")
        return {"kind": self.kind, "id": self.identifier}


@dataclass(frozen=True)
class AuditRequirement:
    kind: str
    identifier: str
    permission: str

    def encoded(self) -> dict[str, str]:
        if not all(
            isinstance(value, str) for value in (self.kind, self.identifier, self.permission)
        ):
            raise ValueError("Invalid audit permission")
        allowed = {
            "printer": OWNER_PERMISSIONS["printer"],
            "cartridge": OWNER_PERMISSIONS["cartridge"],
            "printer_group": GROUP_PERMISSIONS,
            "application": frozenset(PERMISSIONS) | GLOBAL_PERMISSIONS,
            "account": frozenset({"account.self"}),
        }.get(self.kind, frozenset())
        if self.permission not in allowed:
            raise ValueError("Unknown audit field permission")
        if (self.kind == "application") != (self.identifier == "") or len(self.identifier) > 100:
            raise ValueError("Invalid audit permission scope")
        return {"kind": self.kind, "id": self.identifier, "permission": self.permission}


@dataclass(frozen=True)
class AuditField:
    value: str | int | float | bool | list[str] | None
    # Explicitly empty means shared event metadata, not an omitted classification.
    requirements: tuple[AuditRequirement, ...]


def _value_matches(value: object, kind: FieldType) -> bool:
    if value is None:
        return True
    if kind == "text":
        return isinstance(value, str) and len(value) <= 1000
    if kind == "integer":
        return type(value) is int and -(2**63) <= value < 2**63
    if kind == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and abs(value) <= 10**15
        )
    if kind == "boolean":
        return type(value) is bool
    if not isinstance(value, list) or len(value) > 1000:
        return False
    if not all(isinstance(item, str) and len(item) <= 100 for item in value):
        return False
    if kind == "permissions":
        known = (
            OWNER_PERMISSIONS["printer"]
            | OWNER_PERMISSIONS["cartridge"]
            | GLOBAL_PERMISSIONS
            | {"location.manage"}
            | set(PERMISSIONS)
        )
        return all(item in known for item in value)
    return kind == "identifiers"


def append_audit(
    session: Session,
    *,
    event_id: str,
    action: str,
    outcome: Literal["succeeded", "denied", "failed"],
    occurred_at: float,
    scopes: tuple[AuditScope, ...],
    fields: Mapping[str, AuditField],
) -> AuditEvent:
    """Append in the caller's transaction; identical replay is a no-op."""
    if not event_id or len(event_id) > 100 or action not in ACTION_FIELDS:
        raise ValueError("Unknown audit action or invalid event identity")
    if outcome not in {"succeeded", "denied", "failed"} or not math.isfinite(occurred_at):
        raise ValueError("Invalid audit outcome or time")
    if not scopes or len(scopes) > 1000:
        raise ValueError("An audit event needs bounded, explicit scopes")
    encoded_scopes = sorted(
        [scope.encoded() for scope in scopes], key=lambda value: (value["kind"], value["id"])
    )
    if len({(scope["kind"], scope["id"]) for scope in encoded_scopes}) != len(scopes):
        raise ValueError("Duplicate audit scope")
    definitions = COMMON_FIELDS | ACTION_FIELDS[action]
    encoded_fields: dict[str, Any] = {}
    for key, field in fields.items():
        if key not in definitions or not _value_matches(field.value, definitions[key]):
            raise ValueError("Unclassified or invalid audit field")
        if key not in COMMON_FIELDS and not field.requirements:
            raise ValueError("Audit change details need an explicit permission")
        if len(field.requirements) > 100:
            raise ValueError("Too many audit field requirements")
        encoded_fields[key] = {
            "value": field.value,
            "requires": [requirement.encoded() for requirement in field.requirements],
        }
    payload = {
        "action": action,
        "outcome": outcome,
        "occurred_at": occurred_at,
        "scopes": encoded_scopes,
        "fields": encoded_fields,
    }
    # Detach mutable input lists from the evidence that will be committed.
    payload = json.loads(json.dumps(payload, allow_nan=False))
    existing = session.get(AuditEvent, event_id)
    if existing is not None:
        if any(getattr(existing, key) != value for key, value in payload.items()):
            raise ValueError("Audit event identity already has different evidence")
        return existing
    result = AuditEvent(id=event_id, recorded_at=time.time(), **payload)
    session.add(result)
    session.flush()
    return result


@event.listens_for(AuditEvent, "before_update")
@event.listens_for(AuditEvent, "before_delete")
def _immutable_event(
    mapper: Mapper[AuditEvent], connection: Connection, target: AuditEvent
) -> None:
    raise ValueError("Audit evidence cannot be edited or deleted")


def _can_read_scope(access: ResourceAccess, scope: dict[str, str]) -> bool:
    try:
        value = AuditScope(scope["kind"], scope["id"]).encoded()  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError):
        return False
    return access.has("audit.view_all") or access.can(
        value["kind"], value["id"], f"{value['kind']}.view_audit"
    )


def _can_read_field(access: ResourceAccess, field: object) -> bool:
    if not isinstance(field, dict) or set(field) != {"value", "requires"}:
        return False
    requirements = field["requires"]
    if not isinstance(requirements, list) or len(requirements) > 100:
        return False
    for requirement in requirements:
        if not isinstance(requirement, dict) or set(requirement) != {"kind", "id", "permission"}:
            return False
        try:
            rule = AuditRequirement(
                requirement["kind"], requirement["id"], requirement["permission"]
            )
            rule.encoded()
        except (TypeError, ValueError):
            return False
        allowed = (
            access.is_admin or access.user_id == rule.identifier
            if rule.kind == "account"
            else access.has(rule.permission)
            if rule.kind == "application"
            else access.can(rule.kind, rule.identifier, rule.permission)
        )
        if not allowed:
            return False
    return True


def project_audit(event: AuditEvent, access: ResourceAccess) -> dict[str, Any] | None:
    """Fail closed on unclassified/invalid persisted fields, including for admins."""
    if (
        event.action not in ACTION_FIELDS
        or not isinstance(event.scopes, list)
        or not isinstance(event.fields, dict)
    ):
        return None
    scopes = [scope for scope in event.scopes if _can_read_scope(access, scope)]
    if not scopes:
        return None
    definitions = COMMON_FIELDS | ACTION_FIELDS[event.action]
    fields = {}
    for key, field in event.fields.items():
        if key not in definitions or not _can_read_field(access, field):
            continue
        if key not in COMMON_FIELDS and not field["requires"]:
            continue
        if _value_matches(field["value"], definitions[key]):
            fields[key] = field["value"]
    return {
        "id": event.id,
        "action": event.action,
        "outcome": event.outcome,
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "printers": [scope["id"] for scope in scopes if scope["kind"] == "printer"],
        "cartridges": [scope["id"] for scope in scopes if scope["kind"] == "cartridge"],
        "fields": fields,
        "restricted_details": len(fields) < len(event.fields),
    }


@dataclass(frozen=True)
class AuditFilters:
    printer: str | None = None
    cartridge: str | None = None
    action: str | None = None
    actor: str | None = None
    victim: str | None = None
    search: str | None = None

    def matches(self, projection: dict[str, Any]) -> bool:
        fields = projection["fields"]
        return not (
            self.printer is not None
            and self.printer not in projection["printers"]
            or self.cartridge is not None
            and self.cartridge not in projection["cartridges"]
            or self.action is not None
            and self.action != projection["action"]
            or self.actor is not None
            and self.actor != fields.get("actor_id")
            or self.victim is not None
            and self.victim not in (fields.get("victim_ids") or [])
            or self.search is not None
            and self.search.casefold() not in json.dumps(projection, ensure_ascii=False).casefold()
        )


def audit_page(
    session: Session,
    access: ResourceAccess,
    *,
    filters: AuditFilters = AuditFilters(),
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Filter authorized projections before totals/pagination, never hidden fields.

    Stream rows to bound memory. Later indexed query optimization must preserve
    these semantics, including not matching a hidden actor or cartridge.
    """
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("Invalid audit page")
    query = select(AuditEvent).order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
    total = 0
    items = []
    options: dict[str, dict[str, str]] = {
        key: {} for key in ("printer", "cartridge", "action", "actor", "victim")
    }
    for value in session.scalars(query.execution_options(yield_per=100)):
        projection = project_audit(value, access)
        if projection is None:
            continue
        fields = projection["fields"]
        options["action"][projection["action"]] = projection["action"]
        for kind in ("printer", "cartridge"):
            for identifier in projection[f"{kind}s"]:
                options[kind][identifier] = identifier
        if fields.get("actor_id"):
            options["actor"][fields["actor_id"]] = fields.get("actor_name") or fields["actor_id"]
        for index, identifier in enumerate(fields.get("victim_ids") or []):
            names = fields.get("victim_names") or []
            options["victim"][identifier] = (
                names[index] if len(names) == len(fields["victim_ids"]) else identifier
            )
        if not filters.matches(projection):
            continue
        if offset <= total < offset + limit:
            items.append(projection)
        total += 1
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "options": {
            key: [
                {"id": identifier, "name": name}
                for identifier, name in sorted(
                    values.items(), key=lambda item: (item[1].casefold(), item[0])
                )
            ]
            for key, values in options.items()
        },
    }
