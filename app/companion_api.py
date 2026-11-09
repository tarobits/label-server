"""Companion enrollment and explicit human identity bindings."""

import json
import secrets
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import __version__
from app.access import access_context
from app.action_audit import record_action
from app.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.auth import actor_for_user, hash_password, token_hash, verify_password
from app.avatars import avatar_version, read_avatar
from app.companion_auth import DeviceDB, accessible_user, operator
from app.http import db
from app.models import (
    AccessChangeConfirmation,
    Companion,
    CompanionPin,
    CompanionPrinter,
    CompanionSession,
    Location,
    PrinterDevice,
    ResourceGrant,
    User,
    new_id,
)
from app.queue import require_idle
from app.resource_access import resolve_resource_access, validate_grant
from app.resource_api import GrantInput
from app.schemas import Input

router = APIRouter(prefix="/api", tags=["companions"])
DB = Annotated[Session, Depends(db, scope="function")]


@router.get("/companion/operator")
def operator_details(request: Request, session: DeviceDB) -> dict[str, Any]:
    user = operator(request, session)
    actor = actor_for_user(session, user)
    companion: Companion = session.info["companion"]
    identifiers = set(
        session.scalars(
            select(CompanionPrinter.printer_id).where(CompanionPrinter.companion_id == companion.id)
        )
    )
    from app.models import PrinterGroup

    groups = {
        group.id: {"name": group.name, "printer_ids": group.printer_ids}
        for group in session.scalars(select(PrinterGroup))
        if identifiers.intersection(group.printer_ids)
    }
    return {
        "id": user.id,
        "username": user.username,
        "permissions": sorted(actor.permissions),
        "groups": groups,
        "printer_permissions": {
            key: sorted(value)
            for key, value in actor.destination_permissions.items()
            if key in identifiers or key in groups
        },
        "cartridge_permissions": {
            key: sorted(value) for key, value in actor.cartridge_permissions.items()
        },
        "location_id": companion.location_id,
    }


def clear_printer(session: Session, identifier: str, user: User) -> dict[str, int]:
    link = session.get(CompanionPrinter, identifier)
    if not link:
        raise HTTPException(404, "Companion printer not found")
    actor = actor_for_user(session, user)
    if not actor.is_admin and "printer.review" not in actor.destination_permissions.get(
        identifier, ()
    ):
        raise HTTPException(403, "Review permission is required")
    try:
        require_idle(session, identifier)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    link.blocked = False
    link.clearance += 1
    append_audit(
        session,
        event_id=new_id(),
        action="companion.printer_cleared",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("printer", identifier),),
        fields={"actor_id": AuditField(user.id, ()), "actor_name": AuditField(user.username, ())},
    )
    return {"clearance": link.clearance}


@router.post("/companion/printers/{identifier}/clear")
def local_clear(identifier: str, request: Request, session: DeviceDB) -> dict[str, int]:
    from app.companion_transport_api import owned_printer

    owned_printer(session, identifier)
    return clear_printer(session, identifier, operator(request, session))


@router.post("/companions/printers/{identifier}/clear")
def main_clear(identifier: str, request: Request, session: DB) -> dict[str, int]:
    user = session.get(User, access_context(request).actor.id)
    if not user:
        raise HTTPException(403, "An account is required")
    return clear_printer(session, identifier, user)


class CompanionInput(Input):
    name: str = Field(min_length=1, max_length=100)
    location_id: str = Field(min_length=1, max_length=100)
    bound_user_id: str | None = Field(default=None, max_length=100)
    grants: list[GrantInput] = Field(default_factory=list, max_length=1000)
    expected_revision: int | None = None


class PinInput(Input):
    current_password: SecretStr = Field(max_length=256)
    pin: SecretStr | None = Field(default=None, min_length=4, max_length=12)


class UnlockInput(Input):
    user_id: str = Field(min_length=1, max_length=100)
    pin: SecretStr | None = Field(default=None, min_length=4, max_length=12)
    lifetime_seconds: int = Field(default=300, ge=30, le=86400)


