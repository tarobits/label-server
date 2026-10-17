"""Account policy with direct role grants and independent template ownership."""

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Protocol

from fastapi import HTTPException, Request

from app.identity import LOCAL_OWNER_ID

LEVELS = {"none": 0, "request": 1, "print": 2, "moderator": 3, "full": 4}
ADMINISTRATOR_ROLE_ID = "administrator"


@dataclass(frozen=True)
class GroupMembership:
    can_create: bool = False
    can_edit_others: bool = False
    can_delete_others: bool = False


@dataclass(frozen=True)
class Actor:
    id: str = LOCAL_OWNER_ID
    username: str = ""
    is_admin: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)
    role_ids: frozenset[str] = field(default_factory=frozenset)
    group_ids: frozenset[str] = field(default_factory=frozenset)
    printer_ids: frozenset[str] = field(default_factory=frozenset)
    destination_levels: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    group_memberships: Mapping[str, GroupMembership] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "destination_levels", MappingProxyType(dict(self.destination_levels))
        )
        object.__setattr__(
            self, "group_memberships", MappingProxyType(dict(self.group_memberships))
        )


class Action(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    SUBMIT = "submit"
    PRINT = "print"


@dataclass(frozen=True)
class Resource:
    kind: str
    identifier: str | None = None
    owner_id: str | None = None
    destination_id: str | None = None
    scope: str | None = None
    group_id: str | None = None


class AccessPolicy(Protocol):
    def allows(self, actor: Actor, action: Action, resource: Resource) -> bool: ...


class LocalOwnerPolicy:
    """Explicit test injection only, never a production authentication fallback."""

    def allows(self, actor: Actor, action: Action, resource: Resource) -> bool:
        return actor.id == LOCAL_OWNER_ID


class AccountPolicy:
    def __init__(self, destinations: Mapping[str, object]) -> None:
        self.destinations = frozenset(destinations)

    def can_destination(self, actor: Actor, identifier: str, minimum: str = "request") -> bool:
        if minimum not in LEVELS:
            raise ValueError("Unknown destination access level")
        if actor.is_admin:
            return True
        return (
            identifier in self.destinations
            and LEVELS.get(actor.destination_levels.get(identifier, "none"), 0) >= LEVELS[minimum]
        )

    def allows(self, actor: Actor, action: Action, resource: Resource) -> bool:
        if actor.is_admin:
            return True
        kind = resource.kind
        if kind.startswith("/api/admin"):
            return False
        if kind == "template":
            if resource.owner_id == actor.id:
                return True
            member = actor.group_memberships.get(resource.group_id or "")
            if action == Action.READ:
                return (
                    resource.scope == "global" or resource.scope == "group" and member is not None
                )
            if resource.scope == "group" and member is not None:
                return (
                    member.can_delete_others if action == Action.DELETE else member.can_edit_others
                )
            return False
        if kind in ("job", "run", "request"):
            if resource.owner_id == actor.id and action in (
                Action.READ,
                Action.WRITE,
                Action.DELETE,
            ):
                return True
            if resource.owner_id != actor.id:
                return bool(
                    resource.destination_id
                    and self.can_destination(actor, resource.destination_id, "moderator")
                )
        if kind in ("image_asset", "font_asset"):
            return resource.owner_id == actor.id and (
                action == Action.READ or "assets.write" in actor.permissions
            )
        if kind in ("batch", "flush"):
            return bool(
                resource.destination_id
                and self.can_destination(actor, resource.destination_id, "moderator")
            )
        # Application permissions are independent of any incidental destination.
        if kind.startswith("/api/") and action != Action.READ:
            if "tape-profiles" in kind or "cartridges" in kind:
                return "inventory.manage" in actor.permissions
            if kind in ("/api/printers", "/api/printer-groups") and action == Action.WRITE:
                return "printers.manage" in actor.permissions
            if "assets" in kind:
                return "assets.write" in actor.permissions
        if resource.destination_id:
            minimum = (
                "print"
                if action == Action.PRINT
                else "request"
                if action in (Action.READ, Action.SUBMIT)
                else "full"
            )
            return self.can_destination(actor, resource.destination_id, minimum)
        if action == Action.READ:
            return True  # Every list and object service additionally filters scope.
        if kind.startswith("/api/"):
            # IDs inside bodies and saved records are checked at the service boundary.
            if any(
                part in kind
                for part in (
                    "templates",
                    "runs",
                    "jobs",
                    "requests",
                    "queue",
                    "batches",
                    "printer",
                    "destinations",
                )
            ):
                return True
        return False


@dataclass(frozen=True)
class AccessContext:
    actor: Actor
    policy: AccessPolicy

    def can(self, action: Action, resource: Resource) -> bool:
        return self.policy.allows(self.actor, action, resource)

    def has_permission(self, permission: str) -> bool:
        return self.actor.is_admin or permission in self.actor.permissions

    def can_destination(self, identifier: str, minimum: str = "request") -> bool:
        if isinstance(self.policy, AccountPolicy):
            return self.policy.can_destination(self.actor, identifier, minimum)
        return self.can(Action.READ, Resource("destination", destination_id=identifier))

    def require_destination(self, identifier: str, minimum: str = "request") -> None:
        if not self.can_destination(identifier, minimum):
            raise HTTPException(403, "This destination access level is not permitted")

    def require(self, action: Action, resource: Resource) -> None:
        if not self.can(action, resource):
            raise HTTPException(403, "This operation is not permitted")


def access_context(request: Request) -> AccessContext:
    from sqlalchemy import select

    from app.auth import actor_for_user, check_csrf, session_user
    from app.models import PrinterDevice, PrinterGroup

    injected = getattr(request.app.state, "access_policy", None)
    if injected is not None:
        return AccessContext(Actor(is_admin=True), injected)
    # Never cache: preparation outside the lock must recheck current permissions.
    with request.app.state.factory() as session:
        authentication = session_user(request, session)
        if authentication is None:
            raise HTTPException(401, "Sign in to continue")
        user, login = authentication
        check_csrf(request, login)
        actor = actor_for_user(session, user)
        destinations: dict[str, object] = {
            device.id: None
            for device in session.scalars(select(PrinterDevice))
            if not device.config.get("retired")
        }
        destinations.update({group.id: None for group in session.scalars(select(PrinterGroup))})
        return AccessContext(actor, AccountPolicy(destinations))


async def authorize_request(request: Request) -> None:
    path = request.scope["route"].path
    destination = None
    if request.method == "POST" and path in (
        "/api/jobs",
        "/api/image-jobs",
        "/api/preview",
        "/api/image-jobs/preview",
        "/api/runs/prepare",
    ):
        try:
            body = await request.json()
            if isinstance(body, dict) and isinstance(body.get("destination_id"), str):
                destination = body["destination_id"]
        except ValueError:
            pass
    request.state.auth_body_destination = destination
    authorize_current_request(request)


def authorize_current_request(request: Request) -> None:
    """Apply coarse route gates again after mutation locks; services check objects."""
    context = access_context(request)
    path = request.scope["route"].path
    if path.startswith("/api/notifications") and not context.actor.is_admin:
        raise HTTPException(403, "Administrator access is required")
    action = (
        Action.READ
        if request.method in ("GET", "HEAD")
        or path in ("/api/preview", "/api/image-jobs/preview", "/api/csv/parse")
        else Action.DELETE
        if request.method == "DELETE"
        else Action.WRITE
    )
    if (
        path in ("/api/jobs", "/api/image-jobs", "/api/runs/prepare")
        and request.method == "POST"
        or path.endswith("/submit")
    ):
        action = Action.SUBMIT
    elif path == "/api/queue/print" or path == "/api/destinations/{identifier}/print":
        action = Action.PRINT
    # Only inputs consumed by the route can identify the authorized destination.
    # In particular, an unrelated destination_id cannot override a physical target.
    physical_routes = {"/api/status", "/api/printer/active-tape", "/api/printer/automatic-printing"}
    destination = request.query_params.get("printer_id") if path in physical_routes else None
    if path == "/api/queue/print":
        destination = request.query_params.get("destination_id") or request.query_params.get(
            "printer_id"
        )
    if (
        path.startswith("/api/destinations/")
        or path.startswith("/api/printers/{")
        or path.startswith("/api/printer-groups/{")
    ):
        destination = request.path_params.get("identifier")
    destination = getattr(request.state, "auth_body_destination", None) or destination
    if destination is None and (path in physical_routes or path == "/api/queue/print"):
        from sqlalchemy import select

        from app.models import PrinterDevice

        with request.app.state.factory() as session:
            devices = [
                device.id
                for device in session.scalars(select(PrinterDevice))
                if not device.config.get("retired")
            ]
        if len(devices) == 1:
            destination = devices[0]
    # Owner history and cancellation remain available after revocation.
    if action in (Action.DELETE, Action.READ) and any(
        part in path for part in ("/jobs/", "/runs/", "/requests/")
    ):
        destination = None
    if destination and path.endswith("/automatic-printing"):
        context.require_destination(destination, "moderator")
        action = Action.READ
    if destination and path == "/api/printers/{identifier}/stop":
        context.require_destination(destination, "moderator")
        action = Action.READ  # The endpoint additionally checks Full for emergency mode.
    context.require(
        action, Resource(path, request.path_params.get("identifier"), destination_id=destination)
    )
    if destination and request.method == "POST" and path in ("/api/jobs", "/api/image-jobs"):
        context.require_destination(destination, "print")
