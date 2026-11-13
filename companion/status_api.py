"""Explicitly allowlisted, read-only operational data for external station displays."""

import hmac
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.i18n import Message
from companion.agent import Agent
from companion.config import LocalPrinter, Settings


class CartridgeStatus(BaseModel):
    name: str
    profile_name: str | None = None
    foreground: str | None = None
    background: str | None = None
    width_mm: float | None = None
    remaining_mm: float
    nominal_length_mm: float
    uncertain: bool


PrinterOperationalState = Literal[
    "unknown",
    "disconnected",
    "error",
    "printing",
    "held",
    "awaiting_cartridge_confirmation",
    "ready",
]


class PrinterSummary(BaseModel):
    local_id: str
    name: str
    status: PrinterOperationalState
    connected: bool | None
    printing: bool
    blocked: bool
    held: bool | None
    cartridge_check_pending: bool | None
    queued_labels: int | None
    shared_queued_labels: int | None
    cartridge: CartridgeStatus | None
    snapshot_age_seconds: float | None
    stale: bool


class StationStatus(BaseModel):
    schema_version: Literal[1] = 1
    name: str
    online: bool
    printers: list[PrinterSummary]


def status_router(settings: Settings, agent: Agent) -> APIRouter:
    bearer = HTTPBearer(auto_error=False, scheme_name="CompanionStatusKey")

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
        expected = settings.status_api_key.get_secret_value()
        if not expected:
            raise HTTPException(404, Message("serverMessages.statusAPIIsDisabled"))
        if credentials is None or not hmac.compare_digest(
            credentials.credentials.encode(), expected.encode()
        ):
            raise HTTPException(
                401,
                Message("serverMessages.invalidStatusAPIKey"),
                headers={"WWW-Authenticate": "Bearer"},
            )

    router = APIRouter(prefix="/api/status", dependencies=[Depends(authorize)])

    def summary(device: LocalPrinter) -> PrinterSummary:
        identifier = device.local_id
        hardware = agent.statuses.get(identifier, {})
        dashboard = agent.dashboards.get(identifier)
        received = agent.dashboard_received.get(identifier)
        age = max(0.0, time.monotonic() - received) if received is not None else None
        stale = not agent.online or age is None or age > 30
        thread = agent.threads.get(identifier)
        printing = bool(thread and thread.is_alive())
        blocked = agent.journal.blocked(identifier) or agent.server_blocked.get(identifier, False)
        connected = bool(hardware.get("connected")) if hardware and not stale else None
        held = bool(dashboard.get("held")) if dashboard is not None else None
        pending = bool(dashboard.get("cartridge_check_pending")) if dashboard is not None else None
        status: PrinterOperationalState
        if blocked:
            status = "error"
        elif printing:
            status = "printing"
        elif connected is None:
            status = "unknown"
        elif not connected:
            status = "disconnected"
        elif pending:
            status = "awaiting_cartridge_confirmation"
        elif hardware.get("error"):
            status = "error"
        elif held:
            status = "held"
        else:
            status = "ready"
        stock = dashboard.get("cartridge") if dashboard else None
        return PrinterSummary(
            local_id=identifier,
            name=agent.names.get(identifier, device.name),
            status=status,
            connected=connected,
            printing=printing,
            blocked=blocked,
            held=held,
            cartridge_check_pending=pending,
            queued_labels=dashboard.get("queued_labels") if dashboard is not None else None,
            shared_queued_labels=dashboard.get("shared_queued_labels")
            if dashboard is not None
            else None,
            cartridge=CartridgeStatus.model_validate(stock) if stock else None,
            snapshot_age_seconds=age,
            stale=stale,
        )

    def snapshot(devices: list[LocalPrinter]) -> StationStatus:
        return StationStatus(
            name=agent.users.get("name", "Companion"),
            online=agent.online,
            printers=[summary(device) for device in devices],
        )

    @router.get("", response_model=StationStatus)
    def all_printers() -> StationStatus:
        return snapshot(agent.devices)

    @router.get("/printers/{local_id}", response_model=StationStatus)
    def one_printer(local_id: str) -> StationStatus:
        device = next((device for device in agent.devices if device.local_id == local_id), None)
        if device is None:
            raise HTTPException(404, Message("serverMessages.printerNotFound"))
        return snapshot([device])

    return router