def admin(request: Request) -> None:
    if not access_context(request).actor.is_admin:
        raise HTTPException(403, "Administrator access is required")


def public_companion(session: Session, item: Companion) -> dict[str, Any]:
    if item.key_hash is None:
        status = "revoked"
    elif item.last_seen_at is None:
        status = "never_connected"
    elif item.last_seen_at >= time.time() - 30:
        status = "online"
    else:
        status = "offline"
    return {
        "id": item.id,
        "name": item.name,
        "location_id": item.location_id,
        "bound_user_id": item.bound_user_id,
        "revision": item.revision,
        "enabled": item.key_hash is not None,
        "last_seen_at": item.last_seen_at,
        "status": status,
        "software_version": item.software_version,
        "server_version": __version__,
        "grants": [
            {
                "principal_kind": grant.principal_kind,
                "principal_id": grant.principal_id,
                "permission": grant.permission,
                "effect": grant.effect,
            }
            for grant in session.scalars(
                select(ResourceGrant).where(
                    ResourceGrant.scope_kind == "companion", ResourceGrant.scope_id == item.id
                )
            )
        ],
    }


def change(session: Session, item: Companion, body: CompanionInput) -> None:
    if session.get(Location, body.location_id) is None:
        raise HTTPException(422, "Choose an existing location")
    if body.bound_user_id:
        user = session.get(User, body.bound_user_id)
        if not user or user.disabled:
            raise HTTPException(422, "Choose an enabled user")
    grants = [
        ResourceGrant(scope_kind="companion", scope_id=item.id, **entry.model_dump())
        for entry in body.grants
    ]
    for grant in grants:
        try:
            validate_grant(session, grant)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    keys = {(g.principal_kind, g.principal_id, g.permission) for g in grants}
    if len(keys) != len(grants):
        raise HTTPException(422, "Duplicate companion grants")
    session.execute(
        delete(ResourceGrant).where(
            ResourceGrant.scope_kind == "companion", ResourceGrant.scope_id == item.id
        )
    )
    session.add_all(grants)
    item.name, item.location_id, item.bound_user_id = (
        body.name,
        body.location_id,
        body.bound_user_id,
    )
    for printer in session.scalars(
        select(PrinterDevice).join(CompanionPrinter).where(CompanionPrinter.companion_id == item.id)
    ):
        printer.location_id = item.location_id
    session.flush()
    if body.bound_user_id:
        accessible_user(session, item, body.bound_user_id)


@router.get("/companions")
def companions(request: Request, session: DB) -> list[dict[str, Any]]:
    admin(request)
    return [public_companion(session, item) for item in session.scalars(select(Companion))]


@router.post("/companions", status_code=201)
def create_companion(body: CompanionInput, request: Request, session: DB) -> dict[str, Any]:
    admin(request)
    if session.get(Location, body.location_id) is None:
        raise HTTPException(422, "Choose an existing location")
    key = secrets.token_urlsafe(48)
    item = Companion(name=body.name, location_id=body.location_id, key_hash=token_hash(key))
    session.add(item)
    session.flush()
    change(session, item, body)
    record_action(
        session, "companion.created", "global", "", {"companion_id": item.id, "name": item.name}
    )
    return {**public_companion(session, item), "api_key": key}


@router.put("/companions/{identifier}")
def update_companion(
    identifier: str, body: CompanionInput, request: Request, session: DB
) -> dict[str, Any]:
    admin(request)
    item = session.get(Companion, identifier)
    if not item:
        raise HTTPException(404, "Companion not found")
    if body.expected_revision != item.revision:
        raise HTTPException(409, "The companion changed; reload its settings")
    from app.admin_api import state_hash

    receipt = session.get(
        AccessChangeConfirmation, token_hash(request.headers.get("x-access-confirmation", ""))
    )
    if (
        not receipt
        or receipt.actor_id != access_context(request).actor.id
        or receipt.expires_at <= time.time()
        or receipt.state_hash != state_hash(session)
        or receipt.request_hash != companion_fingerprint(identifier, body)
    ):
        raise HTTPException(409, "Review the companion access changes before saving")
    change(session, item, body)
    session.delete(receipt)
    item.revision += 1
    record_action(
        session,
        "companion.settings_changed",
        "global",
        "",
        {
            "companion_id": item.id,
            "name": item.name,
            "location_id": item.location_id,
            "bound_user_id": item.bound_user_id,
            "principal_ids": [f"{g.principal_kind}:{g.principal_id}" for g in body.grants],
        },
    )
    return public_companion(session, item)


