"""Fresh requester consent for substitutions with no comparable saved price."""

import hashlib
import json
import time
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.pricing import job_geometry, remaining_allowance
from app.accounts.usage import cost_micros, money
from app.audit.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.authn.access import access_context
from app.authn.auth import actor_for_user
from app.http import db, get, job_information
from app.i18n import Message, request_language, translate
from app.models import (
    Cartridge,
    CartridgeQuoteOffer,
    LabelCopy,
    PrintJob,
    State,
    UnitCharge,
    User,
    new_id,
)
from app.notifications.notifications import enqueue
from app.printing.job_access import job_eligible
from app.schemas import Input, MaximumPrice
from app.transaction_routes import TransactionRouter

router = TransactionRouter(prefix="/api/cartridge-quotes", tags=["cartridge price consent"])
DB = Annotated[Session, Depends(db, scope="function")]


class Proposal(Input):
    printer_id: str = Field(min_length=1, max_length=100)
    cartridge_id: str = Field(min_length=1, max_length=100)
    job_ids: list[str] = Field(min_length=1, max_length=100)


class Acceptance(Input):
    quote_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    maximum_price: MaximumPrice


def receipt(request: Request, session: Session, offer: CartridgeQuoteOffer) -> dict[str, Any]:
    job = session.get(PrintJob, offer.job_id)
    cartridge = session.get(Cartridge, offer.cartridge_id)
    authorizer = session.get(User, offer.actor_id)
    if not job or not cartridge or cartridge.archived or not authorizer or authorizer.disabled:
        raise HTTPException(409, Message("printErrors.authorizationUnavailable"))
    actor = actor_for_user(session, authorizer)
    rights = actor.destination_permissions.get(offer.printer_id, ())
    start = "printer.start_own" if job.owner_id == actor.id else "printer.start_any"
    if not actor.is_admin and (
        not {start, "printer.start_any"}.intersection(rights)
        or "cartridge.approve_use" not in actor.cartridge_permissions.get(cartridge.id, ())
    ):
        raise HTTPException(409, Message("printErrors.operatorAuthorization"))
    if not job_eligible(session, job):
        raise HTTPException(409, Message("printErrors.resolveHold"))
    copies = list(
        session.scalars(
            select(LabelCopy).where(LabelCopy.job_id == job.id).order_by(LabelCopy.ordinal)
        )
    )
    if any(copy.state in (State.PRINTING, State.NEEDS_REVIEW) for copy in copies):
        raise HTTPException(409, Message("printErrors.activePrint"))
    queued = [copy.id for copy in copies if copy.state == State.QUEUED]
    if not queued or cartridge.profile_id != job.profile_id or cartridge.price_minor is None:
        raise HTTPException(409, Message("printErrors.pricedCartridge"))
    fleet = request.app.state.fleet
    if offer.printer_id not in fleet._candidates(session, job) or not fleet.supports_geometry(
        job, offer.printer_id
    ):
        raise HTTPException(409, Message("printErrors.unsupportedPrinter"))
    backend = request.app.state.registry.backend(offer.printer_id)
    plan = backend.plan_batch(job_geometry(job, len(queued)))
    amount = cost_micros(plan.estimated_mm, cartridge.price_minor, cartridge.nominal_length_mm)
    used = sum(
        int(row.charged_micros or row.reserved_micros or "0")
        for row in session.scalars(
            select(UnitCharge).where(
                UnitCharge.job_id == job.id, UnitCharge.currency == cartridge.currency
            )
        )
    )
    payload = {
        "job_id": job.id,
        "printer_id": offer.printer_id,
        "cartridge_id": cartridge.id,
        "owner_id": cartridge.owner_id,
        "copy_ids": queued,
        "currency": cartridge.currency,
        "price_minor": cartridge.price_minor,
        "nominal_length_mm": cartridge.nominal_length_mm,
        "estimated_mm": plan.estimated_mm,
        "amount_micros": amount,
        "used_micros": used,
        "previous_pricing": job.template_snapshot.get("pricing", {}),
    }
    payload["quote_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return payload


def evidence(
    request: Request,
    session: Session,
    offer: CartridgeQuoteOffer,
    action: str,
    maximum: dict[str, Any] | None = None,
) -> None:
    actor = access_context(request).actor
    guard = (AuditRequirement("printer", offer.printer_id, "printer.view_queue"),)
    account_guard = (AuditRequirement("application", "", "usage.view_others"),)
    fields = {
        "actor_id": AuditField(actor.id, ()),
        "actor_name": AuditField(actor.username, ()),
        "victim_ids": AuditField([offer.requester_id], guard),
        "offer_id": AuditField(offer.id, guard),
        "job_id": AuditField(offer.job_id, guard),
    }
    if maximum:
        fields.update(
            currency=AuditField(maximum["currency"], account_guard),
            maximum_micros=AuditField(maximum["micros"], account_guard),
        )
    append_audit(
        session,
        event_id=new_id(),
        action=action,
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(
            AuditScope("printer", offer.printer_id),
            AuditScope("cartridge", offer.cartridge_id),
        ),
        fields=fields,
    )


@router.post("", status_code=201)
def propose(body: Proposal, request: Request, session: DB) -> dict[str, Any]:
    context = access_context(request)
    context.require_cartridge(body.cartridge_id, "approve_use")
    cartridge = session.get(Cartridge, body.cartridge_id)
    if not cartridge:
        raise HTTPException(404, Message("printErrors.cartridgeNotFound"))
    offers = []
    for identifier in dict.fromkeys(body.job_ids):
        job = get(session, PrintJob, identifier)
        context.require_printer(
            body.printer_id,
            *(["start_own", "start_any"] if job.owner_id == context.actor.id else ["start_any"]),
        )
        requester = session.get(User, job.owner_id)
        if not requester or requester.disabled:
            raise HTTPException(409, Message("printErrors.requesterUnavailable"))
        cap = remaining_allowance(session, job, cartridge.currency, override=True)
        if cap is not None and cap >= 0:
            raise HTTPException(409, Message("printErrors.alreadyConsented"))
        offer = session.scalar(
            select(CartridgeQuoteOffer).where(
                CartridgeQuoteOffer.job_id == job.id,
                CartridgeQuoteOffer.printer_id == body.printer_id,
                CartridgeQuoteOffer.cartridge_id == cartridge.id,
                CartridgeQuoteOffer.actor_id == context.actor.id,
                CartridgeQuoteOffer.status == "pending",
            )
        )
        if offer is None:
            offer = CartridgeQuoteOffer(
                job_id=job.id,
                printer_id=body.printer_id,
                cartridge_id=cartridge.id,
                requester_id=job.owner_id,
                actor_id=context.actor.id,
            )
            session.add(offer)
            session.flush()
            receipt(request, session, offer)
            enqueue(
                session,
                Message("notificationMessages.priceApprovalTitle"),
                Message("notificationMessages.priceApprovalBody"),
                f"/#/cartridge-quotes/{offer.id}",
                recipient_id=job.owner_id,
                context={"job_id": job.id},
            )
            evidence(request, session, offer, "price.acceptance_requested")
        offers.append(offer.id)
    return {"offer_ids": offers}


def own_offer(request: Request, session: Session, identifier: str) -> CartridgeQuoteOffer:
    offer = session.get(CartridgeQuoteOffer, identifier)
    if not offer or offer.requester_id != access_context(request).actor.id:
        raise HTTPException(404, Message("printErrors.priceNotFound"))
    return offer


@router.get("/{identifier}")
def detail(identifier: str, request: Request, session: DB) -> dict[str, Any]:
    offer = own_offer(request, session, identifier)
    job = get(session, PrintJob, offer.job_id)
    quote, unavailable = None, None
    if offer.status == "pending":
        try:
            quote = receipt(request, session, offer)
        except HTTPException as error:
            unavailable = translate(error.detail, request_language(request))
    return {
        "id": offer.id,
        "status": offer.status,
        "unavailable": unavailable,
        "label": {
            **job_information(session, job),
            "job_id": job.id,
            "width_mm": job.width_mm,
            "length_mm": job.length_mm,
        },
        "quote": {
            "quote_hash": quote["quote_hash"],
            "copies": len(quote["copy_ids"]),
            "currency": quote["currency"],
            "maximum": money(quote["amount_micros"]),
            "amount_micros": quote["amount_micros"],
        }
        if quote
        else None,
    }


@router.post("/{identifier}/accept")
def accept(identifier: str, body: Acceptance, request: Request, session: DB) -> dict[str, str]:
    offer = own_offer(request, session, identifier)
    if offer.status == "accepted":
        if not offer.acceptance or offer.acceptance["request"] != body.model_dump():
            raise HTTPException(409, Message("printErrors.priceConsentChanged"))
        return {"status": offer.status}
    if offer.status != "pending":
        raise HTTPException(409, Message("printErrors.priceNotPending"))
    quote = receipt(request, session, offer)
    if quote["quote_hash"] != body.quote_hash:
        raise HTTPException(409, Message("printErrors.quoteChanged"))
    maximum = body.maximum_price.model_dump()
    if maximum["currency"] != quote["currency"] or maximum["micros"] > quote["amount_micros"]:
        raise HTTPException(422, Message("printErrors.maximumPrice"))
    job = get(session, PrintJob, offer.job_id)
    pricing = job.template_snapshot.get("pricing", {})
    job.template_snapshot = {
        **job.template_snapshot,
        "pricing": {
            **pricing,
            "quote_id": offer.id,
            "copies": job.copies,
            "quotes": {
                **pricing.get("quotes", {}),
                quote["currency"]: quote["used_micros"] + quote["amount_micros"],
            },
            "maximum": {
                "currency": maximum["currency"],
                "micros": quote["used_micros"] + maximum["micros"],
            },
        },
    }
    offer.status, offer.acceptance = "accepted", {"request": body.model_dump(), "quote": quote}
    evidence(request, session, offer, "price.accepted", maximum)
    enqueue(
        session,
        Message("notificationMessages.priceAcceptedTitle"),
        Message("notificationMessages.priceAcceptedBody"),
        "/#/queue",
        recipient_id=offer.actor_id,
        context={"job_id": job.id},
    )
    return {"status": offer.status}


@router.post("/{identifier}/decline")
def decline(identifier: str, request: Request, session: DB) -> dict[str, str]:
    offer = own_offer(request, session, identifier)
    if offer.status == "declined":
        return {"status": offer.status}
    if offer.status != "pending":
        raise HTTPException(409, Message("printErrors.priceNotPending"))
    offer.status = "declined"
    evidence(request, session, offer, "price.declined")
    return {"status": offer.status}
