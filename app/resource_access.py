"""Independent resource permissions for the staged 0.13 access migration.

This resolver deliberately does not turn granular grants back into legacy access
levels. Printer operations consume explicit permissions; cartridge enforcement
will be activated with the ownership migration workflow.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import actor_for_user
from app.models import (
    Cartridge,
    Companion,
    Location,
    PrinterDevice,
    PrinterGroup,
    ResourceGrant,
    Role,
    User,
)

if TYPE_CHECKING:
    from app.access import Actor

PRINTER_PERMISSIONS = frozenset(
    f"printer.{name}"
    for name in (
        "view",
        "submit_requests",
        "submit_directly",
        "start_own",
        "view_queue",
        "start_any",
        "manage_queue",
        "approve_requests",
        "view_activity",
        "view_audit",
        "review",
        "swap_cartridges",
        "hold_resume",
        "stop_after_label",
        "emergency_stop",
        "configure",
    )
)
CARTRIDGE_PERMISSIONS = frozenset(
    f"cartridge.{name}"
    for name in (
        "view",
        "use",
        "approve_use",
        "edit_notes",
        "edit_details",
        "manage_access",
        "view_audit",
    )
)
PHYSICAL_PERMISSIONS = frozenset(
    f"printer.{name}"
    for name in ("review", "swap_cartridges", "stop_after_label", "emergency_stop", "view_audit")
)
GROUP_PERMISSIONS = PRINTER_PERMISSIONS - PHYSICAL_PERMISSIONS
OWNER_PERMISSIONS = {
    "printer": PRINTER_PERMISSIONS | {"printer.manage_user_access", "printer.transfer_ownership"},
    "cartridge": CARTRIDGE_PERMISSIONS | {"cartridge.transfer_ownership"},
}
GLOBAL_PERMISSIONS = frozenset(
    {"locations.manage", "printers.edit_all", "cartridges.edit_all", "audit.view_all"}
)


def legacy_permissions(level: str, *, group: bool = False) -> frozenset[str]:
    """Expand old grants without granting newly introduced audit/owner rights.

    Moderator already holds/resumes automatic printing in the current route
    policy, despite older documentation placing that control under Full.
    """
    if level not in {"request", "print", "moderator", "full"}:
        return frozenset()
    result = {"printer.view", "printer.submit_requests"}
    if level in {"print", "moderator", "full"}:
        result.update({"printer.submit_directly", "printer.start_own"})
    if level in {"moderator", "full"}:
        result.update(
            f"printer.{name}"
            for name in (
                "view_queue",
                "start_any",
                "manage_queue",
                "approve_requests",
                "view_activity",
                "review",
                "hold_resume",
                "stop_after_label",
            )
        )
    if level == "full":
        result.update({"printer.configure", "printer.swap_cartridges", "printer.emergency_stop"})
    return frozenset(result) & (GROUP_PERMISSIONS if group else PRINTER_PERMISSIONS)


def location_ancestors(parents: Mapping[str, str | None], identifier: str) -> frozenset[str]:
    """Include the location itself; reject an invalid path rather than inheriting it."""
    seen: set[str] = set()
    current: str | None = identifier
    while current is not None:
        if current in seen:
            raise ValueError("Location hierarchy contains a cycle")
        if current not in parents:
            raise ValueError("Location does not exist")
        seen.add(current)
        current = parents[current]
    return frozenset(seen)


def validate_location_parent(session: Session, identifier: str, parent_id: str | None) -> None:
    parents = dict(session.execute(select(Location.id, Location.parent_id)).all())
    parents[identifier] = parent_id
    location_ancestors(parents, identifier)


def validate_grant(session: Session, grant: ResourceGrant) -> None:
    """Validate references and permission namespaces; callers must authorize writes."""
    if grant.principal_kind == "user":
        user = session.get(User, grant.principal_id)
        if user is None or user.disabled:
            raise ValueError("Grant recipient must be an enabled user")
    elif grant.principal_kind == "role":
        if session.get(Role, grant.principal_id) is None:
            raise ValueError("Grant role does not exist")
    else:
        raise ValueError("Unknown grant principal kind")
    allowed: frozenset[str]
    exists: bool
    if grant.scope_kind == "printer":
        device = session.get(PrinterDevice, grant.scope_id)
        exists = device is not None
        allowed = PRINTER_PERMISSIONS
        if device is not None and device.config.get("retired"):
            allowed = frozenset({"printer.view_audit"})
    elif grant.scope_kind == "printer_group":
        exists = session.get(PrinterGroup, grant.scope_id) is not None
        allowed = GROUP_PERMISSIONS
    elif grant.scope_kind == "cartridge":
        exists = session.get(Cartridge, grant.scope_id) is not None
        allowed = CARTRIDGE_PERMISSIONS
    elif grant.scope_kind == "location":
        exists = session.get(Location, grant.scope_id) is not None
        allowed = PRINTER_PERMISSIONS | CARTRIDGE_PERMISSIONS
    elif grant.scope_kind == "companion":
        exists = session.get(Companion, grant.scope_id) is not None
        allowed = frozenset({"companion.access"})
    else:
        raise ValueError("Unknown grant scope kind")
    if not exists:
        raise ValueError("Grant scope does not exist")
    if grant.permission not in allowed:
        raise ValueError("Permission does not apply to this scope")


@dataclass(frozen=True)
class ResourceAccess:
    user_id: str
    is_admin: bool
    application: frozenset[str]
    resources: Mapping[tuple[str, str], frozenset[str]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "application", frozenset(self.application))
        object.__setattr__(
            self,
            "resources",
            MappingProxyType({key: frozenset(value) for key, value in self.resources.items()}),
        )

    def has(self, permission: str) -> bool:
        return self.is_admin or permission in self.application

    def can(self, kind: str, identifier: str, permission: str) -> bool:
        if (
            kind in {"printer", "cartridge"}
            and permission == f"{kind}.view_audit"
            and self.has("audit.view_all")
        ):
            return True
        return permission in self.resources.get((kind, identifier), frozenset())


def resolve_resource_access(
    session: Session, user: User, *, actor: "Actor | None" = None
) -> ResourceAccess:
    """Resolve a fresh snapshot. Never reuse it after access-affecting mutations."""
    if user.disabled:
        return ResourceAccess(user.id, False, frozenset(), {})
    actor = actor or actor_for_user(session, user, include_resources=False)
    devices = list(session.scalars(select(PrinterDevice)))
    cartridges = list(session.scalars(select(Cartridge)))
    groups = list(session.scalars(select(PrinterGroup)))
    resources: dict[tuple[str, str], set[str]] = {}
    parents = dict(session.execute(select(Location.id, Location.parent_id)).all())
    ancestors: dict[str, frozenset[str]] = {}
    for identifier in parents:
        try:
            ancestors[identifier] = location_ancestors(parents, identifier)
        except ValueError:
            # Corrupt/imported hierarchies cannot become an access escalation.
            ancestors[identifier] = frozenset()
    roles = set(session.scalars(select(Role.id).where(Role.id.in_(actor.role_ids))))
    grants = list(
        session.scalars(
            select(ResourceGrant).where(
                or_(
                    (ResourceGrant.principal_kind == "user")
                    & (ResourceGrant.principal_id == user.id),
                    (ResourceGrant.principal_kind == "role")
                    & ResourceGrant.principal_id.in_(roles),
                )
            )
        )
    )
    for role in session.scalars(select(Role).where(Role.id.in_(roles))):
        for entry in role.permissions:
            if entry.get("kind") == "destination_permissions":
                scope_kind = (
                    "printer_group"
                    if any(group.id == entry["destination_id"] for group in groups)
                    else "printer"
                )
                grants.extend(
                    ResourceGrant(
                        principal_kind="role",
                        principal_id=role.id,
                        scope_kind=scope_kind,
                        scope_id=entry["destination_id"],
                        permission=permission,
                    )
                    for permission in entry["permissions"]
                )
    for kind, values in (("printer", devices), ("cartridge", cartridges)):
        allowed = PRINTER_PERMISSIONS if kind == "printer" else CARTRIDGE_PERMISSIONS
        for value in values:
            rights = (
                set(OWNER_PERMISSIONS[kind])
                if actor.is_admin or value.owner_id == user.id
                else set()
            )
            if kind == "printer":
                rights.update(legacy_permissions(actor.destination_levels.get(value.id, "none")))
            for grant in grants:
                if (
                    grant.scope_kind == kind
                    and grant.scope_id == value.id
                    or grant.scope_kind == "location"
                    and grant.scope_id in ancestors.get(value.location_id or "", frozenset())
                ) and grant.permission in allowed:
                    rights.add(grant.permission)
            if (
                kind == "printer"
                and actor.is_admin is False
                and "printers.edit_all" in actor.permissions
            ):
                rights.update({"printer.view", "printer.configure", "printer.transfer_ownership"})
            if (
                kind == "cartridge"
                and actor.is_admin is False
                and "cartridges.edit_all" in actor.permissions
            ):
                rights.update(
                    {"cartridge.view", "cartridge.edit_details", "cartridge.transfer_ownership"}
                )
            if isinstance(value, PrinterDevice) and value.config.get("retired"):
                rights.intersection_update({"printer.view_audit"})
            resources[(kind, value.id)] = rights
    for group in groups:
        rights = (
            set(GROUP_PERMISSIONS)
            if actor.is_admin
            else set(legacy_permissions(actor.destination_levels.get(group.id, "none"), group=True))
        )
        rights.update(
            grant.permission
            for grant in grants
            if grant.scope_kind == "printer_group"
            and grant.scope_id == group.id
            and grant.permission in GROUP_PERMISSIONS
        )
        resources[("printer_group", group.id)] = rights
    for companion in session.scalars(select(Companion)):
        resources[("companion", companion.id)] = (
            {"companion.access"}
            if actor.is_admin
            or any(
                grant.scope_kind == "companion"
                and grant.scope_id == companion.id
                and grant.permission == "companion.access"
                for grant in grants
            )
            else set()
        )
    return ResourceAccess(
        user.id,
        actor.is_admin,
        actor.permissions,
        {key: frozenset(value) for key, value in resources.items()},
    )
