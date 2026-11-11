"""Group funding policy and settlement, independent of print hardware."""

import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import Actor
from app.billing_models import (
    BillingAccount,
    BillingCharge,
    BillingEvent,
    BillingGrant,
    BillingPayment,
    BillingRequest,
)
from app.models import (
    Batch,
    LabelCopy,
    PrintJob,
    State,
    TapeAllocation,
    UnitCharge,
    UsageAdjustment,
    User,
    new_id,
)

PERMISSIONS = {
    "view": "View balances and transactions",
    "request": "Request print funding",
    "direct": "Charge directly",
    "approve": "Approve print funding",
    "request_transfer": "Request historical transfers and reimbursements",
    "approve_transfer": "Approve historical transfers and reimbursements",
    "record_payments": "Report payments for confirmation",
    "edit": "Edit and archive account",
    "manage_access": "Manage account permissions",
    "view_audit": "View account audit log",
}


def permissions(session: Session, actor: Actor, account_id: str) -> set[str]:
    if actor.is_admin:
        return set(PERMISSIONS)
    rules: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for grant in session.scalars(select(BillingGrant).where(BillingGrant.account_id == account_id)):
        if grant.principal_kind == "user" and grant.principal_id == actor.id:
            rules[grant.permission].append((2, grant.effect))
        elif grant.principal_kind == "role" and grant.principal_id in actor.role_ids:
            rules[grant.permission].append((1, grant.effect))
    return {
        permission
        for permission, candidates in rules.items()
        if permission in PERMISSIONS
        and all(
            effect == "allow"
            for rank, effect in candidates
            if rank == max(r for r, _ in candidates)
        )
    }


def require(
    session: Session, actor: Actor, account_id: str, permission: str, *, active: bool = False
) -> BillingAccount:
    account = session.get(BillingAccount, account_id)
    if account is None:
        raise HTTPException(404, "Group account not found")
    if permission not in permissions(session, actor, account_id):
        raise HTTPException(403, "This group account permission is not granted")
    if active and account.archived:
        raise HTTPException(409, "This group account is archived")
    return account


def audit(session: Session, actor: Actor, account_id: str, action: str, **details: Any) -> None:
    from app.audit import AuditField, AuditRequirement, AuditScope, append_audit

    event = BillingEvent(
        account_id=account_id,
        actor_id=actor.id,
        actor_name=actor.username,
        action=action,
        details=details,
    )
    session.add(event)
    session.flush()
    guard = (AuditRequirement("application", "", "usage.view_others"),)
    append_audit(
        session,
        event_id=new_id(),
        action="billing.changed",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("global"),),
        fields={
            "actor_id": AuditField(actor.id, ()),
            "actor_name": AuditField(actor.username, ()),
            "account_id": AuditField(account_id, guard),
            "event_id": AuditField(event.id, guard),
            "change": AuditField(action, guard),
        },
    )


def can_decide(session: Session, actor: Actor, request: BillingRequest) -> bool:
    if request.kind == "payment":
        return (
            actor.is_admin
            or "usage.edit_accounts" in actor.permissions
            or actor.id == request.details.get("recipient_id")
        )
    return actor.id != request.requester_id and (
        "approve_transfer" if request.kind == "history" else "approve"
    ) in permissions(session, actor, request.account_id)


def can_read_request(session: Session, actor: Actor, request: BillingRequest) -> bool:
    return (
        actor.id == request.requester_id
        or can_decide(session, actor, request)
        or "view" in permissions(session, actor, request.account_id)
    )


def notify(session: Session, request: BillingRequest, *, decision: bool = False) -> None:
    from app.auth import actor_for_user
    from app.models import Notification
    from app.notifications import enqueue

    session.flush()
    if decision:
        for notice in session.scalars(
            select(Notification).where(Notification.delivered_at.is_(None))
        ):
            if notice.context.get("billing_request_id") == request.id and notice.context.get(
                "billing_actionable"
            ):
                notice.cancelled = True
        recipients = [request.requester_id]
    else:
        recipients = [
            user.id
            for user in session.scalars(select(User).where(User.disabled.is_(False)))
            if can_decide(session, actor_for_user(session, user), request)
        ]
    for recipient in recipients:
        enqueue(
            session,
            "Group account request updated" if decision else "Group account request",
            f"Your request was {request.status}." if decision else "A request needs your review.",
            f"/#/group-accounts?account={request.account_id}&request={request.id}",
            recipient_id=recipient,
            context={"billing_request_id": request.id, "billing_actionable": not decision},
        )


