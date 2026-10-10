"""Generic destination membership, state and routing rules; no device protocols."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, Cartridge, PrinterDevice, PrinterGroup, PrinterState, State


def resolve_destination(session: Session, identifier: str | None) -> str:
    if identifier is not None:
        members(session, identifier)
        return identifier
    identifiers = [
        p.id for p in session.scalars(select(PrinterDevice)) if not p.config.get("retired")
    ]
    if not identifiers:
        raise HTTPException(409, "Add a printer in Printers & groups first")
    if len(identifiers) != 1:
        raise HTTPException(422, "Select a print destination")
    return identifiers[0]


def printer_state(session: Session, printer_id: str) -> PrinterState:
    state = session.scalar(select(PrinterState).where(PrinterState.printer_id == printer_id))
    if state is None:
        raise HTTPException(404, "Printer not found")
    return state


def members(session: Session, destination_id: str) -> list[str]:
    if device := session.get(PrinterDevice, destination_id):
        if device.config.get("retired"):
            raise HTTPException(409, "This printer has been retired; select a configured printer")
        return [destination_id]
    group = session.get(PrinterGroup, destination_id)
    if group:
        return group.printer_ids
    raise HTTPException(404, "Print destination not found")


def installed_profile(session: Session, printer_id: str) -> str | None:
    state = printer_state(session, printer_id)
    cartridge = (
        session.get(Cartridge, state.active_cartridge_id) if state.active_cartridge_id else None
    )
    return cartridge.profile_id if cartridge else None


def busy(session: Session, printer_id: str) -> bool:
    return (
        session.scalar(
            select(Batch.id)
            .where(
                Batch.printer_id == printer_id,
                Batch.state.in_([State.PRINTING, State.NEEDS_REVIEW]),
            )
            .limit(1)
        )
        is not None
    )
