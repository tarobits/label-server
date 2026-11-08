"""Resource ownership and access changes with scoped, stale-safe impact previews."""

import json
import secrets
import time
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.access import access_context
from app.admin_api import state_hash
from app.audit import AuditField, AuditRequirement, AuditScope, ScopeKind, append_audit
from app.auth import token_hash
from app.http import db, record
from app.models import (
    AccessChangeConfirmation,
    Cartridge,
    Companion,
    CompanionPrinter,
    Location,
    PrinterDevice,
    ResourceGrant,
    Role,
    User,
    new_id,
)
from app.resource_access import (
    CARTRIDGE_PERMISSIONS,
    PRINTER_PERMISSIONS,
    ResourceAccess,
    location_ancestors,
    resolve_resource_access,
    validate_grant,
    validate_location_parent,
)
from app.schemas import Input

router = APIRouter(prefix="/api/resource-access", tags=["resource access"])
DB = Annotated[Session, Depends(db, scope="function")]
MODELS: dict[str, Any] = {"printer": PrinterDevice, "cartridge": Cartridge, "location": Location}


def objects(session: Session, kind: str) -> list[Any]:
    return list(session.scalars(select(MODELS[kind])))


class GrantInput(Input):
    principal_kind: Literal["user", "role"]
    principal_id: str = Field(min_length=1, max_length=100)
    permission: str = Field(max_length=100)


