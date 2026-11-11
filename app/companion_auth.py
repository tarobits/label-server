"""Installation keys never confer arbitrary user identity or account sessions."""

import re
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import actor_for_user, token_hash
from app.models import (
    Batch,
    Companion,
    CompanionPin,
    CompanionPrinter,
    CompanionSession,
    PrinterGroup,
    PrintJob,
    User,
)
from app.resource_access import resolve_resource_access

if TYPE_CHECKING:
    from app.access import AccessContext


def revoke_sessions(session: Session, user_id: str, *, clear_pin: bool = False) -> None:
    session.execute(delete(CompanionSession).where(CompanionSession.user_id == user_id))
    if clear_pin:
        session.execute(delete(CompanionPin).where(CompanionPin.user_id == user_id))


def installation(request: Request, session: Session) -> Companion:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or len(authorization) > 256:
        raise HTTPException(401, "Invalid companion key")
    companion = session.scalar(
        select(Companion).where(Companion.key_hash == token_hash(authorization[7:]))
    )
    if companion is None:
        raise HTTPException(401, "Invalid companion key")
    return companion


def device_db(request: Request) -> Iterator[Session]:
    with request.app.state.fleet.lock, request.app.state.factory.begin() as session:
        companion = installation(request, session)
        version = request.headers.get("x-companion-version")
        # Missing headers are expected from older companions. Invalid telemetry
        # must not interrupt printing or be reflected back into the interface.
        companion.software_version = (
            version
            if version and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}", version)
            else None
        )
        session.info["companion"] = companion
        companion.last_seen_at = time.time()
        yield session
    request.app.state.fleet.sync()
    request.app.state.wake.set()


DeviceDB = Annotated[Session, Depends(device_db, scope="function")]


def accessible_user(session: Session, companion: Companion, identifier: str) -> User:
    user = session.get(User, identifier)
    if (
        user is None
        or user.disabled
        or not resolve_resource_access(session, user).can(
            "companion", companion.id, "companion.access"
        )
    ):
        raise HTTPException(403, "Companion access is not granted")
    if companion.bound_user_id and companion.bound_user_id != identifier:
        raise HTTPException(403, "This companion is bound to a different user")
    return user


def operator(request: Request, session: Session) -> User:
    companion = installation(request, session)
    token = request.headers.get("x-companion-session", "")
    stored = session.get(CompanionSession, token_hash(token)) if len(token) <= 256 else None
    if (
        not stored
        or stored.companion_id != companion.id
        or stored.revision != companion.revision
        or stored.expires_at <= time.time()
    ):
        raise HTTPException(401, "Unlock the companion to continue")
    user = accessible_user(session, companion, stored.user_id)
    if stored.pin_fingerprint is not None:
        pin = session.get(CompanionPin, user.id)
        if not pin or token_hash(pin.pin_hash) != stored.pin_fingerprint:
            raise HTTPException(401, "Unlock the companion to continue")
    return user


def station_context(request: Request, session: Session) -> "AccessContext":
    from app.access import AccessContext, AccountPolicy

    user = operator(request, session)
    item = installation(request, session)
    actor = actor_for_user(session, user)
    printers = set(
        session.scalars(
            select(CompanionPrinter.printer_id).where(CompanionPrinter.companion_id == item.id)
        )
    )
    groups = {
        group.id
        for group in session.scalars(select(PrinterGroup))
        if printers.intersection(group.printer_ids)
    }
    destinations = printers | groups
    path = getattr(request.scope.get("route"), "path", "")
    method = request.method
    allowed = False
    if method == "GET" and path in ("/api/printers", "/api/tape-profiles", "/api/cartridges"):
        allowed = True
    if method == "POST" and path == "/api/cartridges":
        allowed = True
    if method == "POST" and path == "/api/cartridge-quotes":
        allowed = request.query_params.get("printer_id") in printers
    if path in (
        "/api/status",
        "/api/printer/active-tape",
        "/api/printer/automatic-printing",
        "/api/queue/print",
    ):
        allowed = request.query_params.get("printer_id") in printers
        destination = request.query_params.get("destination_id")
        if destination and destination not in destinations:
            allowed = False
    if path in (
        "/api/printers/{identifier}",
        "/api/printers/{identifier}/stop",
        "/api/printers/{identifier}/cartridge-check",
    ):
        allowed = request.path_params.get("identifier") in printers and method in (
            "GET",
            "PUT",
            "POST",
        )
    if method == "GET" and path == "/api/queue/groups":
        allowed = request.query_params.get("destination_id") in destinations
    if method == "GET" and path == "/api/batches/page":
        allowed = request.query_params.get("printer_id") in printers
    if method == "GET" and path in (
        "/api/batches/{identifier}",
        "/api/batches/{identifier}/items/{copy_id}/preview",
    ):
        batch = session.get(Batch, request.path_params.get("identifier"))
        allowed = batch is not None and batch.printer_id in printers
    if method == "GET" and path in ("/api/jobs/{identifier}", "/api/jobs/{identifier}/preview"):
        job = session.get(PrintJob, request.path_params.get("identifier"))
        allowed = job is not None and bool(
            printers.intersection(request.app.state.fleet._candidates(session, job))
        )
    if not allowed:
        raise HTTPException(403, "This operation is not available through a companion")
    # Preserve the real user's granted capabilities, while removing the blanket
    # administrator bypass and every destination outside this installation.
    scoped = replace(
        actor,
        is_admin=False,
        printer_ids=actor.printer_ids & printers,
        destination_levels={
            key: value for key, value in actor.destination_levels.items() if key in destinations
        },
        destination_permissions={
            key: value
            for key, value in actor.destination_permissions.items()
            if key in destinations
        },
    )
    return AccessContext(scoped, AccountPolicy(dict.fromkeys(destinations)))
