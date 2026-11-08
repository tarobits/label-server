"""Explicit free retry authorization and requester acceptance of paid retries."""

import time
from collections import defaultdict
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import access_context
from app.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.cost_estimates import estimate_cost
from app.http import db, get, job_information, record
from app.job_access import job_eligible
from app.models import (
    Batch,
    BatchItem,
    Cartridge,
    LabelCopy,
    PrintJob,
    RetryOffer,
    State,
    User,
    new_id,
)
from app.notifications import enqueue
from app.pricing import accept_quote, job_geometry
from app.retry_funding import clone_job, retry_eligible
from app.schemas import Input, MaximumPrice
from app.submissions import input_fingerprint

router = APIRouter(prefix="/api", tags=["retry funding"])
DB = Annotated[Session, Depends(db, scope="function")]


class RetryInput(Input):
    request_id: UUID
    copy_ids: list[str] = Field(min_length=1, max_length=1000)
    mode: Literal["free", "paid"]
    cartridge_id: str | None = Field(default=None, max_length=100)
    include_printed: bool = False


class RetryAcceptance(Input):
    quote_id: str = Field(min_length=1, max_length=100)
    maximum_price: MaximumPrice


def evidence(session: Session, request: Request, offer: RetryOffer, action: str) -> None:
    batch = session.get(Batch, offer.batch_id)
    assert batch is not None
    context = access_context(request)
    guard = (AuditRequirement("printer", batch.printer_id, "printer.view_activity"),)
    scopes: tuple[AuditScope, ...] = (AuditScope("printer", batch.printer_id),)
    if offer.cartridge_id:
        scopes += (AuditScope("cartridge", offer.cartridge_id),)
    append_audit(
        session,
        event_id=new_id(),
        action=action,
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=scopes,
        fields={
            "actor_id": AuditField(context.actor.id, ()),
            "actor_name": AuditField(context.actor.username, ()),
            "victim_ids": AuditField([offer.requester_id], guard),
            "offer_id": AuditField(offer.id, guard),
            "batch_id": AuditField(batch.id, guard),
            "copy_ids": AuditField(offer.copy_ids, guard),
            "funding": AuditField(offer.mode, guard),
        },
    )


def persist_job(request: Request, session: Session, offer: RetryOffer, job: PrintJob) -> None:
    batch = session.get(Batch, offer.batch_id)
    assert batch is not None
    if not retry_eligible(session, job):
        raise HTTPException(409, "The retry authorization is no longer valid")
    original = session.get(PrintJob, offer.source_job_id)
    assert original is not None
    if not job_eligible(session, original):
        raise HTTPException(409, "The original work has an access or content hold")
    fleet = request.app.state.fleet
    if batch.printer_id not in fleet.workers or not fleet.supports_geometry(job, batch.printer_id):
        raise HTTPException(409, "The original printer cannot currently print these saved labels")
    session.add(job)
    session.flush()
    session.add_all(LabelCopy(job_id=job.id, ordinal=index) for index in range(job.copies))
    offer.job_id, offer.status, offer.accepted_at = job.id, "queued", time.time()
    session.flush()


