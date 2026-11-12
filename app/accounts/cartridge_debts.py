"""Charges keep their cartridge identity while unassigned ownership is resolved."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.usage import money
from app.authn.ownership import owner_at
from app.models import Batch, Cartridge, ResourceOwnership, TapeAllocation, UsageAdjustment


def recipient_at(
    session: Session, cartridge: Cartridge, stamp: float
) -> tuple[str | None, str | None, float | None]:
    identifier, name = owner_at(session, cartridge, stamp)
    if identifier:
        return identifier, name, None
    # A reviewed attempt may finish after its previously ownerless cartridge was
    # claimed. The first following owner receives that gap's charges, never a later one.
    following = session.scalar(
        select(ResourceOwnership)
        .where(
            ResourceOwnership.kind == "cartridge",
            ResourceOwnership.resource_id == cartridge.id,
            ResourceOwnership.effective_at > stamp,
        )
        .order_by(ResourceOwnership.effective_at)
        .limit(1)
    )
    return (
        (following.owner_id, following.owner_name, following.effective_at)
        if following
        else (None, None, None)
    )


def assign_unowned(session: Session, cartridge: Cartridge, actor_id: str, actor_name: str) -> None:
    import time

    from app.audit.audit import AuditField, AuditRequirement, AuditScope, append_audit
    from app.models import new_id

    for row, stamp in session.execute(
        select(TapeAllocation, Batch.created_at)
        .join(Batch, Batch.id == TapeAllocation.batch_id)
        .where(TapeAllocation.cartridge_id == cartridge.id, TapeAllocation.recipient_id.is_(None))
    ):
        recipient, name, assigned_at = recipient_at(session, cartridge, stamp)
        if not recipient:
            continue
        row.recipient_id, row.recipient_name = recipient, name
        row.recipient_assigned_at = assigned_at or time.time()
        from app.accounts.billing_models import BillingCharge

        for charge in session.scalars(
            select(BillingCharge).where(
                BillingCharge.batch_id == row.batch_id,
                BillingCharge.requester_id == row.user_id,
                BillingCharge.recipient_id.is_(None),
            )
        ):
            charge.recipient_id, charge.recipient_name = recipient, name
            from app.accounts.billing import audit as billing_audit
            from app.authn.access import Actor

            billing_audit(
                session,
                Actor(id=actor_id, username=actor_name),
                charge.account_id,
                "creditor.assigned",
                charge_id=charge.id,
                recipient_id=recipient,
            )
        if (
            row.cost_micros is not None
            and row.charged_micros is not None
            and int(row.cost_micros) > int(row.charged_micros)
        ):
            from app.notifications.notifications import enqueue

            enqueue(
                session,
                "Assigned cartridge cost reduction",
                f"An assigned charge used {money(int(row.cost_micros))} {row.currency} of tape and charged {money(int(row.charged_micros))} {row.currency}.",
                "/#/usage",
                recipient_id=recipient,
                context={"batch_id": row.batch_id},
            )
        guard = (AuditRequirement("application", "", "usage.view_others"),)
        append_audit(
            session,
            event_id=new_id(),
            action="cartridge.debt_assigned",
            outcome="succeeded",
            occurred_at=time.time(),
            scopes=(AuditScope("cartridge", cartridge.id),),
            fields={
                "actor_id": AuditField(actor_id, ()),
                "actor_name": AuditField(actor_name, ()),
                "victim_ids": AuditField([row.user_id, recipient], guard),
                "batch_id": AuditField(row.batch_id, guard),
                "recipient_id": AuditField(recipient, guard),
            },
        )


def cartridge_balances(
    session: Session, viewer_id: str | None = None, *, include_schedule: bool = False
) -> list[dict[str, Any]]:
    from app.accounts.billing import offsets

    transferred = offsets(session)
    totals: dict[tuple[str, str | None, str, str], dict[str, Any]] = {}
    for allocation, stamp, name in session.execute(
        select(TapeAllocation, Batch.created_at, Cartridge.name)
        .join(Batch, Batch.id == TapeAllocation.batch_id)
        .join(Cartridge, Cartridge.id == TapeAllocation.cartridge_id)
        .order_by(Batch.created_at, Batch.id)
    ):
        if allocation.charged_micros is None or allocation.user_id == allocation.recipient_id:
            continue
        if viewer_id is not None and viewer_id not in (allocation.user_id, allocation.recipient_id):
            continue
        key = (
            allocation.user_id,
            allocation.recipient_id,
            allocation.cartridge_id or "",
            allocation.currency,
        )
        entry = totals.setdefault(
            key,
            {
                "requester_id": allocation.user_id,
                "requester_name": allocation.username,
                "recipient_id": allocation.recipient_id,
                "recipient_name": allocation.recipient_name,
                "cartridge_id": allocation.cartridge_id,
                "cartridge_name": name,
                "currency": allocation.currency,
                "oldest_at": stamp,
                "micros": 0,
                "_charges": [],
                "_payments": 0,
            },
        )
        personal = int(allocation.charged_micros) - transferred.get(
            (allocation.batch_id, allocation.user_id), 0
        )
        entry["micros"] += personal
        entry["_charges"].append((stamp, personal))
    for adjustment in session.scalars(select(UsageAdjustment)):
        if viewer_id is not None and viewer_id not in (adjustment.user_id, adjustment.recipient_id):
            continue
        for cartridge, amount in (adjustment.cartridge_allocations or {}).items():
            key = (adjustment.user_id, adjustment.recipient_id, cartridge, adjustment.currency)
            if key in totals:
                totals[key]["micros"] -= int(amount)
                totals[key]["_payments"] += int(amount)
    for entry in totals.values():
        payments = entry.pop("_payments")
        outstanding = []
        for stamp, amount in entry.pop("_charges"):
            offset = min(max(0, payments), amount)
            payments -= offset
            if amount > offset:
                outstanding.append((stamp, amount - offset))
        if payments < 0:
            outstanding.insert(0, (entry["oldest_at"], -payments))
        if outstanding:
            entry["oldest_at"] = outstanding[0][0]
        if include_schedule:
            entry["_outstanding"] = outstanding
    return [
        {**entry, "owed": money(entry["micros"])}
        for entry in sorted(
            totals.values(), key=lambda row: (row["oldest_at"], row["cartridge_id"])
        )
    ]


def repayment_allocations(
    session: Session,
    payer: str,
    recipient: str,
    currency: str,
    amount: int,
    selected: dict[str, int] | None = None,
) -> dict[str, int]:
    balances = [
        row
        for row in cartridge_balances(session, payer, include_schedule=True)
        if row["requester_id"] == payer
        and row["recipient_id"] == recipient
        and row["currency"] == currency
    ]
    if selected is not None:
        eligible = {row["cartridge_id"] for row in balances}
        if any(
            key not in eligible
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value == 0
            or (value > 0) != (amount > 0)
            for key, value in selected.items()
        ) or abs(sum(selected.values())) > abs(amount):
            raise HTTPException(
                422,
                "Choose cartridges from this account and currency, with allocations within the payment amount",
            )
        return selected
    if amount < 0:
        return {}  # Corrections without a selected cartridge remain pair-level credits/debits.
    remaining = amount
    result: dict[str, int] = {}
    schedule = sorted(
        (stamp, row["cartridge_id"], value)
        for row in balances
        for stamp, value in row["_outstanding"]
    )
    for _, cartridge, value in schedule:
        allocated = min(remaining, value)
        if allocated:
            result[cartridge] = result.get(cartridge, 0) + allocated
            remaining -= allocated
        if not remaining:
            break
    return result
