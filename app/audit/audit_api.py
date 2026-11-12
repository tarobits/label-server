"""Read current authorized audit projections; recording is action-specific."""

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.audit.audit import (
    AuditField,
    AuditFilters,
    AuditScope,
    ScopeKind,
    append_audit,
    audit_page,
)
from app.authn.access import access_context
from app.authn.resource_access import ResourceAccess, resolve_resource_access
from app.models import User, new_id

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def audit_history(
    request: Request,
    printer: str | None = Query(default=None, max_length=100),
    cartridge: str | None = Query(default=None, max_length=100),
    action: str | None = Query(default=None, max_length=100),
    actor: str | None = Query(default=None, max_length=100),
    victim: str | None = Query(default=None, max_length=100),
    search: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    # A read also records an access event. Serialize it with mutations so a long
    # SQLite read transaction cannot race its own final write or access revocation.
    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        context = access_context(request)
        user = session.get(User, context.actor.id)
        rights = (
            resolve_resource_access(session, user, actor=context.actor)
            if user
            else ResourceAccess(
                context.actor.id, context.actor.is_admin, context.actor.permissions, {}
            )
        )
        if not rights.has("audit.view_all") and not any(
            f"{kind}.view_audit" in permissions
            for (kind, _), permissions in rights.resources.items()
        ):
            raise HTTPException(403, "Audit log access is required")
        result = audit_page(
            session,
            rights,
            filters=AuditFilters(
                printer=printer,
                cartridge=cartridge,
                action=action,
                actor=actor,
                victim=victim,
                search=search,
            ),
            offset=offset,
            limit=limit,
        )
        targets: tuple[tuple[ScopeKind, str | None], ...] = (
            ("printer", printer),
            ("cartridge", cartridge),
        )
        scopes = tuple(
            AuditScope(kind, identifier)
            for kind, identifier in targets
            if identifier and rights.can(kind, identifier, f"{kind}.view_audit")
        )
        append_audit(
            session,
            event_id=new_id(),
            action="audit.viewed",
            outcome="succeeded",
            occurred_at=time.time(),
            scopes=scopes or (AuditScope("global"),),
            fields={
                "actor_id": AuditField(context.actor.id, ()),
                "actor_name": AuditField(context.actor.username, ()),
            },
        )
        return result