def companion_fingerprint(identifier: str, body: CompanionInput) -> str:
    return token_hash(
        json.dumps({"companion": identifier, "body": body.model_dump()}, sort_keys=True)
    )


@router.post("/companions/{identifier}/preview")
def preview_companion(
    identifier: str, body: CompanionInput, request: Request, session: DB
) -> dict[str, Any]:
    from app.admin_api import state_hash
    from app.resource_api import access_snapshot

    admin(request)
    item = session.get(Companion, identifier)
    if not item:
        raise HTTPException(404, "Companion not found")
    if body.expected_revision != item.revision:
        raise HTTPException(409, "The companion changed; reload its settings")
    resources = {("companion", identifier)} | {
        ("printer", value)
        for value in session.scalars(
            select(CompanionPrinter.printer_id).where(CompanionPrinter.companion_id == identifier)
        )
    }
    before = access_snapshot(session, resources)
    with session.begin_nested() as savepoint:
        change(session, item, body)
        after = access_snapshot(session, resources)
        savepoint.rollback()
    token = secrets.token_urlsafe(32)
    session.add(
        AccessChangeConfirmation(
            token_hash=token_hash(token),
            actor_id=access_context(request).actor.id,
            request_hash=companion_fingerprint(identifier, body),
            state_hash=state_hash(session),
            expires_at=time.time() + 600,
        )
    )
    return {
        "confirmation_token": token,
        "affected_users": [
            {
                "id": identifier,
                "name": after[identifier]["name"],
                "before": before[identifier]["resources"],
                "after": after[identifier]["resources"],
            }
            for identifier in after
            if before[identifier] != after[identifier]
        ],
    }


@router.post("/companions/{identifier}/key")
def rotate_key(identifier: str, request: Request, session: DB) -> dict[str, str]:
    admin(request)
    item = session.get(Companion, identifier)
    if not item:
        raise HTTPException(404, "Companion not found")
    key = secrets.token_urlsafe(48)
    item.key_hash, item.revision = token_hash(key), item.revision + 1
    record_action(session, "companion.key_rotated", "global", "", {"companion_id": item.id})
    return {"api_key": key}


@router.delete("/companions/{identifier}/key")
def revoke_key(identifier: str, request: Request, session: DB) -> dict[str, bool]:
    admin(request)
    item = session.get(Companion, identifier)
    if not item:
        raise HTTPException(404, "Companion not found")
    item.key_hash, item.revision = None, item.revision + 1
    record_action(session, "companion.revoked", "global", "", {"companion_id": item.id})
    return {"ok": True}


@router.get("/companions/account/pin")
def pin_status(request: Request, session: DB) -> dict[str, bool]:
    return {"configured": session.get(CompanionPin, access_context(request).actor.id) is not None}


@router.put("/companions/account/pin")
def set_pin(body: PinInput, request: Request, session: DB) -> dict[str, bool]:
    actor = access_context(request).actor
    request.app.state.auth_limiter.check(request, f"pin-setup:{actor.id}")
    user = session.get(User, actor.id)
    if not user or not verify_password(
        body.current_password.get_secret_value(), user.password_hash
    ):
        raise HTTPException(403, "Current password is incorrect")
    value = body.pin.get_secret_value() if body.pin else None
    if value is not None and (not value.isascii() or not value.isdigit()):
        raise HTTPException(422, "PIN must contain 4–12 digits")
    session.execute(delete(CompanionPin).where(CompanionPin.user_id == user.id))
    session.execute(delete(CompanionSession).where(CompanionSession.user_id == user.id))
    if value:
        session.add(CompanionPin(user_id=user.id, pin_hash=hash_password(value)))
    record_action(session, "account.pin_changed", "global", "", {"configured": value is not None})
    return {"configured": value is not None}


