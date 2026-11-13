"""Pairwise owner accounts; recipients can acknowledge repayments to themselves."""

import time
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.accounts import billing  # noqa: F401
from app.accounts.cartridge_debts import cartridge_balances, repayment_allocations
from app.accounts.usage import money
from app.accounts.usage_accounts import (
    AdjustmentInput,
    account_names,
    adjust_account,
    pairwise_report,
)
from app.audit.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.authn.access import access_context
from app.http import db, record
from app.i18n import Message
from app.models import (
    Batch,
    Cartridge,
    PaymentReport,
    TapeAllocation,
    UsageAdjustment,
    User,
    new_id,
)
from app.transaction_routes import TransactionRouter

router = TransactionRouter(prefix="/api/accounts", tags=["owner accounting"])
DB = Annotated[Session, Depends(db, scope="function")]


@router.get("")
def accounts(
    request: Request, session: DB, all_users: bool = False, user_id: str | None = None
) -> dict[str, Any]:
    context = access_context(request)
    if (all_users or user_id not in (None, context.actor.id)) and not context.has_permission(
        "usage.view_others"
    ):
        raise HTTPException(403, Message("serverMessages.viewingOtherUsersAccountsIsNotPermitted"))
    if all_users and user_id is not None:
        raise HTTPException(422, Message("serverMessages.chooseAllAccountsOrAnIndividualAccount"))
    viewer = None if all_users else user_id or context.actor.id
    allocations = (
        select(TapeAllocation, Batch.created_at, Cartridge.name)
        .join(Batch, TapeAllocation.batch_id == Batch.id)
        .join(Cartridge, Cartridge.id == TapeAllocation.cartridge_id)
    )
    adjustments = select(UsageAdjustment)
    reports = select(PaymentReport)
    if viewer is not None:
        allocations = allocations.where(
            or_(TapeAllocation.user_id == viewer, TapeAllocation.recipient_id == viewer)
        )
        adjustments = adjustments.where(
            or_(UsageAdjustment.user_id == viewer, UsageAdjustment.recipient_id == viewer)
        )
        if not context.has_permission("usage.edit_accounts"):
            reports = reports.where(
                or_(PaymentReport.user_id == viewer, PaymentReport.recipient_id == viewer)
            )
    group_balances, group_cartridges = billing.usage_balances(session, context.actor, viewer)
    return {
        "payment_reports": [
            payment_report_record(row, request)
            for row in session.scalars(
                reports.order_by(
                    (PaymentReport.status == "pending").desc(), PaymentReport.created_at.desc()
                ).limit(100)
            )
        ],
        "group_balances": group_balances,
        "group_cartridge_balances": group_cartridges,
        "balances": pairwise_report(session, viewer)
        + [
            {**row, "recipient_name": row["cartridge_name"]}
            for row in cartridge_balances(session, viewer)
            if row["recipient_id"] is None
        ],
        "cartridge_balances": cartridge_balances(session, viewer),
        "adjustments": [
            record(row)
            for row in session.scalars(
                adjustments.order_by(UsageAdjustment.created_at.desc()).limit(100)
            )
        ],
        "charges": [
            {
                "batch_id": row.batch_id,
                "requester_id": row.user_id,
                "requester_name": row.username,
                "recipient_id": row.recipient_id,
                "recipient_name": row.recipient_name,
                "recipient_assigned_at": row.recipient_assigned_at,
                "cartridge_id": row.cartridge_id,
                "cartridge_name": name,
                "created_at": stamp,
                "currency": row.currency,
                "actual_cost": money(int(row.cost_micros)) if row.cost_micros is not None else None,
                "charged": money(int(row.charged_micros))
                if row.charged_micros is not None
                else None,
                "consumed_mm": row.consumed_mm,
                "own_cartridge": row.user_id == row.recipient_id,
            }
            for row, stamp, name in session.execute(
                allocations.order_by(Batch.created_at.desc(), TapeAllocation.batch_id).limit(100)
            )
        ],
    }


