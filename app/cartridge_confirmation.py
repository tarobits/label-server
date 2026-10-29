"""Cartridge selection and explicit acceptance of adapter-reported mismatches."""

import hashlib
import json
import time
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.access import access_context
from app.models import Cartridge, PrinterState, TapeProfile
from app.print_audit import actor_snapshot
from app.printer.base import ConfirmableMediaBackend, MediaSelection, PrinterBackend, PrinterStatus


def profile_signature(profile: TapeProfile) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                profile.id,
                profile.width_mm,
                profile.foreground,
                profile.background,
            ]
        ).encode()
    ).hexdigest()


def configure_media(backend: PrinterBackend, session: Session, state: PrinterState) -> None:
    if not isinstance(backend, ConfirmableMediaBackend):
        return
    cartridge = (
        session.get(Cartridge, state.active_cartridge_id) if state.active_cartridge_id else None
    )
    profile = session.get(TapeProfile, cartridge.profile_id) if cartridge else None
    if not profile:
        backend.configure_media(None)
        return
    saved = state.media_confirmation or {}
    accepted = saved.get("cartridge_id") == state.active_cartridge_id and saved.get(
        "profile_signature"
    ) == profile_signature(profile)
    backend.configure_media(
        MediaSelection(
            profile.width_mm,
            saved.get("fingerprint") if accepted else None,
            state.media_verified_fingerprint,
            state.cartridge_check_enabled,
            state.cartridge_check_pending,
        )
    )


def media_mismatch(hardware: PrinterStatus, profile: TapeProfile) -> str | None:
    media = hardware.media
    if not hardware.connected or not media or not media.confirmable:
        return None
    problems = []
    if media.problem:
        problems.append(media.problem)
    if media.width_mm != profile.width_mm:
        detected = f"{media.width_mm:g} mm" if media.width_mm else "unknown"
        problems.append(f"Selected width: {profile.width_mm:g} mm; detected width: {detected}.")
    return "\n".join(problems) or None


def check_cartridge(
    request: Request,
    session: Session,
    state: PrinterState,
    cartridge: Cartridge,
    confirmation: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    worker = request.app.state.fleet.workers.get(state.printer_id)
    if not worker or not isinstance(worker.backend, ConfirmableMediaBackend):
        return None, None
    if not worker.printer_lock.acquire(blocking=False):
        raise HTTPException(409, "Printer is busy; try again when it is idle")
    request.state.held_locks.append(worker.printer_lock)
    configure_media(worker.backend, session, state)
    hardware = worker.backend.get_status()
    worker.latest_status = hardware
    profile = session.get(TapeProfile, cartridge.profile_id)
    assert profile is not None
    capabilities = request.app.state.registry.definition(state.printer_id).capabilities
    if profile.width_mm not in capabilities.supported_widths_mm:
        raise HTTPException(422, "The selected cartridge width is not supported by this printer")
    mismatch = media_mismatch(hardware, profile)
    if (
        state.cartridge_check_enabled
        and hardware.media_changed
        and (not hardware.media or not hardware.media.confirmable)
    ):
        raise HTTPException(
            409,
            hardware.error
            or "Close the printer and resolve hardware errors before confirming the cartridge",
        )
    if not hardware.media or not hardware.media.confirmable:
        return None, None
    verification = hardware.media.verification_key
    needs_check = state.cartridge_check_enabled and hardware.media_changed
    if not mismatch and not needs_check:
        return None, verification
    fingerprint = hardware.media.fingerprint
    signature = profile_signature(profile)
    token = hashlib.sha256(
        json.dumps(
            [
                state.printer_id,
                cartridge.id,
                signature,
                fingerprint,
                verification,
            ]
        ).encode()
    ).hexdigest()
    saved = state.media_confirmation or {}
    if (
        state.active_cartridge_id == cartridge.id
        and hardware.media_confirmed
        and not needs_check
        and saved.get("profile_signature") == signature
    ):
        return saved, verification
    if confirmation != token:
        raise HTTPException(
            409,
            {
                "code": "cartridge_mismatch",
                "message": (
                    (
                        "The printer was opened or its tape changed. Is this still the correct cartridge?\n\n"
                        if needs_check
                        else "Is this the correct cartridge?\n\n"
                    )
                    + f"Printer: {request.app.state.registry.definition(state.printer_id).name}\n"
                    + f"Selected: {cartridge.name} · {profile.name} · {profile.width_mm:g} mm\n"
                    f"Detected: {hardware.media.description}\n\n"
                    + (f"{mismatch}\n\n" if mismatch else "")
                    + "Confirming uses the selected cartridge width for printing. "
                    "Eligible queued labels may print."
                ),
                "confirmation": token,
            },
        )
    accepted = (
        {
            "cartridge_id": cartridge.id,
            "profile_signature": signature,
            "fingerprint": fingerprint,
            "confirmed_by": actor_snapshot(access_context(request).actor),
            "confirmed_at": time.time(),
        }
        if mismatch
        else None
    )
    return accepted, verification
