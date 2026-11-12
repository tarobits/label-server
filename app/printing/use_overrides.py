"""Explicit, selected-copy cartridge consent and its durable dispatch receipt."""

import hashlib
import json
from typing import Any, Sequence

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.pricing import job_geometry, remaining_allowance
from app.accounts.usage import cost_micros, money
from app.authn.access import access_context
from app.authn.auth import actor_for_user
from app.models import Cartridge, FlushRequest, LabelCopy, PrintJob, User
from app.schemas import CopySelectionInput


def confirm_use(
    request: Request,
    session: Session,
    printer_id: str,
    cartridge: Cartridge,
    copies: Sequence[LabelCopy],
    blocked: set[str],
    body: CopySelectionInput | None,
) -> dict[str, Any]:
    if not blocked:
        if body and body.approve_copy_ids:
            raise HTTPException(409, "Cartridge permissions changed; refresh the print selection")
        return {}
    context = access_context(request)
    if not context.can_cartridge(cartridge.id, "approve_use"):
        raise HTTPException(409, "The queued requesters may not use the installed cartridge")
    backend = request.app.state.registry.backend(printer_id)
    missing: set[str] = set()
    for label in copies:
        if label.id not in blocked:
            continue
        job = session.get(PrintJob, label.job_id)
        assert job is not None
        cap = remaining_allowance(session, job, cartridge.currency, override=True)
        if cartridge.price_minor is None:
            raise HTTPException(
                409, "Set a price for this cartridge before requesting price approval"
            )
        if cap is None or cap < 0:
            missing.add(job.id)
    if missing:
        raise HTTPException(
            409,
            {
                "code": "cartridge_quote_required",
                "printer_id": printer_id,
                "cartridge_id": cartridge.id,
                "job_ids": sorted(missing),
                "message": "Some requesters have no saved price in this cartridge's currency. Ask them to approve a quote for their remaining copies before printing.",
            },
        )
    rows: list[dict[str, Any]] = []
    for label in copies:
        if label.id not in blocked:
            continue
        job = session.get(PrintJob, label.job_id)
        assert job is not None
        cap = remaining_allowance(session, job, cartridge.currency, override=True)
        if cartridge.price_minor is None or cap is None or cap < 0:
            raise HTTPException(
                409,
                "These copies need requester acceptance of a price quote in the cartridge's currency",
            )
        estimate = cost_micros(
            backend.plan_batch(job_geometry(job, 1)).estimated_mm,
            cartridge.price_minor,
            cartridge.nominal_length_mm,
        )
        requester = session.get(User, job.owner_id)
        rows.append(
            {
                "copy_id": label.id,
                "job_id": job.id,
                "requester": requester.username if requester else job.owner_id,
                "ordinal": label.ordinal + 1,
                "actual": money(estimate),
                "maximum_charge": money(min(estimate, cap)),
                "currency": cartridge.currency,
                "preview": f"/api/jobs/{job.id}/preview"
                if job.owner_id == context.actor.id
                or context.can_printer(job.destination_id, "view_queue")
                else None,
            }
        )
    confirmations = {
        row["copy_id"]: hashlib.sha256(
            json.dumps(
                {
                    "actor": context.actor.id,
                    "printer": printer_id,
                    "cartridge": cartridge.id,
                    "owner": cartridge.owner_id,
                    "price": cartridge.price_minor,
                    "length": cartridge.nominal_length_mm,
                    "row": row,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        for row in rows
    }
    approved = set(body.approve_copy_ids) if body else set()
    if (
        approved != blocked
        or not body
        or any(
            body.use_confirmations.get(identifier) != value
            for identifier, value in confirmations.items()
        )
    ):
        raise HTTPException(
            409,
            {
                "code": "cartridge_use",
                "confirmations": confirmations,
                "items": rows,
                "copy_ids": [copy.id for copy in copies],
                "message": "The cartridge owner covers any difference above the saved quote. Each quote allowance is shared across the label's copies.",
            },
        )
    return {
        identifier: {
            "actor_id": context.actor.id,
            "actor_name": context.actor.username,
            "cartridge_id": cartridge.id,
            "kind": "use_override",
        }
        for identifier in approved
    }


def authorization_valid(session: Session, authorization: Any, cartridge: Cartridge) -> bool:
    if not isinstance(authorization, dict) or authorization.get("cartridge_id") != cartridge.id:
        return False
    user = session.get(User, authorization.get("actor_id"))
    if user is None or user.disabled:
        return False
    actor = actor_for_user(session, user)
    return actor.is_admin or "cartridge.approve_use" in actor.cartridge_permissions.get(
        cartridge.id, ()
    )


def pending_authorization(
    session: Session, job: PrintJob, cartridge: Cartridge, copy_id: str | None = None
) -> dict[str, Any] | None:
    query = select(FlushRequest).where(
        FlushRequest.cartridge_id == cartridge.id, FlushRequest.completed.is_(False)
    )
    ids = (
        {copy_id}
        if copy_id
        else set(session.scalars(select(LabelCopy.id).where(LabelCopy.job_id == job.id)))
    )
    for flush in session.scalars(query):
        for identifier in ids:
            authorization = (flush.use_authorizations or {}).get(identifier)
            if not authorization:
                continue
            if authorization_valid(session, authorization, cartridge):
                return dict(authorization)
    return None