def validate_selection(session: Session, actor: Actor, selection: dict[str, Any] | None) -> None:
    if selection:
        require(
            session,
            actor,
            selection["account_id"],
            "direct" if selection["mode"] == "direct" else "request",
            active=True,
        )


def register_job(session: Session, job: PrintJob, actor: Actor) -> None:
    selection = job.template_snapshot.get("billing")
    if not selection:
        return
    # Billing authority is always the original requester's, never the print reviewer’s.
    validate_selection(session, actor, selection)
    existing = session.scalar(
        select(BillingRequest).where(
            BillingRequest.kind == "job", BillingRequest.source_id == job.id
        )
    )
    if existing:
        return
    direct = selection["mode"] == "direct"
    request = BillingRequest(
        account_id=selection["account_id"],
        requester_id=job.owner_id,
        requester_name=actor.username,
        kind="job",
        source_id=job.id,
        mode=selection["mode"],
        status="approved" if direct else "pending",
        details={
            "pricing": job.template_snapshot.get("pricing", {}),
            "note": selection.get("note", ""),
        },
        decided_by=actor.id if direct else None,
        decided_at=time.time() if direct else None,
    )
    session.add(request)
    session.flush()
    audit(
        session,
        actor,
        request.account_id,
        "funding.direct" if direct else "funding.requested",
        request_id=request.id,
        job_id=job.id,
    )
    if not direct:
        notify(session, request)


def job_request(session: Session, job: PrintJob) -> BillingRequest | None:
    if not job.template_snapshot.get("billing"):
        return None
    return session.scalar(
        select(BillingRequest).where(
            BillingRequest.kind == "job", BillingRequest.source_id == job.id
        )
    )


def job_eligible(session: Session, job: PrintJob) -> bool:
    if not job.template_snapshot.get("billing"):
        return True
    request = job_request(session, job)
    if request is None:
        return False
    if request.status == "personal":
        return True
    if request.mode == "risk" and request.status in ("pending", "rejected"):
        return True  # The submitter explicitly accepted personal liability.
    account = session.get(BillingAccount, request.account_id)
    if not account or account.archived or request.status != "approved":
        return False
    from app.auth import actor_for_user

    user = session.get(User, request.requester_id)
    if user is None or user.disabled:
        return False
    required = "direct" if request.mode == "direct" else "request"
    if required not in permissions(session, actor_for_user(session, user), request.account_id):
        return False
    if request.mode != "direct":
        approver = session.get(User, request.decided_by) if request.decided_by else None
        if (
            approver is None
            or approver.disabled
            or not can_decide(session, actor_for_user(session, approver), request)
        ):
            return False
    return True


def offsets(session: Session) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = defaultdict(int)
    for charge in session.scalars(select(BillingCharge).where(BillingCharge.kind == "transfer")):
        result[charge.batch_id, charge.requester_id] += int(charge.amount_micros)
    return result


def eligible_history(session: Session, user_id: str) -> list[dict[str, Any]]:
    """Allocate recorded cartridge payments oldest-first; never infer payment from self-use."""
    moved = offsets(session)
    claimed: dict[str, int] = defaultdict(int)
    for charge in session.scalars(
        select(BillingCharge).where(BillingCharge.requester_id == user_id)
    ):
        claimed[charge.batch_id] += int(charge.amount_micros)
    payments: dict[tuple[str | None, str, str], int] = defaultdict(int)
    unallocated: dict[tuple[str | None, str], int] = defaultdict(int)
    for payment in session.scalars(
        select(UsageAdjustment).where(UsageAdjustment.user_id == user_id)
    ):
        unallocated[payment.recipient_id, payment.currency] += payment.amount_minor * 10000 - sum(
            int(value) for value in payment.cartridge_allocations.values()
        )
        for cartridge, amount in payment.cartridge_allocations.items():
            payments[payment.recipient_id, cartridge, payment.currency] += int(amount)
    result = []
    for row, stamp in session.execute(
        select(TapeAllocation, Batch.created_at)
        .join(Batch, Batch.id == TapeAllocation.batch_id)
        .where(TapeAllocation.user_id == user_id)
        .order_by(Batch.created_at, Batch.id)
    ):
        if row.charged_micros is None or not row.cartridge_id:
            continue
        total = int(row.charged_micros)
        remaining = max(0, total - claimed[row.batch_id])
        personal = max(0, total - moved.get((row.batch_id, user_id), 0))
        key = (row.recipient_id, row.cartridge_id, row.currency)
        paid = min(personal, max(0, payments[key])) if row.recipient_id != user_id else 0
        payments[key] -= paid
        # Previously reimbursed costs remain part of the original personal payment history.
        reimbursed = claimed[row.batch_id] - moved.get((row.batch_id, user_id), 0)
        paid = max(0, paid - reimbursed)
        result.append(
            {
                "batch_id": row.batch_id,
                "created_at": stamp,
                "currency": row.currency,
                "cartridge_id": row.cartridge_id,
                "recipient_id": row.recipient_id,
                "available_micros": remaining,
                "paid_micros": min(remaining, paid),
                "needs_payment_allocation": bool(unallocated[row.recipient_id, row.currency]),
                "supply": row.recipient_id == user_id,
            }
        )
    return result


