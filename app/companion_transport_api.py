"""Outbound polling, complete-batch receipts, durable go, and idempotent results."""

import hmac
import secrets
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from app.action_audit import record_action
from app.companion_auth import DeviceDB, operator
from app.companion_dashboard import printer_dashboard
from app.companion_protocol import BatchReceipt, ExecutionResult
from app.models import (
    Batch,
    BatchItem,
    Cartridge,
    Companion,
    CompanionBatch,
    CompanionPrinter,
    LabelCopy,
    PrinterDevice,
    PrinterState,
    PrintJob,
    State,
)
from app.printer.factory import DeviceConfiguration
from app.printer.remote import RemotePrinterBackend
from app.schemas import Input

router = APIRouter(prefix="/api/companion", tags=["companion transport"])


class LocalStopEvent(Input):
    id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    occurred_at: float = Field(ge=0)
    printer_id: str = Field(min_length=1, max_length=100)
    mode: Literal["after_current", "emergency"]
    user_id: str | None = Field(default=None, max_length=100)
    offline: bool
    locked: bool


@router.post("/events/stop")
def local_stop_event(body: LocalStopEvent, session: DeviceDB) -> dict[str, bool]:
    from app.audit import AuditField, AuditRequirement, AuditScope, append_audit

    link = owned_printer(session, body.printer_id)
    guard = (AuditRequirement("printer", body.printer_id, "printer.view"),)
    try:
        append_audit(
            session,
            event_id=f"{link.companion_id}:{body.id}",
            action="companion.local_stop_requested",
            outcome="succeeded",
            occurred_at=body.occurred_at,
            scopes=(AuditScope("printer", body.printer_id),),
            fields={
                "actor_id": AuditField(body.user_id, ()),
                "source": AuditField("companion", ()),
                "mode": AuditField(body.mode, guard),
                "offline": AuditField(body.offline, guard),
                "locked": AuditField(body.locked, guard),
            },
        )
    except ValueError as error:
        raise HTTPException(409, "Local event identity has conflicting evidence") from error
    return {"ok": True}


class Registration(Input):
    local_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    driver: str = Field(min_length=1, max_length=100)
    configuration: DeviceConfiguration = Field(default_factory=DeviceConfiguration)


def require_management(request: Request, session: DeviceDB) -> None:
    from app.auth import actor_for_user

    actor = actor_for_user(session, operator(request, session))
    if not actor.is_admin and "printers.manage" not in actor.permissions:
        raise HTTPException(403, "Printer management permission is required")
    session.info["companion_operator"] = actor


class MediaStatus(Input):
    width_mm: float | None = Field(default=None, gt=0, le=1000)
    description: str = Field(max_length=500)
    fingerprint: str = Field(max_length=500)
    problem: str | None = Field(default=None, max_length=500)
    confirmable: bool = True
    verification_key: str | None = Field(default=None, max_length=500)


class DeviceStatus(Input):
    local_blocked: bool = False
    clearance_seen: int = Field(default=0, ge=0)
    connected: bool
    tape_width_mm: float | None = Field(default=None, gt=0, le=1000)
    error: str | None = Field(default=None, max_length=500)
    error_requires_investigation: bool = True
    media: MediaStatus | None = None
    media_confirmed: bool = False
    media_changed: bool = False
    diagnostics: dict[str, str] | None = None


def owned_printer(session: DeviceDB, identifier: str) -> CompanionPrinter:
    item: Companion = session.info["companion"]
    link = session.get(CompanionPrinter, identifier)
    if link is None or link.companion_id != item.id:
        raise HTTPException(404, "Companion printer not found")
    return link


def owned_batch(session: DeviceDB, identifier: str) -> CompanionBatch:
    item: Companion = session.info["companion"]
    batch = session.get(CompanionBatch, identifier)
    if batch is None or batch.companion_id != item.id:
        raise HTTPException(404, "Companion batch not found")
    return batch