@router.post("/batches/{identifier}/retry-offers", status_code=201)
def create_retries(
    identifier: str, body: RetryInput, request: Request, session: DB
) -> list[dict[str, Any]]:
    batch = get(session, Batch, identifier)
    context = access_context(request)
    context.require_printer(batch.printer_id, "view_activity")
    fingerprint = input_fingerprint({"batch_id": identifier, **body.model_dump(mode="json")})
    existing = list(
        session.scalars(select(RetryOffer).where(RetryOffer.request_key == str(body.request_id)))
    )
    if existing:
        if any(
            row.actor_id != context.actor.id or row.request_hash != fingerprint for row in existing
        ):
            raise HTTPException(409, "This retry reference already has different instructions")
        return [record(row) for row in existing]
    if batch.state in (State.PRINTING, State.NEEDS_REVIEW):
        raise HTTPException(409, "Review uncertain output before authorizing a retry")
    selected = set(body.copy_ids)
    if len(selected) != len(body.copy_ids):
        raise HTTPException(422, "Select each copy once")
    items = list(
        session.scalars(
            select(BatchItem)
            .where(BatchItem.batch_id == batch.id, BatchItem.copy_id.in_(selected))
            .order_by(BatchItem.position)
        )
    )
    if len(items) != len(selected):
        raise HTTPException(404, "A selected copy is not part of this batch")
    if any(item.outcome == State.PRINTED for item in items) and not body.include_printed:
        raise HTTPException(409, "Explicitly include confirmed printed copies to retry them")
    for offer in session.scalars(
        select(RetryOffer).where(RetryOffer.batch_id == batch.id, RetryOffer.status != "declined")
    ):
        if selected.intersection(offer.copy_ids):
            raise HTTPException(409, "A selected copy already has a retry offer or queued retry")
    cartridge = None
    if body.mode == "free":
        if not body.cartridge_id:
            raise HTTPException(422, "Choose the cartridge funding this retry")
        context.require_cartridge(body.cartridge_id, "approve_use")
        cartridge = session.get(Cartridge, body.cartridge_id)
        if cartridge is None or cartridge.archived:
            raise HTTPException(409, "Choose an available retry cartridge")
    elif body.cartridge_id:
        raise HTTPException(422, "Paid retries use the requester's eligible cartridges")
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in items:
        label = session.get(LabelCopy, item.copy_id)
        assert label is not None
        if label.state in (State.QUEUED, State.PRINTING, State.NEEDS_REVIEW):
            raise HTTPException(409, "This copy is already queued or awaiting review")
        original = session.get(PrintJob, label.job_id)
        assert original is not None
        context.require_printer(
            batch.printer_id,
            *(
                ["start_own", "start_any"]
                if original.owner_id == context.actor.id
                else ["start_any"]
            ),
        )
        user = session.get(User, original.owner_id)
        if user is None or user.disabled:
            raise HTTPException(409, "The requester is unavailable or disabled")
        if cartridge and cartridge.profile_id != original.profile_id:
            raise HTTPException(422, "The retry cartridge must match the saved tape profile")
        grouped[original.id].append(label.id)
    offers = []
    for job_id, copies in grouped.items():
        original = session.get(PrintJob, job_id)
        assert original is not None
        offer = RetryOffer(
            request_key=str(body.request_id),
            request_hash=fingerprint,
            batch_id=batch.id,
            source_job_id=job_id,
            copy_ids=copies,
            requester_id=original.owner_id,
            actor_id=context.actor.id,
            actor_name=context.actor.username,
            mode=body.mode,
            cartridge_id=body.cartridge_id,
        )
        session.add(offer)
        session.flush()
        if body.mode == "free":
            persist_job(request, session, offer, clone_job(session, offer))
            if cartridge and cartridge.owner_id:
                enqueue(
                    session,
                    "Cartridge-funded retry authorized",
                    f"{len(copies)} copies will use {cartridge.name} at no additional charge to the requester. Actual tape cost will still be recorded.",
                    "/#/usage",
                    recipient_id=cartridge.owner_id,
                    context={"retry_id": offer.id},
                )
        else:
            enqueue(
                session,
                "Print retry needs your approval",
                "Review a fresh quote before accepting a retry at your cost.",
                f"/#/retries/{offer.id}",
                recipient_id=offer.requester_id,
                context={"retry_id": offer.id},
            )
        evidence(
            session,
            request,
            offer,
            "retry.authorized" if body.mode == "free" else "retry.requested",
        )
        offers.append(record(offer))
    return offers


def own_offer(request: Request, session: Session, identifier: str) -> RetryOffer:
    offer = session.get(RetryOffer, identifier)
    if offer is None or offer.requester_id != access_context(request).actor.id:
        raise HTTPException(404, "Retry offer not found")
    return offer


@router.get("/retries/{identifier}")
def retry_detail(identifier: str, request: Request, session: DB) -> dict[str, Any]:
    offer = own_offer(request, session, identifier)
    job = session.get(PrintJob, offer.source_job_id)
    assert job is not None
    return {
        **record(offer),
        "label": {
            **job_information(session, job),
            "job_id": job.id,
            "width_mm": job.width_mm,
            "length_mm": job.length_mm,
            "copies": len(offer.copy_ids),
        },
    }


@router.post("/retries/{identifier}/quote")
def retry_quote(identifier: str, request: Request, session: DB) -> dict[str, Any]:
    offer = own_offer(request, session, identifier)
    if offer.status != "pending" or offer.mode != "paid":
        raise HTTPException(409, "This retry no longer needs a price quote")
    job = clone_job(session, offer)
    if not retry_eligible(session, job):
        raise HTTPException(409, "The retry authorization is no longer valid")
    return estimate_cost(request, session, job.destination_id, job.profile_id, job_geometry(job))


@router.post("/retries/{identifier}/accept")
def accept_retry(
    identifier: str, body: RetryAcceptance, request: Request, session: DB
) -> dict[str, Any]:
    offer = own_offer(request, session, identifier)
    if offer.status == "queued":
        saved = session.get(PrintJob, offer.job_id)
        pricing = saved.template_snapshot.get("pricing", {}) if saved else {}
        if (
            pricing.get("quote_id") != body.quote_id
            or pricing.get("maximum") != body.maximum_price.model_dump()
        ):
            raise HTTPException(409, "This retry was already accepted with different price consent")
        return record(offer)
    if offer.status != "pending" or offer.mode != "paid":
        raise HTTPException(409, "This retry no longer awaits acceptance")
    job = clone_job(session, offer)
    accept_quote(request, session, job, body.quote_id, body.maximum_price.model_dump())
    persist_job(request, session, offer, job)
    evidence(session, request, offer, "retry.accepted")
    return record(offer)


@router.post("/retries/{identifier}/decline")
def decline_retry(identifier: str, request: Request, session: DB) -> dict[str, Any]:
    offer = own_offer(request, session, identifier)
    if offer.status == "declined":
        return record(offer)
    if offer.status != "pending":
        raise HTTPException(409, "This retry no longer awaits acceptance")
    offer.status = "declined"
    evidence(session, request, offer, "retry.declined")
    return record(offer)
