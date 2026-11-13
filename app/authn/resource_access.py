"""Resolve scoped resource permissions and their inheritance evidence."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.authn.auth import actor_for_user
from app.authn.permission_rules import PermissionDecision, PermissionRule, decide
from app.i18n import Message
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
    from app.authn.access import Actor

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
            raise ValueError(Message("authValidation.locationHierarchyContainsACycle"))
        if current not in parents:
            raise ValueError(Message("authValidation.locationDoesNotExist"))
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
            raise ValueError(Message("authValidation.grantRecipientMustBeAnEnabledUser"))
    elif grant.principal_kind == "role":
        if session.get(Role, grant.principal_id) is None:
            raise ValueError(Message("authValidation.grantRoleDoesNotExist"))
    else:
        raise ValueError(Message("authValidation.unknownGrantPrincipalKind"))
    if grant.effect not in (None, "allow", "deny"):
        raise ValueError(Message("authValidation.unknownPermissionEffect"))
    allowed: frozenset[str]
    exists: bool
    if grant.scope_kind == "printer":
        device = session.get(PrinterDevice, grant.scope_id)
        exists = device is not None
        allowed = PRINTER_PERMISSIONS
        if device is not None and device.config.get("retired"):
            allowed = frozenset({"printer.view_audit", "printer.view_activity"})
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
        if grant.effect == "deny":
            raise ValueError(Message("authValidation.companionAccessUsesAllowGrantsOnly"))
        exists = session.get(Companion, grant.scope_id) is not None
        allowed = frozenset({"companion.access"})
    else:
        raise ValueError(Message("authValidation.unknownGrantScopeKind"))
    if not exists:
        raise ValueError(Message("authValidation.grantScopeDoesNotExist"))
    if grant.permission not in allowed:
        raise ValueError(Message("authValidation.permissionDoesNotApplyToThisScope"))


@dataclass(frozen=True)
class ResourceAccess:
    user_id: str
    is_admin: bool
    application: frozenset[str]
    resources: Mapping[tuple[str, str], frozenset[str]]
    decisions: Mapping[tuple[str, str], Mapping[str, PermissionDecision]] = field(
        default_factory=dict
    )

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
    locations = list(session.scalars(select(Location)))
    parents = {location.id: location.parent_id for location in locations}
    location_names = {location.id: location.name for location in locations}
    paths: dict[str, list[str]] = {}
    for identifier in parents:
        try:
            location_ancestors(parents, identifier)
            path: list[str] = []
            current: str | None = identifier
            while current is not None:
                path.insert(0, current)
                current = parents[current]
            paths[identifier] = path
        except ValueError:
            paths[identifier] = []
    roles = list(session.scalars(select(Role).where(Role.id.in_(actor.role_ids))))
    role_names = {role.id: role.name for role in roles}
    grants = list(
        session.scalars(
            select(ResourceGrant).where(
                or_(
                    (ResourceGrant.principal_kind == "user")
                    & (ResourceGrant.principal_id == user.id),
                    (ResourceGrant.principal_kind == "role")
                    & ResourceGrant.principal_id.in_(role_names),
                )
            )
        )
    )
    group_ids = {group.id for group in groups}
    for role in roles:
        for entry in role.permissions:
            if entry.get("kind") not in {"destination", "destination_permissions"}:
                continue
            identifier = entry["destination_id"]
            scope_kind = "printer_group" if identifier in group_ids else "printer"
            permissions = (
                legacy_permissions(entry["level"], group=identifier in group_ids)
                if entry["kind"] == "destination"
                else entry["permissions"]
            )
            for effect, values in (
                ("allow", permissions),
                ("deny", entry.get("denied_permissions", [])),
            ):
                grants.extend(
                    ResourceGrant(
                        principal_kind="role",
                        principal_id=role.id,
                        scope_kind=scope_kind,
                        scope_id=identifier,
                        permission=permission,
                        effect=effect,
                    )
                    for permission in values
                )
    resources: dict[tuple[str, str], frozenset[str]] = {}
    decisions: dict[tuple[str, str], Mapping[str, PermissionDecision]] = {}
    collections = (
        ("printer", devices),
        ("cartridge", cartridges),
        ("printer_group", groups),
        ("companion", list(session.scalars(select(Companion)))),
        ("location", locations),
    )
    for kind, values in collections:
        for value in values:
            allowed = (
                OWNER_PERMISSIONS[kind]
                if kind in OWNER_PERMISSIONS
                else GROUP_PERMISSIONS
                if kind == "printer_group"
                else frozenset({"companion.access"})
                if kind == "companion"
                else frozenset({"location.manage"})
            )
            path = (
                paths.get(getattr(value, "location_id", None) or "", [])
                if kind in {"printer", "cartridge"}
                else []
            )
            rules: list[PermissionRule] = []
            for grant in grants:
                if grant.permission not in allowed:
                    continue
                if grant.scope_kind == kind and grant.scope_id == value.id:
                    specificity = len(path) + 1
                    scope_name = value.name
                elif (
                    kind in {"printer", "cartridge"}
                    and grant.scope_kind == "location"
                    and grant.scope_id in path
                ):
                    specificity = path.index(grant.scope_id)
                    scope_name = location_names[grant.scope_id]
                else:
                    continue
                rules.append(
                    PermissionRule(
                        grant.permission,
                        grant.effect or "allow",
                        grant.scope_kind,
                        grant.scope_id,
                        scope_name,
                        grant.principal_kind,
                        grant.principal_id,
                        user.username
                        if grant.principal_kind == "user"
                        else role_names[grant.principal_id],
                        (specificity, 1 if grant.principal_kind == "user" else 0),
                        inherited_via=tuple(
                            location_names[ancestor]
                            for ancestor in path[path.index(grant.scope_id) + 1 :]
                        )
                        if grant.scope_kind == "location"
                        else (),
                    )
                )
            special: set[str] = set()
            if kind == "printer" and "printers.edit_all" in actor.permissions:
                special.update({"printer.view", "printer.configure", "printer.transfer_ownership"})
            if kind == "cartridge" and "cartridges.edit_all" in actor.permissions:
                special.update(
                    {"cartridge.view", "cartridge.edit_details", "cartridge.transfer_ownership"}
                )
            if kind == "location" and "locations.manage" in actor.permissions:
                special.add("location.manage")
            application_rules = [
                (
                    permission,
                    "locations.manage" if kind == "location" else f"{kind}s.edit_all",
                    False,
                )
                for permission in special
            ]
            if kind in {"printer", "cartridge"} and "audit.view_all" in actor.permissions:
                application_rules.append((f"{kind}.view_audit", "audit.view_all", True))
            for permission, application, protected in (
                application_rules if not actor.is_admin else []
            ):
                origins = [
                    ("role", role.id, role.name)
                    for role in roles
                    if any(
                        entry.get("kind") == "application"
                        and entry.get("permission") == application
                        for entry in role.permissions
                    )
                ] or [("user", user.id, user.username)]
                for principal_kind, principal_id, principal_name in origins:
                    rules.append(
                        PermissionRule(
                            permission,
                            "allow",
                            "application",
                            application,
                            {
                                "printers.edit_all": "Edit all printers",
                                "cartridges.edit_all": "Edit all cartridges",
                                "locations.manage": "Manage locations",
                                "audit.view_all": "View all audit logs",
                            }[application],
                            principal_kind,
                            principal_id,
                            principal_name,
                            (1000000, 0) if protected else (-1, 0),
                            protected,
                        )
                    )
            owner = getattr(value, "owner_id", None) == user.id
            if actor.is_admin or owner:
                rules.extend(
                    PermissionRule(
                        permission,
                        "allow",
                        kind,
                        value.id,
                        "Administrator" if actor.is_admin else "Owner",
                        "user",
                        user.id,
                        user.username,
                        (1000000, 1),
                        True,
                    )
                    for permission in allowed
                )
            resolved = decide(rules, allowed)
            if isinstance(value, PrinterDevice) and value.config.get("retired"):
                resolved = {
                    key: decision
                    for key, decision in resolved.items()
                    if key in {"printer.view_audit", "printer.view_activity"}
                }
            decisions[(kind, value.id)] = resolved
            resources[(kind, value.id)] = frozenset(
                key for key, decision in resolved.items() if decision.allowed
            )
    return ResourceAccess(user.id, actor.is_admin, actor.permissions, resources, decisions)