@router.post("/printers", status_code=201)
def register(body: Registration, request: Request, session: DeviceDB) -> dict[str, Any]:
    if request.headers.get("x-companion-session"):
        require_management(request, session)
    item: Companion = session.info["companion"]
    existing = session.scalar(
        select(CompanionPrinter).where(
            CompanionPrinter.companion_id == item.id, CompanionPrinter.local_id == body.local_id
        )
    )
    if existing:
        return {"printer_id": existing.printer_id, "enabled": existing.enabled}
    configuration = body.configuration.model_dump()
    try:
        request.app.state.fleet.backend_factory(body.driver, configuration)
    except ValueError as error:
        raise HTTPException(422, "Unsupported printer configuration") from error
    device = PrinterDevice(
        name=body.name, driver=body.driver, config=configuration, location_id=item.location_id
    )
    session.add(device)
    session.flush()
    session.add(PrinterState(printer_id=device.id))
    session.add(
        CompanionPrinter(printer_id=device.id, companion_id=item.id, local_id=body.local_id)
    )
    session.flush()
    from app.fleet_api import validate_device
    from app.schemas import PrinterInput

    validate_device(
        PrinterInput(name=body.name, driver=body.driver, **configuration), session, device.id
    )
    record_action(
        session,
        "companion.printer_registered",
        "printer",
        device.id,
        {"companion_id": item.id, "name": body.name},
    )
    # Registration is idempotent per installation/local identity and can never
    # claim an existing server printer or grant its ownership to a user.
    return {"printer_id": device.id, "enabled": True}


class PrinterEnabled(Input):
    enabled: bool


@router.put("/printers/{identifier}/enabled")
def enable_printer(
    identifier: str, body: PrinterEnabled, request: Request, session: DeviceDB
) -> dict[str, bool]:
    require_management(request, session)
    link = owned_printer(session, identifier)
    from app.queue import require_idle

    try:
        require_idle(session, identifier)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if body.enabled:
        from app.fleet_api import validate_device
        from app.schemas import PrinterInput

        device = session.get(PrinterDevice, identifier)
        assert device is not None
        if device.config.get("retired"):
            raise HTTPException(409, "This printer registration has been retired")
        validate_device(
            PrinterInput(name=device.name, driver=device.driver, **device.config),
            session,
            identifier,
        )
    if link.enabled != body.enabled:
        link.enabled = body.enabled
        link.last_seen_at = None
        record_action(
            session,
            "companion.printer_enabled_changed",
            "printer",
            identifier,
            {"enabled": body.enabled},
        )
    return {"enabled": link.enabled}


@router.put("/printers/{identifier}/status")
def heartbeat(
    identifier: str, body: DeviceStatus, request: Request, session: DeviceDB
) -> dict[str, Any]:
    link = owned_printer(session, identifier)
    device = session.get(PrinterDevice, identifier)
    if device and device.config.get("moved_to"):
        raise HTTPException(409, "Printer moved; restart the companion to refresh its registration")
    if body.diagnostics and (
        len(body.diagnostics) > 30
        or any(len(k) > 100 or len(v) > 500 for k, v in body.diagnostics.items())
    ):
        raise HTTPException(422, "Diagnostic values exceed limits")
    link.status, link.last_seen_at = (
        body.model_dump(exclude={"local_blocked", "clearance_seen"}),
        time.time(),
    )
    hardware_fault = bool(body.error and body.error_requires_investigation)
    local_block = body.local_blocked and body.clearance_seen >= link.clearance
    if (hardware_fault or local_block) and not link.blocked:
        link.blocked = True
        reasons = []
        if hardware_fault:
            reasons.append(f"Printer reported a fault: {body.error}")
        if local_block:
            reasons.append(
                "Companion reports an unresolved local print attempt requiring investigation"
            )
        record_action(
            session,
            "companion.printer_blocked",
            "printer",
            identifier,
            {
                "reason": "; ".join(reasons),
                "connected": body.connected,
                "local_blocked": local_block,
            },
        )
    backend = request.app.state.fleet.workers.get(identifier)
    selection = (
        backend.backend.media_configuration()
        if backend and isinstance(backend.backend, RemotePrinterBackend)
        else None
    )
    device = session.get(PrinterDevice, identifier)
    return {
        "enabled": link.enabled,
        "media_selection": selection,
        "dashboard": printer_dashboard(session, identifier),
        "blocked": link.blocked,
        "clearance": link.clearance,
        "configuration": device.config if device else {},
        "driver": device.driver if device else None,
        "name": device.name if device else None,
    }


