"""Non-binding cartridge price estimates for user-visible print plans."""

from typing import Any, Sequence

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import access_context
from app.destinations import members
from app.models import Cartridge, PrinterState
from app.printer.base import LabelGeometry
from app.usage import cost_micros, money


def estimate_cost(
    request: Request,
    session: Session,
    destination_id: str | None,
    profile_id: str,
    labels: Sequence[LabelGeometry],
) -> dict[str, Any]:
    """Quote all copies as one batch, without reserving tape or fixing a future price.

    Prefer matching installed cartridges. When none are installed, known inventory
    gives a labelled fallback. Group destinations may produce a range or currencies.
    Never expose identities of physical members hidden behind group permissions.
    """
    result: dict[str, Any] = {
        "quotes": [],
        "basis": "installed",
        "incomplete": False,
        "reason": None,
    }
    if not destination_id or not access_context(request).can_destination(destination_id):
        return {**result, "reason": "destination"}
    try:
        identifiers = members(session, destination_id)
    except HTTPException:
        return {**result, "reason": "destination"}
    fleet = request.app.state.fleet
    registry = request.app.state.registry
    plans = {
        identifier: registry.backend(identifier).plan_batch(labels)
        for identifier in identifiers
        if identifier in fleet.workers
    }
    if not plans:
        return {**result, "reason": "destination"}
    candidates = []
    for state in session.scalars(select(PrinterState).where(PrinterState.printer_id.in_(plans))):
        cartridge = (
            session.get(Cartridge, state.active_cartridge_id) if state.active_cartridge_id else None
        )
        if cartridge and not cartridge.archived and cartridge.profile_id == profile_id:
            candidates.append((plans[state.printer_id], cartridge))
    if not candidates:
        result["basis"] = "inventory"
        inventory = list(
            session.scalars(
                select(Cartridge).where(
                    Cartridge.profile_id == profile_id,
                    Cartridge.remaining_mm > 0,
                    Cartridge.archived.is_(False),
                )
            )
        )
        candidates = [(plan, cartridge) for plan in plans.values() for cartridge in inventory]
    if not candidates:
        return {**result, "reason": "cartridge"}
    amounts: dict[str, list[int]] = {}
    for plan, cartridge in candidates:
        if cartridge.price_minor is None:
            result["incomplete"] = True
            continue
        amounts.setdefault(cartridge.currency, []).append(
            cost_micros(plan.estimated_mm, cartridge.price_minor, cartridge.nominal_length_mm)
        )
    result["quotes"] = [
        {"currency": currency, "minimum": money(min(values)), "maximum": money(max(values))}
        for currency, values in sorted(amounts.items())
    ]
    if not amounts:
        result["reason"] = "price"
    return result