class ResourceChange(Input):
    kind: Literal["printer", "cartridge", "location"]
    identifier: str = Field(min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: str | None = Field(default=None, max_length=100)
    owner_id: str | None = Field(default=None, max_length=100)
    location_id: str | None = Field(default=None, max_length=100)
    grants: list[GrantInput] | None = Field(default=None, max_length=1000)
    accept_owner_loss: bool = False


def rights_for(request: Request, session: Session) -> ResourceAccess:
    actor = access_context(request).actor
    user = session.get(User, actor.id)
    if user is None:
        raise HTTPException(403, "An account is required")
    return resolve_resource_access(session, user, actor=actor)


def management(rights: ResourceAccess, kind: str, identifier: str) -> dict[str, bool]:
    if kind == "location":
        allowed = rights.has("locations.manage")
        return {"transfer": False, "locate": allowed, "grants": allowed, "roles": allowed}
    return {
        "transfer": rights.can(kind, identifier, f"{kind}.transfer_ownership"),
        "locate": rights.can(
            kind, identifier, f"{kind}.{'configure' if kind == 'printer' else 'edit_details'}"
        ),
        "grants": rights.can(
            kind,
            identifier,
            f"{kind}.{'manage_user_access' if kind == 'printer' else 'manage_access'}",
        ),
        "roles": rights.is_admin
        or kind == "cartridge"
        and rights.can(kind, identifier, "cartridge.manage_access"),
    }


def resource_grants(session: Session, kind: str, identifier: str) -> list[dict[str, str]]:
    return [
        {key: getattr(grant, key) for key in ("principal_kind", "principal_id", "permission")}
        for grant in session.scalars(
            select(ResourceGrant)
            .where(ResourceGrant.scope_kind == kind, ResourceGrant.scope_id == identifier)
            .order_by(
                ResourceGrant.principal_kind, ResourceGrant.principal_id, ResourceGrant.permission
            )
        )
    ]


@router.get("")
def catalog(request: Request, session: DB) -> dict[str, Any]:
    rights = rights_for(request, session)
    resources = []
    for kind in MODELS:
        for value in objects(session, kind):
            abilities = management(rights, kind, value.id)
            inherited_location = kind == "printer" and session.get(CompanionPrinter, value.id) is not None
            if inherited_location:
                abilities["locate"] = False
            if not any(abilities[key] for key in ("transfer", "locate", "grants")):
                continue
            resources.append(
                {
                    "kind": kind,
                    "id": value.id,
                    "name": value.name,
                    "owner_id": getattr(value, "owner_id", None),
                    "location_id": getattr(value, "location_id", None),
                    "parent_id": getattr(value, "parent_id", None),
                    "inherited_location": inherited_location,
                    "abilities": abilities,
                    "grants": resource_grants(session, kind, value.id)
                    if abilities["grants"]
                    else [],
                }
            )
    permitted = bool(resources) or rights.has("locations.manage")
    return {
        "resources": resources,
        "users": [
            {"id": user.id, "name": user.username}
            for user in session.scalars(
                select(User).where(User.disabled.is_(False)).order_by(User.username)
            )
        ]
        if permitted
        else [],
        "roles": [{"id": role.id, "name": role.name} for role in session.scalars(select(Role))]
        if any(item["abilities"]["roles"] for item in resources) or rights.has("locations.manage")
        else [],
        "locations": [record(value) for value in session.scalars(select(Location))]
        if permitted
        else [],
        "manage_locations": rights.has("locations.manage"),
        "permissions": {
            "printer": sorted(PRINTER_PERMISSIONS),
            "cartridge": sorted(CARTRIDGE_PERMISSIONS),
        },
    }


def affected_resources(session: Session, body: ResourceChange) -> set[tuple[str, str]]:
    if body.kind != "location":
        return {(body.kind, body.identifier)}
    parents = dict(session.execute(select(Location.id, Location.parent_id)).all())
    return {
        (kind, value.id)
        for kind in ("printer", "cartridge")
        for value in objects(session, kind)
        if value.location_id and body.identifier in location_ancestors(parents, value.location_id)
    }


def access_snapshot(session: Session, resources: set[tuple[str, str]]) -> dict[str, Any]:
    result = {}
    for user in session.scalars(select(User)):
        rights = resolve_resource_access(session, user)
        result[user.id] = {
            "name": user.username,
            "resources": {
                f"{kind}:{identifier}": sorted(rights.resources.get((kind, identifier), ()))
                for kind, identifier in sorted(resources)
            },
        }
    return result


def apply_resource_change(
    session: Session,
    rights: ResourceAccess,
    body: ResourceChange,
    *,
    installation_printer: str | None = None,
) -> Any:
    model = MODELS[body.kind]
    value = session.get(model, body.identifier)
    abilities = management(rights, body.kind, body.identifier)
    supplied = body.model_fields_set
    if body.kind == "location":
        if not rights.has("locations.manage"):
            raise HTTPException(403, "Location management permission is required")
        if supplied & {"owner_id", "location_id"}:
            raise HTTPException(422, "Locations cannot have owners or locations")
        if value is None:
            if not body.name:
                raise HTTPException(422, "A location name is required")
            value = Location(id=body.identifier, name=body.name)
            session.add(value)
        if body.name is not None:
            value.name = body.name
        if "parent_id" in supplied:
            try:
                validate_location_parent(session, body.identifier, body.parent_id)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            value.parent_id = body.parent_id
    else:
        if value is None:
            raise HTTPException(404, "Resource not found")
        if supplied & {"name", "parent_id"}:
            raise HTTPException(422, "Use the resource editor to rename this resource")
        if "owner_id" in supplied:
            if not abilities["transfer"]:
                raise HTTPException(
                    403, "Only the owner or an authorized global editor may transfer ownership"
                )
            owner = session.get(User, body.owner_id) if body.owner_id else None
            if owner is None or owner.disabled:
                raise HTTPException(422, "Choose an enabled owner")
            from app.ownership import record_ownership

            record_ownership(session, body.kind, value, at=0)
            value.owner_id = owner.id
            record_ownership(session, body.kind, value)
        if "location_id" in supplied:
            if body.kind == "printer":
                link = session.get(CompanionPrinter, body.identifier)
                companion = session.get(Companion, link.companion_id) if link else None
                if companion and body.location_id != companion.location_id:
                    raise HTTPException(409, "This printer inherits its companion's location")
            installation = (
                session.get(PrinterDevice, installation_printer) if installation_printer else None
            )
            installing = bool(
                installation
                and body.kind == "cartridge"
                and supplied == {"kind", "identifier", "location_id"}
                and body.location_id == installation.location_id
                and rights.can("printer", installation.id, "printer.swap_cartridges")
                and rights.can("cartridge", body.identifier, "cartridge.view")
            )
            if not abilities["locate"] and not installing:
                raise HTTPException(403, "Resource configuration permission is required")
            if body.location_id and session.get(Location, body.location_id) is None:
                raise HTTPException(422, "Location not found")
            value.location_id = body.location_id
    if body.grants is not None:
        if not abilities["grants"]:
            raise HTTPException(403, "Resource access management permission is required")
        if not abilities["roles"] and any(g.principal_kind != "user" for g in body.grants):
            raise HTTPException(403, "Printer owners may manage direct user grants only")
        if len({(g.principal_kind, g.principal_id, g.permission) for g in body.grants}) != len(
            body.grants
        ):
            raise HTTPException(422, "Duplicate grant")
        session.flush()
        query = delete(ResourceGrant).where(
            ResourceGrant.scope_kind == body.kind, ResourceGrant.scope_id == body.identifier
        )
        if not abilities["roles"]:
            query = query.where(ResourceGrant.principal_kind == "user")
        session.execute(query)
        for item in body.grants:
            grant = ResourceGrant(
                scope_kind=body.kind, scope_id=body.identifier, **item.model_dump()
            )
            try:
                validate_grant(session, grant)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            session.add(grant)
    session.flush()
    return value


def change_fingerprint(body: ResourceChange) -> str:
    return token_hash(
        json.dumps(
            body.model_dump(exclude_unset=True, exclude={"accept_owner_loss"}), sort_keys=True
        )
    )


@router.post("/preview")
def preview(body: ResourceChange, request: Request, session: DB) -> dict[str, Any]:
    rights = rights_for(request, session)
    fingerprint = state_hash(session)
    resources = affected_resources(session, body)
    before = access_snapshot(session, resources)
    cartridge = session.get(Cartridge, body.identifier) if body.kind == "cartridge" else None
    claims_debts = bool(cartridge and cartridge.owner_id is None and body.owner_id)
    with session.begin_nested() as savepoint:
        apply_resource_change(session, rights, body)
        resources |= affected_resources(session, body)
        after = access_snapshot(session, resources)
        savepoint.rollback()
    changes = [
        {
            "id": user,
            "name": after[user]["name"],
            "before": before[user]["resources"],
            "after": after[user]["resources"],
        }
        for user in after
        if before[user]["resources"] != after[user]["resources"]
    ]
    loss_warning = any(
        "cartridge.approve_use" in permissions
        and "cartridge.approve_use" not in item["before"].get(key, [])
        for item in changes
        for key, permissions in item["after"].items()
    ) or any(grant.permission == "cartridge.approve_use" for grant in body.grants or [])
    token = secrets.token_urlsafe(32)
    session.add(
        AccessChangeConfirmation(
            token_hash=token_hash(token),
            actor_id=rights.user_id,
            request_hash=change_fingerprint(body),
            state_hash=fingerprint,
            expires_at=time.time() + 600,
        )
    )
    return {
        "confirmation_token": token,
        "affected_users": changes,
        "owner_loss_warning": loss_warning,
        "claims_unassigned_debts": claims_debts,
    }


@router.post("/apply")
def apply(body: ResourceChange, request: Request, session: DB) -> dict[str, Any]:
    rights = rights_for(request, session)
    receipt = session.get(
        AccessChangeConfirmation, token_hash(request.headers.get("x-access-confirmation", ""))
    )
    if (
        receipt is None
        or receipt.actor_id != rights.user_id
        or receipt.expires_at <= time.time()
        or receipt.request_hash != change_fingerprint(body)
        or receipt.state_hash != state_hash(session)
    ):
        raise HTTPException(409, "Preview the current access changes before confirming")
    if (
        any(grant.permission == "cartridge.approve_use" for grant in body.grants or [])
        and not body.accept_owner_loss
    ):
        raise HTTPException(
            422, "Acknowledge that Approve use may reduce the cartridge owner's income"
        )
    value = mutate_with_evidence(session, request, rights, body)
    session.delete(receipt)
    from app.job_access import reconcile_access_holds

    reconcile_access_holds(session)
    return {"id": value.id}


def mutate_with_evidence(
    session: Session,
    request: Request,
    rights: ResourceAccess,
    body: ResourceChange,
    *,
    installation_printer: str | None = None,
) -> Any:
    value = session.get(MODELS[body.kind], body.identifier)
    old_grants = resource_grants(session, body.kind, body.identifier)
    old_owner, old_location = getattr(value, "owner_id", None), getattr(value, "location_id", None)
    resources = affected_resources(session, body)
    before = access_snapshot(session, resources)
    value = apply_resource_change(session, rights, body, installation_printer=installation_printer)
    resources |= affected_resources(session, body)
    after = access_snapshot(session, resources)
    actor = access_context(request).actor
    if isinstance(value, Cartridge) and old_owner is None and value.owner_id is not None:
        from app.cartridge_debts import assign_unowned

        assign_unowned(session, value, actor.id, actor.username)
    attribution = {
        "actor_id": AuditField(actor.id, ()),
        "actor_name": AuditField(actor.username, ()),
    }
    scopes = (
        (AuditScope(body.kind, body.identifier),)
        if body.kind != "location"
        else (AuditScope("global"),)
    )
    rule = (
        (AuditRequirement(body.kind, body.identifier, f"{body.kind}.view_audit"),)
        if body.kind != "location"
        else (AuditRequirement("application", "", "audit.view_all"),)
    )
    new_grants = resource_grants(session, body.kind, body.identifier)
    principals = {(g["principal_kind"], g["principal_id"]) for g in old_grants + new_grants}
    for principal_kind, principal_id in principals:
        old_permissions, new_permissions = [
            sorted(
                g["permission"]
                for g in grants
                if g["principal_kind"] == principal_kind and g["principal_id"] == principal_id
            )
            for grants in (old_grants, new_grants)
        ]
        if old_permissions != new_permissions:
            append_audit(
                session,
                event_id=new_id(),
                action="permission.changed",
                outcome="succeeded",
                occurred_at=time.time(),
                scopes=scopes,
                fields={
                    **attribution,
                    "principal_kind": AuditField(principal_kind, rule),
                    "principal_id": AuditField(principal_id, rule),
                    "old_permissions": AuditField(old_permissions, rule),
                    "new_permissions": AuditField(new_permissions, rule),
                },
            )
    append_audit(
        session,
        event_id=new_id(),
        action="resource.access_changed",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=scopes,
        fields={
            **attribution,
            "resource_kind": AuditField(body.kind, rule),
            "resource_id": AuditField(body.identifier, rule),
            "old_owner_id": AuditField(old_owner, rule),
            "new_owner_id": AuditField(getattr(value, "owner_id", None), rule),
            "old_location_id": AuditField(old_location, rule),
            "new_location_id": AuditField(getattr(value, "location_id", None), rule),
        },
    )
    for user_id in after:
        for kind, identifier in resources:
            key = f"{kind}:{identifier}"
            old, new = (
                before[user_id]["resources"].get(key, []),
                after[user_id]["resources"].get(key, []),
            )
            if old == new:
                continue
            field_rule = (AuditRequirement(kind, identifier, f"{kind}.view_audit"),)
            append_audit(
                session,
                event_id=new_id(),
                action="permission.changed",
                outcome="succeeded",
                occurred_at=time.time(),
                scopes=(AuditScope(cast(ScopeKind, kind), identifier),),
                fields={
                    **attribution,
                    "victim_ids": AuditField([user_id], field_rule),
                    "victim_names": AuditField([after[user_id]["name"]], field_rule),
                    "old_permissions": AuditField(old, field_rule),
                    "new_permissions": AuditField(new, field_rule),
                },
            )
    return value