@router.get("/work")
def work(session: DeviceDB) -> list[dict[str, Any]]:
    item: Companion = session.info["companion"]
    return [
        {"payload": row.payload, "digest": row.digest, "stop_mode": row.stop_mode}
        for row in session.scalars(
            select(CompanionBatch)
            .join(Batch)
            .where(
                CompanionBatch.companion_id == item.id,
                Batch.state == State.PRINTING,
            )
            .order_by(CompanionBatch.created_at)
        )
        if row.result is None
    ]


def authorized(session: DeviceDB, row: CompanionBatch) -> bool:
    from app.cartridge_access import can_use_cartridge
    from app.job_access import job_eligible
    from app.migration_gate import migration_pending
    from app.use_overrides import authorization_valid

    batch = session.get(Batch, row.batch_id)
    link = session.get(CompanionPrinter, row.printer_id)
    if (
        not batch
        or batch.state != State.PRINTING
        or migration_pending(session)
        or not link
        or not link.enabled
        or link.blocked
    ):
        return False
    if row.stop_mode or (batch.trigger or {}).get("stop_request"):
        return False
    cartridge = session.get(Cartridge, batch.cartridge_id)
    if not cartridge:
        return False
    for item in session.scalars(select(BatchItem).where(BatchItem.batch_id == batch.id)):
        copy = session.get(LabelCopy, item.copy_id)
        job = session.get(PrintJob, copy.job_id) if copy else None
        consent = (item.attribution or {}).get("cartridge_authorization")
        if not job or not job_eligible(session, job):
            return False
        if consent and not authorization_valid(session, consent, cartridge):
            return False
        if not consent and not can_use_cartridge(session, job, cartridge):
            return False
    return True


@router.post("/batches/{identifier}/ready")
def ready(identifier: str, body: BatchReceipt, session: DeviceDB) -> dict[str, Any]:
    row = owned_batch(session, identifier)
    if not hmac.compare_digest(row.digest, body.digest):
        raise HTTPException(409, "Batch receipt does not match")
    if row.result:
        return {"cancelled": True, "go_token": None}
    if not row.go_token:
        go_token = secrets.token_urlsafe(32)
        row.go_token = go_token
        if not authorized(session, row):
            row.result = ExecutionResult(
                digest=row.digest, go_token=go_token, outcome="not_started"
            ).model_dump()
            return {"cancelled": True, "go_token": None}
        record_action(
            session,
            "companion.batch_authorized",
            "printer",
            row.printer_id,
            {"batch_id": row.batch_id},
        )
    return {"cancelled": False, "go_token": row.go_token}


@router.post("/batches/{identifier}/result")
def result(identifier: str, body: ExecutionResult, session: DeviceDB) -> dict[str, bool]:
    row = owned_batch(session, identifier)
    if (
        not row.go_token
        or not hmac.compare_digest(row.go_token, body.go_token)
        or not hmac.compare_digest(row.digest, body.digest)
    ):
        raise HTTPException(409, "Batch authorization does not match")
    count = len(row.payload["labels"])
    if (
        body.confirmed_labels > count
        or body.outcome == "printed"
        and body.confirmed_labels != count
        or body.outcome == "not_started"
        and (body.confirmed_labels or body.consumed_mm)
    ):
        raise HTTPException(422, "Result does not match the batch")
    value = body.model_dump()
    if row.result is not None:
        if row.result != value:
            raise HTTPException(409, "This batch already has a different result")
        return {"ok": True}
    row.result = value
    details: dict[str, Any] = {
        "batch_id": row.batch_id,
        "state": body.outcome,
        "copy_count": body.confirmed_labels,
    }
    if body.outcome != "printed":
        details["reason"] = (
            "Companion rejected the batch before printing; printer investigation is required"
            if body.outcome == "not_started"
            else "Companion reported interrupted printing; unconfirmed output requires review"
        )
        link = owned_printer(session, row.printer_id)
        if not link.blocked:
            link.blocked = True
            record_action(session, "companion.printer_blocked", "printer", row.printer_id, details)
    record_action(
        session,
        "companion.result_received",
        "printer",
        row.printer_id,
        details,
    )
    return {"ok": True}
