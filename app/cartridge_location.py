"""An installation may move inventory only after a scoped access-impact preview."""

import secrets
import time
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.admin_api import state_hash
from app.auth import token_hash
from app.models import AccessChangeConfirmation, Cartridge, Location, PrinterDevice
from app.resource_api import (
    ResourceChange,
    access_snapshot,
    apply_resource_change,
    mutate_with_evidence,
    rights_for,
)


def installation_location(
    session: Session,
    request: Request,
    printer_id: str,
    cartridge: Cartridge,
    move: bool | None,
    confirmation: str | None,
) -> dict[str, Any] | None:
    device = session.get(PrinterDevice, printer_id)
    assert device is not None
    if move is False or cartridge.location_id == device.location_id:
        return None
    rights = rights_for(request, session)
    fingerprint = token_hash(f"installation:{printer_id}:{cartridge.id}:{device.location_id}")
    state = state_hash(session)
    change = ResourceChange(
        kind="cartridge", identifier=cartridge.id, location_id=device.location_id
    )
    receipt = session.get(AccessChangeConfirmation, token_hash(confirmation or ""))
    if (
        move is True
        and receipt is not None
        and (
            receipt.actor_id == rights.user_id
            and receipt.request_hash == fingerprint
            and receipt.state_hash == state
            and receipt.expires_at > time.time()
        )
    ):
        mutate_with_evidence(session, request, rights, change, installation_printer=printer_id)
        session.delete(receipt)
        return None
    resources = {("cartridge", cartridge.id)}
    before = access_snapshot(session, resources)
    with session.begin_nested() as savepoint:
        apply_resource_change(session, rights, change, installation_printer=printer_id)
        after = access_snapshot(session, resources)
        savepoint.rollback()
    target = session.get(Location, device.location_id) if device.location_id else None
    token = secrets.token_urlsafe(32)
    session.add(
        AccessChangeConfirmation(
            token_hash=token_hash(token),
            actor_id=rights.user_id,
            request_hash=fingerprint,
            state_hash=state,
            expires_at=time.time() + 600,
        )
    )
    return {
        "code": "cartridge_location",
        "confirmation": token,
        "message": f"Move {cartridge.name}'s recorded location to {target.name if target else 'Unassigned'}?",
        "affected_users": [
            {
                "id": user,
                "name": after[user]["name"],
                "before": before[user]["resources"],
                "after": after[user]["resources"],
            }
            for user in after
            if before[user] != after[user]
        ],
        "owner_loss_warning": any(
            "cartridge.approve_use" in after[user]["resources"][f"cartridge:{cartridge.id}"]
            and "cartridge.approve_use"
            not in before[user]["resources"][f"cartridge:{cartridge.id}"]
            for user in after
        ),
    }
