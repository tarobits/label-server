from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from mock_backend import MockPrinterBackend
from pydantic import Field
from sqlalchemy.orm import Session

from app.destinations import resolve_destination
from app.http import db
from app.schemas import Input


class MockPrinterInput(Input):
    connected: bool = True
    tape_width_mm: float | None = Field(default=24, ge=1, le=100)
    fail_after: int | None = Field(default=None, ge=0, le=1000)


router = APIRouter(prefix="/api")


def mock_backend(request: Request, printer_id: str | None = None) -> MockPrinterBackend:
    with request.app.state.factory() as session:
        printer_id = resolve_destination(session, printer_id)
    if printer_id not in request.app.state.fleet.workers:
        raise HTTPException(404, "Printer not found")
    backend = request.app.state.fleet.workers[printer_id].backend
    if not isinstance(backend, MockPrinterBackend):
        raise HTTPException(404, "Mock controls are unavailable for this printer")
    return backend


@router.get("/printer/mock")
def mock_settings(request: Request, printer_id: str | None = None) -> dict[str, Any]:
    with request.app.state.factory() as lookup:
        printer_id = resolve_destination(lookup, printer_id)
    backend = mock_backend(request, printer_id)
    return {
        "connected": backend.connected,
        "tape_width_mm": backend.width_mm,
        "fail_after": backend.fail_after,
    }


@router.put("/printer/mock")
def set_mock_settings(
    body: MockPrinterInput,
    request: Request,
    session: Session = Depends(db, scope="function"),
    printer_id: str | None = None,
) -> dict[str, Any]:
    with request.app.state.factory() as lookup:
        printer_id = resolve_destination(lookup, printer_id)
    backend = mock_backend(request, printer_id)
    worker = request.app.state.fleet.workers[printer_id]
    # Nonblocking acquisition avoids reversing the worker's printer/database lock order.
    if not worker.printer_lock.acquire(blocking=False):
        raise HTTPException(409, "Printer is busy; try again after this batch")
    try:
        backend.connected = body.connected
        backend.width_mm = body.tape_width_mm
        backend.fail_after = body.fail_after
        worker.latest_status = backend.get_status()
    finally:
        worker.printer_lock.release()
    return mock_settings(request, printer_id)
