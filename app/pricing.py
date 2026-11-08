"""Requester price consent and per-submission allowances, independent of adapters."""

import hashlib
import json
import time
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Sequence

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.access import access_context
from app.models import Cartridge, LabelCopy, PriceQuote, PrintJob, State, UnitCharge
from app.printer.base import LabelGeometry, PrinterBackend


def geometry_key(destination: str, profile: str, labels: Sequence[LabelGeometry]) -> str:
    geometry = [
        {key: value for key, value in asdict(label).items() if key != "copy_id"} for label in labels
    ]
    return hashlib.sha256(
        json.dumps([destination, profile, geometry], sort_keys=True).encode()
    ).hexdigest()


def job_geometry(job: PrintJob, copies: int | None = None) -> list[LabelGeometry]:
    spec = job.template_snapshot.get("render_spec", {})
    return [
        LabelGeometry(
            str(index),
            job.width_mm,
            job.length_mm,
            spec.get("dpi_x") or spec.get("dpi", 180),
            spec.get("dpi", 180),
            job.template_snapshot.get("template_padding_mm", 0),
        )
        for index in range(job.copies if copies is None else copies)
    ]


def save_quote(
    request: Request,
    session: Session,
    destination: str,
    profile: str,
    labels: Sequence[LabelGeometry],
    estimate: dict[str, Any],
) -> str:
    session.execute(delete(PriceQuote).where(PriceQuote.expires_at < time.time()))
    quote = PriceQuote(
        user_id=access_context(request).actor.id,
        geometry_key=geometry_key(destination, profile, labels),
        quotes=estimate["quotes"],
        expires_at=time.time() + 3600,
    )
    session.add(quote)
    session.flush()
    return quote.id


def accept_quote(
    request: Request,
    session: Session,
    job: PrintJob,
    quote_id: str | None,
    maximum: dict[str, Any] | None = None,
) -> None:
    if not quote_id:
        if maximum is not None:
            raise HTTPException(422, "Refresh the price quote before setting a maximum")
        return
    quote = session.get(PriceQuote, quote_id)
    if (
        not quote
        or quote.user_id != access_context(request).actor.id
        or quote.expires_at < time.time()
        or quote.geometry_key != geometry_key(job.destination_id, job.profile_id, job_geometry(job))
    ):
        raise HTTPException(
            409, "Price quote expired or label quantities changed; refresh the preview"
        )
    quotes = {row["currency"]: int(Decimal(row["maximum"]) * 1000000) for row in quote.quotes}
    if maximum is not None and maximum["currency"] not in quotes:
        raise HTTPException(422, "Choose a currency with an available price quote")
    job.template_snapshot = {
        **job.template_snapshot,
        "pricing": {
            "quote_id": quote.id,
            "quotes": quotes,
            "copies": job.copies,
            "maximum": maximum,
        },
    }


def remaining_allowance(
    session: Session,
    job: PrintJob,
    currency: str,
    *,
    override: bool = False,
    exclude_batch: str | None = None,
) -> int | None:
    pricing = job.template_snapshot.get("pricing", {})
    maximum = pricing.get("maximum")
    cap = int(maximum["micros"]) if maximum and maximum["currency"] == currency else None
    if maximum and maximum["currency"] != currency:
        return -1
    if override:
        quote = pricing.get("quotes", {}).get(currency)
        if quote is None:
            return -1
        cap = min(cap, int(quote)) if cap is not None else int(quote)
    if cap is None:
        return None
    rows = session.scalars(select(UnitCharge).where(UnitCharge.job_id == job.id))
    used = sum(
        int(row.charged_micros if row.charged_micros is not None else row.reserved_micros or "0")
        for row in rows
        if row.batch_id != exclude_batch and row.currency == currency
    )
    return max(0, cap - used)


def affordable(
    session: Session, job: PrintJob, cartridge: Cartridge, backend: PrinterBackend
) -> bool:
    if job.template_snapshot.get("retry", {}).get("mode") == "free":
        from app.retry_funding import retry_authorization

        return retry_authorization(session, job, cartridge) is not None
    allowance = remaining_allowance(session, job, cartridge.currency)
    if allowance is None:
        return True
    if allowance < 0 or cartridge.price_minor is None:
        return False
    from app.usage import cost_micros

    count = (
        session.scalar(
            select(func.count())
            .select_from(LabelCopy)
            .where(LabelCopy.job_id == job.id, LabelCopy.state == State.QUEUED)
        )
        or 0
    )
    if not count:
        return True
    estimate = backend.plan_batch(job_geometry(job, count)).estimated_mm
    return cost_micros(estimate, cartridge.price_minor, cartridge.nominal_length_mm) <= allowance


def check_affordable_inventory(
    session: Session, job: PrintJob, backends: Sequence[PrinterBackend]
) -> None:
    """One notification per unaffordable episode, including stored eligible cartridges."""
    pricing = job.template_snapshot.get("pricing", {})
    if not pricing.get("maximum"):
        return
    from app.cartridge_access import can_use_cartridge

    available = any(
        can_use_cartridge(session, job, cartridge)
        and any(affordable(session, job, cartridge, backend) for backend in backends)
        for cartridge in session.scalars(
            select(Cartridge).where(
                Cartridge.profile_id == job.profile_id,
                Cartridge.archived.is_(False),
                Cartridge.remaining_mm > 0,
            )
        )
    )
    waiting = not available
    if bool(pricing.get("unaffordable")) == waiting:
        return
    job.template_snapshot = {
        **job.template_snapshot,
        "pricing": {**pricing, "unaffordable": waiting},
    }
    if waiting:
        from app.notifications import enqueue

        enqueue(
            session,
            "No cartridge meets your maximum",
            "Your labels are waiting for an eligible cartridge within your price limit.",
            "/#/jobs",
            recipient_id=job.owner_id,
            context={"job_id": job.id},
        )