@router.get("/parties")
def parties(request: Request, session: DB) -> list[dict[str, str]]:
    access_context(request)
    return [
        {"user_id": identifier, "username": name}
        for identifier, name in sorted(
            account_names(session).items(), key=lambda pair: pair[1].casefold()
        )
    ]


def record_repayment(request: Request, session: Session, body: AdjustmentInput) -> UsageAdjustment:
    context = access_context(request)
    if body.amount_minor < 0 and not context.has_permission("usage.edit_accounts"):
        raise HTTPException(
            403, Message("serverMessages.onlyAnAccountingEditorMaySubtractFromABalance")
        )
    if body.recipient_id != context.actor.id and not context.has_permission("usage.edit_accounts"):
        raise HTTPException(
            403,
            Message("serverMessages.onlyTheRecipientOrAnAccountingEditorMayRecordThisRepayment"),
        )
    existing = session.get(UsageAdjustment, str(body.request_id))
    adjustment = adjust_account(session, context.actor, body)
    if existing is not None:
        return adjustment
    rule = (AuditRequirement("application", "", "usage.view_others"),)
    append_audit(
        session,
        event_id=new_id(),
        action="account.adjusted",
        outcome="succeeded",
        occurred_at=time.time(),
        scopes=(AuditScope("global"),),
        fields={
            "actor_id": AuditField(context.actor.id, ()),
            "actor_name": AuditField(context.actor.username, ()),
            "victim_ids": AuditField([body.user_id, body.recipient_id], rule),
            "adjustment_id": AuditField(adjustment.id, rule),
            "recipient_id": AuditField(body.recipient_id, rule),
            "amount_minor": AuditField(body.amount_minor, rule),
            "currency": AuditField(body.currency, rule),
        },
    )
    for cartridge_id, amount in adjustment.cartridge_allocations.items():
        append_audit(
            session,
            event_id=new_id(),
            action="account.repayment_allocated",
            outcome="succeeded",
            occurred_at=time.time(),
            scopes=(AuditScope("cartridge", cartridge_id),),
            fields={
                "actor_id": AuditField(context.actor.id, ()),
                "actor_name": AuditField(context.actor.username, ()),
                "victim_ids": AuditField([body.user_id, body.recipient_id], rule),
                "adjustment_id": AuditField(adjustment.id, rule),
                "recipient_id": AuditField(body.recipient_id, rule),
                "allocated_micros": AuditField(int(amount), rule),
                "currency": AuditField(body.currency, rule),
            },
        )
    return adjustment


@router.post("/repayments", status_code=201)
def repayment(body: AdjustmentInput, request: Request, session: DB) -> dict[str, Any]:
    return record(record_repayment(request, session, body))


@router.post("/repayments/preview")
def repayment_preview(body: AdjustmentInput, request: Request, session: DB) -> dict[str, Any]:
    context = access_context(request)
    if body.amount_minor < 0 and not context.has_permission("usage.edit_accounts"):
        raise HTTPException(
            403, Message("serverMessages.onlyAnAccountingEditorMaySubtractFromABalance")
        )
    if body.recipient_id != context.actor.id and not context.has_permission("usage.edit_accounts"):
        raise HTTPException(
            403, Message("serverMessages.onlyTheRecipientOrAnAccountingEditorMayAllocateARepayment")
        )
    balances = [
        row
        for row in cartridge_balances(session, body.user_id)
        if row["requester_id"] == body.user_id
        and row["recipient_id"] == body.recipient_id
        and row["currency"] == body.currency
    ]
    return {
        "cartridges": balances,
        "allocations": repayment_allocations(
            session, body.user_id, body.recipient_id, body.currency, body.amount_minor * 10000
        ),
    }


class PaymentReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    recipient_id: str = Field(min_length=1, max_length=100)
    amount_minor: int = Field(strict=True, ge=1, le=1_000_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    note: str = Field(min_length=1, max_length=500)


def payment_report_record(report: PaymentReport, request: Request) -> dict[str, Any]:
    context = access_context(request)
    return {
        **record(report),
        "can_review": report.status == "pending"
        and (
            report.recipient_id == context.actor.id or context.has_permission("usage.edit_accounts")
        ),
        "can_cancel": report.status == "pending" and report.user_id == context.actor.id,
    }


def payment_audit(session: Session, report: PaymentReport, action: str) -> None:
    from app.audit.action_audit import record_action

    record_action(
        session,
        f"payment.{action}",
        "global",
        "",
        {
            "report_id": report.id,
            "amount_minor": report.amount_minor,
            "currency": report.currency,
            "victim_ids": [report.user_id, report.recipient_id],
        },
    )


def require_payment_accounts(session: Session, *identifiers: str) -> None:
    from app.maintenance.deletion import is_deleted

    for identifier in identifiers:
        if session.get(User, identifier) is None or is_deleted(session, "users", identifier):
            raise HTTPException(
                409, Message("serverMessages.bothPaymentAccountsMustExistAndNotBeDeleted")
            )


@router.post("/payment-reports", status_code=201)
def report_payment(body: PaymentReportInput, request: Request, session: DB) -> dict[str, Any]:
    actor = access_context(request).actor
    identifier = str(body.request_id)
    existing = session.get(PaymentReport, identifier)
    if existing is not None:
        if existing.user_id != actor.id or any(
            getattr(existing, key) != getattr(body, key)
            for key in ("recipient_id", "amount_minor", "currency", "note")
        ):
            raise HTTPException(
                409, Message("serverMessages.thisPaymentReferenceHasAlreadyBeenUsed")
            )
        return payment_report_record(existing, request)
    if session.get(UsageAdjustment, identifier) is not None:
        raise HTTPException(409, Message("serverMessages.thisPaymentReferenceHasAlreadyBeenUsed"))
    if body.recipient_id == actor.id:
        raise HTTPException(422, Message("serverMessages.chooseADifferentPayerAndRecipient"))
    require_payment_accounts(session, actor.id, body.recipient_id)
    recipient = session.get(User, body.recipient_id)
    assert recipient is not None
    report = PaymentReport(
        id=identifier,
        user_id=actor.id,
        username=actor.username,
        recipient_id=body.recipient_id,
        recipient_name=recipient.username,
        amount_minor=body.amount_minor,
        currency=body.currency,
        note=body.note,
    )
    session.add(report)
    session.flush()
    payment_audit(session, report, "reported")
    return payment_report_record(report, request)


@router.post("/payment-reports/{identifier}/{decision}")
def review_payment(
    identifier: str, decision: Literal["approve", "reject", "cancel"], request: Request, session: DB
) -> dict[str, Any]:
    report = session.scalar(
        select(PaymentReport).where(PaymentReport.id == identifier).with_for_update()
    )
    if report is None:
        raise HTTPException(404, Message("serverMessages.paymentReportNotFound"))
    context = access_context(request)
    if decision == "cancel":
        allowed = report.user_id == context.actor.id
    else:
        allowed = report.recipient_id == context.actor.id or context.has_permission(
            "usage.edit_accounts"
        )
    if not allowed:
        raise HTTPException(
            403,
            Message(
                "serverMessages.onlyTheRecipientOrAnAccountingEditorMayReviewAPaymentOnlyItsPayerMayCancelIt"
            ),
        )
    status = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[decision]
    if report.status != "pending":
        if report.status != status:
            raise HTTPException(
                409, Message("serverMessages.thisPaymentReportHasAlreadyBeenResolved")
            )
        return payment_report_record(report, request)
    if decision == "approve":
        require_payment_accounts(session, report.user_id, report.recipient_id)
        if session.get(UsageAdjustment, identifier) is not None:
            raise HTTPException(
                409, Message("serverMessages.thisPaymentReferenceHasAlreadyBeenUsed")
            )
        record_repayment(
            request,
            session,
            AdjustmentInput(
                request_id=UUID(identifier),
                user_id=report.user_id,
                recipient_id=report.recipient_id,
                amount_minor=report.amount_minor,
                currency=report.currency,
                note=report.note,
            ),
        )
    report.status = status
    report.reviewed_at = time.time()
    report.reviewer_id, report.reviewer_name = context.actor.id, context.actor.username
    payment_audit(session, report, status)
    session.flush()
    return payment_report_record(report, request)
