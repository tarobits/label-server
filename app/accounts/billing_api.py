"""Permission-checked group account management and billing decisions."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.accounts import billing  # noqa: F401
from app.accounts.billing_models import (
    BillingAccount,
    BillingCharge,
    BillingEvent,
    BillingGrant,
    BillingRequest,
)
from app.authn.access import access_context
from app.http import db, job_summary, record
from app.models import Batch, BatchItem, LabelCopy, PrintJob, Role, TapeAllocation, User
from app.schemas import Input
from app.transaction_routes import TransactionRouter

router = TransactionRouter(prefix="/api/accounts/groups", tags=["group billing"])
DB = Annotated[Session, Depends(db, scope="function")]


class AccountInput(Input):
    name: str = Field(min_length=1, max_length=100)
    archived: bool = False


class GrantInput(Input):
    principal_kind: Literal["user", "role"]
    principal_id: str = Field(min_length=1, max_length=128)
    permission: str
    effect: Literal["allow", "deny", "inherit"]


class DecisionInput(Input):
    approve: bool
    reason: str = Field(default="", max_length=500)


class PersonalInput(Input):
    cancel: bool = False


class HistoryInput(Input):
    request_id: UUID
    batch_id: str = Field(min_length=1, max_length=128)
    direct: bool = False
    job_ids: list[str] | None = Field(default=None, min_length=1, max_length=1000)


class PaymentInput(Input):
    request_id: UUID
    recipient_id: str = Field(min_length=1, max_length=128)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount_micros: int = Field(strict=True, gt=0, le=10**15)
    cartridge_ids: list[str] | None = Field(default=None, max_length=1000)
    note: str = Field(min_length=1, max_length=500)


def request_record(session: Session, value: BillingRequest, request: Request) -> dict[str, Any]:
    actor = access_context(request).actor
    job = preview_job(session, value, request)
    return {
        **record(value),
        "can_decide": value.status == "pending" and billing.can_decide(session, actor, value),
        "can_resolve": value.kind == "job"
        and value.requester_id == actor.id
        and value.status in ("pending", "rejected"),
        "prints_url": f"/api/accounts/groups/requests/{value.id}/prints"
        if can_preview_request(session, value, request)
        else None,
        "preview": {
            "url": f"/api/accounts/groups/requests/{value.id}/preview",
            "width_mm": job.width_mm,
            "length_mm": job.length_mm,
            "copies": job.copies,
        }
        if job
        else None,
    }


def can_preview_request(session: Session, value: BillingRequest, request: Request) -> bool:
    actor = access_context(request).actor
    return value.kind in {"job", "history"} and (
        actor.is_admin
        or value.requester_id == actor.id
        or billing.can_decide(session, actor, value)
    )


def preview_job(session: Session, value: BillingRequest, request: Request) -> PrintJob | None:
    if value.kind != "job" or not can_preview_request(session, value, request):
        return None
    return session.get(PrintJob, value.source_id)


def funded_prints(
    value: BillingRequest, batch_id: str | None = None
) -> Select[PrintJob, LabelCopy, BatchItem, Batch]:
    """Scope label contents to this funding source, never the whole physical batch."""
    query = (
        select(PrintJob, LabelCopy, BatchItem, Batch)
        .join(LabelCopy, LabelCopy.job_id == PrintJob.id)
        .outerjoin(BatchItem, BatchItem.copy_id == LabelCopy.id)
        .outerjoin(Batch, Batch.id == BatchItem.batch_id)
        .where(PrintJob.owner_id == value.requester_id)
    )
    if value.kind == "job":
        query = query.where(PrintJob.id == value.source_id)
    else:
        # Historical funding covers the requester's remaining personal costs.
        # Jobs already charged separately to a group are not part of that transfer.
        separately_funded = (
            select(BillingRequest.source_id)
            .join(BillingCharge, BillingCharge.request_id == BillingRequest.id)
            .where(BillingRequest.kind == "job", BillingCharge.batch_id == value.source_id)
        )
        query = query.where(
            BatchItem.batch_id == value.source_id, PrintJob.id.not_in(separately_funded)
        )
        if selected := value.details.get("job_amounts"):
            query = query.where(PrintJob.id.in_(selected))
    if batch_id is not None:
        query = query.where(BatchItem.batch_id == batch_id)
    return query.order_by(Batch.created_at, Batch.id, BatchItem.position, LabelCopy.ordinal)


def print_details(
    session: Session,
    value: BillingRequest,
    request: Request,
    *,
    charge: BillingCharge | None = None,
) -> dict[str, Any]:
    from app.printing.print_activity import readable_batch

    if not can_preview_request(session, value, request):
        raise HTTPException(404, "Funding prints are unavailable")
    prefix = (
        f"/api/accounts/groups/charges/{charge.id}"
        if charge
        else f"/api/accounts/groups/requests/{value.id}"
    )
    prints: dict[tuple[str, str | None], dict[str, Any]] = {}
    batches: dict[str, dict[str, Any]] = {}
    for job, label, item, batch in session.execute(
        funded_prints(value, charge.batch_id if charge else None)
    ):
        key = (job.id, batch.id if batch else None)
        if key not in prints:
            prints[key] = {
                "job_id": job.id,
                "batch_id": batch.id if batch else None,
                "text": job_summary(job),
                "width_mm": job.width_mm,
                "length_mm": job.length_mm,
                "copies": 0,
                "outcomes": {},
                "url": f"{prefix}/items/{label.id}/preview",
            }
        entry = prints[key]
        entry["copies"] += 1
        outcome = item.outcome if item else label.state
        entry["outcomes"][outcome] = entry["outcomes"].get(outcome, 0) + 1
        if batch and batch.id not in batches:
            try:
                readable_batch(request, session, batch.id)
                can_view = True
            except HTTPException as exc:
                if exc.status_code != 403:
                    raise
                can_view = False
            batches[batch.id] = {
                "id": batch.id,
                "created_at": batch.created_at,
                "can_view": can_view,
            }
    return {"prints": list(prints.values()), "batches": list(batches.values())}


def print_source(
    session: Session, identifier: str, *, is_charge: bool = False
) -> tuple[BillingRequest, BillingCharge | None]:
    charge = session.get(BillingCharge, identifier) if is_charge else None
    value = session.get(BillingRequest, charge.request_id if charge else identifier)
    if value is None or (is_charge and charge is None):
        raise HTTPException(404, "Funding prints are unavailable")
    return value, charge


@router.get("/requests/{identifier}/prints")
def request_prints(identifier: str, request: Request, session: DB) -> dict[str, Any]:
    value, _ = print_source(session, identifier)
    return print_details(session, value, request)


@router.get("/charges/{identifier}/prints")
def charge_prints(identifier: str, request: Request, session: DB) -> dict[str, Any]:
    value, charge = print_source(session, identifier, is_charge=True)
    return print_details(session, value, request, charge=charge)


def scoped_preview(
    identifier: str, copy_id: str, request: Request, session: Session, *, is_charge: bool = False
) -> Response:
    from app.api import label_preview_response

    value, charge = print_source(session, identifier, is_charge=is_charge)
    if not can_preview_request(session, value, request):
        raise HTTPException(404, "Funding preview is unavailable")
    row = session.execute(
        funded_prints(value, charge.batch_id if charge else None)
        .where(LabelCopy.id == copy_id)
        .limit(1)
    ).first()
    if row is None:
        raise HTTPException(404, "Funding preview is unavailable")
    return label_preview_response(request, session, row[0], row[1])


@router.get("/requests/{identifier}/items/{copy_id}/preview")
def request_item_preview(identifier: str, copy_id: str, request: Request, session: DB) -> Response:
    return scoped_preview(identifier, copy_id, request, session)


@router.get("/charges/{identifier}/items/{copy_id}/preview")
def charge_item_preview(identifier: str, copy_id: str, request: Request, session: DB) -> Response:
    return scoped_preview(identifier, copy_id, request, session, is_charge=True)


@router.get("/requests/{identifier}/preview")
def funding_preview(identifier: str, request: Request, session: DB) -> Response:
    from app.api import label_preview_response

    value = session.get(BillingRequest, identifier)
    job = preview_job(session, value, request) if value else None
    if job is None:
        raise HTTPException(404, "Funding preview is unavailable")
    label = session.scalar(
        select(LabelCopy).where(LabelCopy.job_id == job.id).order_by(LabelCopy.ordinal).limit(1)
    )
    if label is None:
        raise HTTPException(404, "Funding preview is unavailable")
    return label_preview_response(request, session, job, label)


@router.get("")
def accounts(request: Request, session: DB) -> dict[str, Any]:
    actor = access_context(request).actor
    creditor = set(
        session.scalars(
            select(BillingCharge.account_id).where(BillingCharge.recipient_id == actor.id)
        )
    )
    involved = set(
        session.scalars(
            select(BillingRequest.account_id).where(BillingRequest.requester_id == actor.id)
        )
    )
    result = []
    for account in session.scalars(select(BillingAccount).order_by(BillingAccount.name)):
        rights = billing.permissions(session, actor, account.id)
        if (
            rights
            or account.id in creditor
            or account.id in involved
            or "usage.edit_accounts" in actor.permissions
        ):
            result.append({**record(account), "permissions": sorted(rights)})
    return {
        "accounts": result,
        "can_create": actor.is_admin or "billing.create" in actor.permissions,
        "permissions": billing.PERMISSIONS,
    }


@router.post("", status_code=201)
def create_account(body: AccountInput, request: Request, session: DB) -> dict[str, Any]:
    actor = access_context(request).actor
    if not actor.is_admin and "billing.create" not in actor.permissions:
        raise HTTPException(403, "Creating group accounts is not permitted")
    if not body.name.strip():
        raise HTTPException(422, "Enter an account name")
    account = BillingAccount(name=body.name.strip(), archived=body.archived)
    session.add(account)
    session.flush()
    for permission in billing.PERMISSIONS:
        session.add(
            BillingGrant(
                account_id=account.id,
                principal_kind="user",
                principal_id=actor.id,
                permission=permission,
                effect="allow",
            )
        )
    billing.audit(session, actor, account.id, "account.created", name=account.name)
    return record(account)


@router.get("/history")
def history(request: Request, session: DB) -> list[dict[str, Any]]:
    user_id = access_context(request).actor.id
    return [
        {**entry, "previews": historical_previews(session, entry["batch_id"], user_id)}
        for entry in billing.eligible_history(session, user_id)
    ]


def historical_previews(session: Session, batch_id: str, user_id: str) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for job, copy_id in session.execute(
        select(PrintJob, BatchItem.copy_id)
        .join(LabelCopy, LabelCopy.job_id == PrintJob.id)
        .join(BatchItem, BatchItem.copy_id == LabelCopy.id)
        .where(BatchItem.batch_id == batch_id, PrintJob.owner_id == user_id)
        .order_by(BatchItem.position)
    ):
        if job.id not in result:
            result[job.id] = {
                "job_id": job.id,
                "copy_id": copy_id,
                "text": job_summary(job),
                "width_mm": job.width_mm,
                "length_mm": job.length_mm,
                "copies": 0,
                "url": f"/api/accounts/groups/history/{batch_id}/items/{copy_id}/preview",
            }
        result[job.id]["copies"] += 1
    return list(result.values())


@router.get("/history/{batch_id}/items/{copy_id}/preview")
def historical_preview(batch_id: str, copy_id: str, request: Request, session: DB) -> Response:
    from app.api import label_preview_response

    user_id = access_context(request).actor.id
    allocation = session.get(TapeAllocation, (batch_id, user_id))
    item = session.get(BatchItem, (batch_id, copy_id))
    label = session.get(LabelCopy, copy_id) if item else None
    job = session.get(PrintJob, label.job_id) if label else None
    if allocation is None or job is None or label is None or job.owner_id != user_id:
        raise HTTPException(404, "Historical label preview is unavailable")
    return label_preview_response(request, session, job, label)


@router.get("/{identifier}")
def details(identifier: str, request: Request, session: DB) -> dict[str, Any]:
    actor = access_context(request).actor
    account = session.get(BillingAccount, identifier)
    if account is None:
        raise HTTPException(404, "Group account not found")
    rights = billing.permissions(session, actor, identifier)
    charges = billing.visible_outstanding(session, actor, identifier)
    for charge in charges:
        source = session.get(BillingRequest, charge["request_id"])
        charge["source_kind"] = source.kind if source else None
        charge["prints_url"] = (
            f"/api/accounts/groups/charges/{charge['id']}/prints"
            if source and can_preview_request(session, source, request)
            else None
        )
    requests = [
        request_record(session, entry, request)
        for entry in session.scalars(
            select(BillingRequest)
            .where(BillingRequest.account_id == identifier)
            .order_by(BillingRequest.created_at.desc())
        )
        if billing.can_read_request(session, actor, entry)
    ]
    if not rights and not charges and not requests:
        raise HTTPException(403, "Group account access is not granted")
    return {
        **record(account),
        "permissions": sorted(rights),
        "charges": charges,
        "requests": requests,
    }


@router.put("/{identifier}")
def update_account(
    identifier: str, body: AccountInput, request: Request, session: DB
) -> dict[str, Any]:
    actor = access_context(request).actor
    account = billing.require(session, actor, identifier, "edit")
    if not body.name.strip():
        raise HTTPException(422, "Enter an account name")
    account.name, account.archived = body.name.strip(), body.archived
    billing.audit(
        session, actor, identifier, "account.updated", name=account.name, archived=account.archived
    )
    return record(account)


@router.get("/{identifier}/access")
def access(identifier: str, request: Request, session: DB) -> dict[str, Any]:
    billing.require(session, access_context(request).actor, identifier, "manage_access")
    return {
        "grants": [
            record(entry)
            for entry in session.scalars(
                select(BillingGrant).where(BillingGrant.account_id == identifier)
            )
        ],
        "users": [
            {"id": user.id, "name": user.username}
            for user in session.scalars(select(User).where(User.disabled.is_(False)))
        ],
        "roles": [{"id": role.id, "name": role.name} for role in session.scalars(select(Role))],
        "permissions": billing.PERMISSIONS,
    }


@router.put("/{identifier}/access", status_code=204)
def set_access(identifier: str, body: GrantInput, request: Request, session: DB) -> None:
    actor = access_context(request).actor
    billing.require(session, actor, identifier, "manage_access")
    if body.permission not in billing.PERMISSIONS:
        raise HTTPException(422, "Unknown group account permission")
    principal = session.get(User if body.principal_kind == "user" else Role, body.principal_id)
    if principal is None:
        raise HTTPException(422, "Choose an existing user or role")
    key = (identifier, body.principal_kind, body.principal_id, body.permission)
    grant = session.get(BillingGrant, key)
    if body.effect == "inherit":
        if grant:
            session.delete(grant)
    elif grant:
        grant.effect = body.effect
    else:
        session.add(BillingGrant(account_id=identifier, **body.model_dump()))
    billing.audit(session, actor, identifier, "access.changed", **body.model_dump())


@router.get("/{identifier}/audit")
def audit(identifier: str, request: Request, session: DB) -> list[dict[str, Any]]:
    billing.require(session, access_context(request).actor, identifier, "view_audit")
    return [
        record(entry)
        for entry in session.scalars(
            select(BillingEvent)
            .where(BillingEvent.account_id == identifier)
            .order_by(BillingEvent.created_at.desc())
            .limit(200)
        )
    ]


def receipt(
    session: Session,
    identifier: str,
    account_id: str,
    actor_id: str,
    kind: str,
    source: str,
    inputs: dict[str, Any],
) -> BillingRequest | None:
    existing = session.get(BillingRequest, identifier)
    if existing and (
        existing.account_id != account_id
        or existing.requester_id != actor_id
        or existing.kind != kind
        or existing.source_id != source
        or existing.details.get("input") != inputs
    ):
        raise HTTPException(409, "This request reference has already been used")
    return existing


@router.post("/{identifier}/transfers", status_code=201)
def transfer(identifier: str, body: HistoryInput, request: Request, session: DB) -> dict[str, Any]:
    actor = access_context(request).actor
    billing.require(session, actor, identifier, "request_transfer", active=True)
    if body.direct:
        billing.require(session, actor, identifier, "direct", active=True)
    inputs = body.model_dump(mode="json", exclude_none=True)
    if existing := receipt(
        session, str(body.request_id), identifier, actor.id, "history", body.batch_id, inputs
    ):
        return request_record(session, existing, request)
    entry = next(
        (
            item
            for item in billing.eligible_history(session, actor.id)
            if item["batch_id"] == body.batch_id
        ),
        None,
    )
    if not entry or entry["available_micros"] <= 0:
        raise HTTPException(409, "No unfunded charges remain for this print")
    if entry["needs_payment_allocation"]:
        raise HTTPException(
            409, "Allocate existing payments to cartridges before transferring these costs"
        )
    units = {unit["job_id"]: unit for unit in entry["labels"] if unit["available_micros"] > 0}
    identifiers = body.job_ids if body.job_ids is not None else list(units)
    if len(set(identifiers)) != len(identifiers):
        raise HTTPException(422, "Select each label only once")
    if any(identifier not in units for identifier in identifiers):
        raise HTTPException(409, "Selected labels are unavailable for transfer")
    if any(units[identifier]["pending"] for identifier in identifiers):
        raise HTTPException(
            409, "Resolve the existing funding request for the selected labels first"
        )
    selected_amounts = {
        identifier: str(units[identifier]["available_micros"]) for identifier in identifiers
    }
    amount = (
        sum(map(int, selected_amounts.values())) if selected_amounts else entry["available_micros"]
    )
    if not selected_amounts and session.scalar(
        select(BillingRequest.id).where(
            BillingRequest.requester_id == actor.id,
            BillingRequest.kind == "history",
            BillingRequest.source_id == body.batch_id,
            BillingRequest.status == "pending",
        )
    ):
        raise HTTPException(409, "Resolve the existing funding request for this print first")
    value = BillingRequest(
        id=str(body.request_id),
        account_id=identifier,
        requester_id=actor.id,
        requester_name=actor.username,
        kind="history",
        source_id=body.batch_id,
        mode="risk",
        details={
            "input": inputs,
            "amount_micros": amount,
            "currency": entry["currency"],
            **({"job_amounts": selected_amounts} if selected_amounts else {}),
        },
    )
    session.add(value)
    session.flush()
    billing.audit(
        session,
        actor,
        identifier,
        "transfer.direct" if body.direct else "transfer.requested",
        request_id=value.id,
        batch_id=body.batch_id,
    )
    if body.direct:
        import time

        from app.models import TapeAllocation

        original = session.get(TapeAllocation, (body.batch_id, actor.id))
        assert original is not None
        billing.fund_allocation(session, value, original, amount, actor)
        value.status, value.mode = "approved", "direct"
        value.decided_at, value.decided_by = time.time(), actor.id
    else:
        billing.notify(session, value)
    return request_record(session, value, request)


@router.post("/{identifier}/payments", status_code=201)
def payment(identifier: str, body: PaymentInput, request: Request, session: DB) -> dict[str, Any]:
    actor = access_context(request).actor
    # Creditors and accounting editors retain their existing right to acknowledge receipt.
    confirms = (
        actor.is_admin
        or "usage.edit_accounts" in actor.permissions
        or actor.id == body.recipient_id
    )
    if not confirms:
        billing.require(session, actor, identifier, "record_payments")
    inputs = body.model_dump(mode="json")
    if existing := receipt(
        session, str(body.request_id), identifier, actor.id, "payment", body.recipient_id, inputs
    ):
        return request_record(session, existing, request)
    remaining = body.amount_micros
    allocations = {}
    for entry in billing.outstanding(session, identifier):
        if entry["recipient_id"] != body.recipient_id or entry["currency"] != body.currency:
            continue
        if body.cartridge_ids is not None and entry["cartridge_id"] not in body.cartridge_ids:
            continue
        amount = min(remaining, entry["outstanding_micros"])
        if amount > 0:
            allocations[entry["id"]] = str(amount)
            remaining -= amount
    if remaining:
        raise HTTPException(422, "The payment exceeds the selected outstanding debts")
    value = BillingRequest(
        id=str(body.request_id),
        account_id=identifier,
        requester_id=actor.id,
        requester_name=actor.username,
        kind="payment",
        source_id=body.recipient_id,
        mode="confirmation",
        details={
            "input": inputs,
            "recipient_id": body.recipient_id,
            "amount_micros": body.amount_micros,
            "currency": body.currency,
            "allocations": allocations,
            "note": body.note,
        },
    )
    session.add(value)
    session.flush()
    billing.audit(session, actor, identifier, "payment.reported", request_id=value.id)
    if confirms:
        billing.decide_request(session, actor, value, True, body.note)
    else:
        billing.notify(session, value)
    return request_record(session, value, request)


@router.post("/requests/{identifier}/decision")
def decide(identifier: str, body: DecisionInput, request: Request, session: DB) -> dict[str, Any]:
    value = session.get(BillingRequest, identifier)
    if value is None:
        raise HTTPException(404, "Billing request not found")
    billing.decide_request(session, access_context(request).actor, value, body.approve, body.reason)
    return request_record(session, value, request)


@router.post("/requests/{identifier}/resolve")
def resolve(identifier: str, body: PersonalInput, request: Request, session: DB) -> dict[str, Any]:
    value = session.get(BillingRequest, identifier)
    if value is None:
        raise HTTPException(404, "Billing request not found")
    billing.resolve_personally(session, access_context(request).actor, value, body.cancel)
    return request_record(session, value, request)
