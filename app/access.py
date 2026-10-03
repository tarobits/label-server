"""Application access boundary. Local-owner mode is not authentication.

Future authentication supplies Actor here; request headers never choose an actor.
Policies belong here and in application services, never in rendering or drivers.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from fastapi import HTTPException, Request

from app.identity import DEFAULT_PRINTER_ID, LOCAL_OWNER_ID


@dataclass(frozen=True)
class Actor:
    id: str = LOCAL_OWNER_ID


class Action(str, Enum):
    READ = "read"
    WRITE = "write"
    SUBMIT = "submit"
    PRINT = "print"


@dataclass(frozen=True)
class Resource:
    kind: str
    identifier: str | None = None
    owner_id: str | None = None
    destination_id: str | None = None


class AccessPolicy(Protocol):
    def allows(self, actor: Actor, action: Action, resource: Resource) -> bool: ...


class LocalOwnerPolicy:
    def allows(self, actor: Actor, action: Action, resource: Resource) -> bool:
        return actor.id == LOCAL_OWNER_ID and resource.destination_id in (None, DEFAULT_PRINTER_ID)


@dataclass(frozen=True)
class AccessContext:
    actor: Actor
    policy: AccessPolicy
    destination_id: str = DEFAULT_PRINTER_ID

    def require(self, action: Action, resource: Resource) -> None:
        if not self.policy.allows(self.actor, action, resource):
            raise HTTPException(403, "This operation is not permitted")


def access_context(request: Request) -> AccessContext:
    # Deliberately no X-User/Authorization parsing until the gated account phase.
    return AccessContext(Actor(), request.app.state.access_policy)


def authorize_request(request: Request) -> None:
    context = access_context(request)
    path = request.scope["route"].path
    action = (
        Action.READ
        if request.method in ("GET", "HEAD")
        or path in ("/api/preview", "/api/image-jobs/preview", "/api/csv/inspect")
        else Action.WRITE
    )
    if (
        path in ("/api/jobs", "/api/image-jobs")
        and request.method == "POST"
        or path.endswith("/submit")
    ):
        action = Action.SUBMIT
    elif path == "/api/queue/print":
        action = Action.PRINT
    context.require(
        action,
        Resource(
            path, request.path_params.get("identifier"), destination_id=context.destination_id
        ),
    )