def fund_allocation(
    session: Session,
    request: BillingRequest,
    row: TapeAllocation,
    amount: int,
    actor: Actor,
    *,
    retrospective: bool = True,
) -> None:
    if session.scalar(
        select(BillingCharge.id).where(
            BillingCharge.request_id == request.id, BillingCharge.batch_id == row.batch_id
        )
    ):
        return
    eligible = next(
        (
            entry
            for entry in eligible_history(session, row.user_id)
            if entry["batch_id"] == row.batch_id
        ),
        None,
    )
    if eligible is None or amount > eligible["available_micros"]:
        raise HTTPException(409, "This charge has already been funded")
    if retrospective and eligible["needs_payment_allocation"]:
        raise HTTPException(
            409,
            "Allocate this member's existing payments to cartridges before transferring these costs",
        )
    paid = min(amount, eligible["paid_micros"]) if retrospective else 0
    parts = (
        [("supply", amount)]
        if eligible["supply"]
        else [("reimbursement", paid), ("transfer", amount - paid)]
    )
    for kind, value in parts:
        if not value:
            continue
        charge = BillingCharge(
            account_id=request.account_id,
            request_id=request.id,
            batch_id=row.batch_id,
            requester_id=row.user_id,
            requester_name=row.username,
            recipient_id=row.user_id if kind == "reimbursement" else row.recipient_id,
            recipient_name=row.username if kind == "reimbursement" else row.recipient_name,
            cartridge_id=row.cartridge_id or "",
            currency=row.currency,
            kind=kind,
            amount_micros=str(value),
        )
        session.add(charge)
        audit(
            session,
            actor,
            request.account_id,
            f"charge.{kind}",
            request_id=request.id,
            batch_id=row.batch_id,
            requester_id=row.user_id,
            amount_micros=value,
            currency=row.currency,
        )


def settle_job(
    session: Session, request: BillingRequest, actor: Actor, *, retrospective: bool = True
) -> None:
    for unit in session.scalars(select(UnitCharge).where(UnitCharge.job_id == request.source_id)):
        if unit.charged_micros is None:
            continue
        allocation = session.get(TapeAllocation, (unit.batch_id, request.requester_id))
        if allocation:
            fund_allocation(
                session,
                request,
                allocation,
                int(unit.charged_micros),
                actor,
                retrospective=retrospective,
            )


def settle_batch(session: Session, batch: Batch) -> None:
    session.flush()
    for request in session.scalars(
        select(BillingRequest)
        .join(UnitCharge, UnitCharge.job_id == BillingRequest.source_id)
        .where(
            BillingRequest.kind == "job",
            BillingRequest.status == "approved",
            UnitCharge.batch_id == batch.id,
        )
    ):
        settle_job(
            session, request, Actor(id="system", username="Print accounting"), retrospective=False
        )