@router.get("/companion/users")
def station_users(request: Request, session: DeviceDB) -> dict[str, Any]:
    item: Companion = session.info["companion"]
    users = []
    for user in session.scalars(
        select(User).where(User.disabled.is_(False)).order_by(User.username)
    ):
        if item.bound_user_id and item.bound_user_id != user.id:
            continue
        if resolve_resource_access(session, user).can("companion", item.id, "companion.access"):
            if item.bound_user_id or session.get(CompanionPin, user.id):
                users.append(
                    {
                        "id": user.id,
                        "username": user.username,
                        "avatar_version": avatar_version(session, user.id),
                    }
                )
    return {
        "id": item.id,
        "name": item.name,
        "location_id": item.location_id,
        "bound_user_id": item.bound_user_id,
        "users": users,
    }


@router.get("/companion/users/{identifier}/avatar")
def station_avatar(identifier: str, request: Request, session: DeviceDB) -> Response:
    item: Companion = session.info["companion"]
    user = accessible_user(session, item, identifier)
    if not item.bound_user_id and not session.get(CompanionPin, user.id):
        raise HTTPException(404, "User is not available at this station")
    try:
        data = read_avatar(session, user.id)
    except FileNotFoundError:
        raise HTTPException(404, "No profile picture") from None
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.post("/companion/unlock")
def unlock(body: UnlockInput, request: Request, session: DeviceDB) -> dict[str, Any]:
    item: Companion = session.info["companion"]
    request.app.state.auth_limiter.check(request, f"pin:{body.user_id}")
    user = accessible_user(session, item, body.user_id)
    pin = session.get(CompanionPin, user.id)
    if not item.bound_user_id and (
        not pin or not body.pin or not verify_password(body.pin.get_secret_value(), pin.pin_hash)
    ):
        raise HTTPException(401, "Invalid user or PIN")
    # A bound installation verifies its deployment PIN locally. This trust is
    # restricted to the exact administrator-approved identity, never a body override.
    token = secrets.token_urlsafe(32)
    session.execute(delete(CompanionSession).where(CompanionSession.expires_at <= time.time()))
    session.add(
        CompanionSession(
            token_hash=token_hash(token),
            companion_id=item.id,
            user_id=user.id,
            revision=item.revision,
            pin_fingerprint=None
            if item.bound_user_id
            else token_hash(pin.pin_hash)
            if pin
            else None,
            expires_at=time.time() + body.lifetime_seconds,
        )
    )
    append_audit(
        session,
        event_id=new_id(),
        action="companion.unlocked",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("global", ""),),
        fields={
            "companion_id": AuditField(
                item.id, (AuditRequirement("application", "", "audit.view_all"),)
            ),
            "actor_id": AuditField(user.id, ()),
            "actor_name": AuditField(user.username, ()),
        },
    )
    actor = actor_for_user(session, user)
    return {
        "session_token": token,
        "user": {"id": user.id, "username": user.username},
        "expires_in": body.lifetime_seconds,
        "permissions": sorted(actor.permissions),
    }


@router.post("/companion/lock")
def lock_station(request: Request, session: DeviceDB) -> dict[str, bool]:
    user = operator(request, session)
    item: Companion = session.info["companion"]
    session.execute(
        delete(CompanionSession).where(
            CompanionSession.token_hash
            == token_hash(request.headers.get("x-companion-session", ""))
        )
    )
    append_audit(
        session,
        event_id=new_id(),
        action="companion.locked",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("global", ""),),
        fields={
            "companion_id": AuditField(
                item.id, (AuditRequirement("application", "", "audit.view_all"),)
            ),
            "actor_id": AuditField(user.id, ()),
            "actor_name": AuditField(user.username, ()),
        },
    )
    return {"ok": True}
