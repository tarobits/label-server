"""Pairwise owner accounts; recipients can acknowledge repayments to themselves."""

import time
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import billing
from app.access import access_context
from app.audit import AuditField, AuditRequirement, AuditScope, append_audit
from app.cartridge_debts import cartridge_balances, repayment_allocations
from app.http import db, record
from app.models import Batch, Cartridge, TapeAllocation, UsageAdjustment, new_id
from app.transaction_routes import TransactionRouter
from app.usage import money
from app.usage_accounts import AdjustmentInput, account_names, adjust_account, pairwise_report

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
        raise HTTPException(403, "Viewing other users' accounts is not permitted")
    if all_users and user_id is not None:
        raise HTTPException(422, "Choose all accounts or an individual account")
    viewer = None if all_users else user_id or context.actor.id
    allocations = (
        select(TapeAllocation, Batch.created_at, Cartridge.name)
        .join(Batch, TapeAllocation.batch_id == Batch.id)
        .join(Cartridge, Cartridge.id == TapeAllocation.cartridge_id)
    )
    adjustments = select(UsageAdjustment)
    if viewer is not None:
        allocations = allocations.where(
            or_(TapeAllocation.user_id == viewer, TapeAllocation.recipient_id == viewer)
        )
        adjustments = adjustments.where(
            or_(UsageAdjustment.user_id == viewer, UsageAdjustment.recipient_id == viewer)
        )
    group_balances, group_cartridges = billing.usage_balances(session, context.actor, viewer)
    return {
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
    if body.recipient_id != context.actor.id and not context.has_permission("usage.edit_accounts"):
        raise HTTPException(
            403, "Only the recipient or an accounting editor may record this repayment"
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
    if body.recipient_id != context.actor.id and not context.has_permission("usage.edit_accounts"):
        raise HTTPException(
            403, "Only the recipient or an accounting editor may allocate a repayment"
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