def outstanding(session: Session, account_id: str) -> list[dict[str, Any]]:
    from app.http import record
    from app.models import Cartridge

    paid: dict[str, int] = defaultdict(int)
    for payment in session.scalars(
        select(BillingPayment).join(BillingCharge).where(BillingCharge.account_id == account_id)
    ):
        paid[payment.charge_id] += int(payment.amount_micros)
    names = dict(session.execute(select(Cartridge.id, Cartridge.name)).all())
    return [
        {
            **record(charge),
            "cartridge_name": names.get(charge.cartridge_id, charge.cartridge_id),
            "outstanding_micros": int(charge.amount_micros) - paid[charge.id],
        }
        for charge in session.scalars(
            select(BillingCharge)
            .where(BillingCharge.account_id == account_id)
            .order_by(BillingCharge.created_at, BillingCharge.id)
        )
    ]


def decide_request(
    session: Session, actor: Actor, request: BillingRequest, approve: bool, reason: str
) -> None:
    if not can_decide(session, actor, request):
        raise HTTPException(
            403, "You cannot decide this request; funding requests cannot be self-approved"
        )
    target = "approved" if approve else "rejected"
    if request.status == target:
        return
    if request.status != "pending":
        raise HTTPException(409, "This request has already been decided")
    account = session.get(BillingAccount, request.account_id)
    if approve and request.kind != "payment" and (not account or account.archived):
        raise HTTPException(409, "This group account is archived")
    if approve:
        if request.kind != "payment":
            from app.auth import actor_for_user

            requester = session.get(User, request.requester_id)
            if requester is None or requester.disabled:
                raise HTTPException(409, "The requester is no longer active")
            require(
                session,
                actor_for_user(session, requester),
                request.account_id,
                "request_transfer" if request.kind == "history" else "request",
                active=True,
            )
        if request.kind == "job":
            settle_job(session, request, actor)
        elif request.kind == "history":
            row = session.get(TapeAllocation, (request.source_id, request.requester_id))
            if row is None:
                raise HTTPException(409, "Original charge is unavailable")
            fund_allocation(session, request, row, int(request.details["amount_micros"]), actor)
        else:
            available = {entry["id"]: entry for entry in outstanding(session, request.account_id)}
            for identifier, amount in request.details["allocations"].items():
                entry = available.get(identifier)
                if (
                    entry is None
                    or int(amount) > entry["outstanding_micros"]
                    or entry["recipient_id"] != request.details["recipient_id"]
                ):
                    raise HTTPException(
                        409, "Outstanding debts changed; submit a new payment report"
                    )
                session.add(
                    BillingPayment(
                        request_id=request.id,
                        charge_id=identifier,
                        amount_micros=str(amount),
                        confirmed_by=actor.id,
                    )
                )
    request.status, request.reason = target, reason
    request.decided_by, request.decided_at = actor.id, time.time()
    audit(
        session,
        actor,
        request.account_id,
        f"request.{target}",
        request_id=request.id,
        reason=reason,
    )
    notify(session, request, decision=True)


def resolve_personally(
    session: Session, actor: Actor, request: BillingRequest, cancel: bool
) -> None:
    if request.kind != "job" or actor.id != request.requester_id:
        raise HTTPException(403, "Only the requester can change this print's funding")
    if request.status not in ("pending", "rejected"):
        raise HTTPException(409, "This funding request has already been resolved")
    job = session.get(PrintJob, request.source_id)
    if job is None:
        raise HTTPException(409, "The print is unavailable")
    copies = list(session.scalars(select(LabelCopy).where(LabelCopy.job_id == job.id)))
    if cancel:
        for copy in copies:
            if copy.state == State.QUEUED:
                copy.state = State.CANCELLED
    request.status = "withdrawn" if cancel else "personal"
    request.decided_by, request.decided_at = actor.id, time.time()
    audit(session, actor, request.account_id, f"request.{request.status}", request_id=request.id)
    notify(session, request, decision=True)


def cancel_empty_requests(session: Session, actor: Actor) -> None:
    """Removing all unprinted copies also withdraws their outstanding funding request."""
    session.flush()
    for request in session.scalars(
        select(BillingRequest).where(
            BillingRequest.kind == "job", BillingRequest.status == "pending"
        )
    ):
        states = list(
            session.scalars(select(LabelCopy.state).where(LabelCopy.job_id == request.source_id))
        )
        if states and all(state == State.CANCELLED for state in states):
            request.status, request.decided_by, request.decided_at = (
                "withdrawn",
                actor.id,
                time.time(),
            )
            audit(session, actor, request.account_id, "request.withdrawn", request_id=request.id)
            notify(session, request, decision=True)
