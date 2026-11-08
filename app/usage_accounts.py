"""Auditable account adjustments, independent of immutable printing charges."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import Actor
from app.models import TapeAllocation, UsageAdjustment, User


class AdjustmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: UUID
    user_id: str = Field(min_length=1, max_length=100)
    recipient_id: str = Field(min_length=1, max_length=100)
    amount_minor: int = Field(strict=True, ge=-1_000_000_000, le=1_000_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    note: str = Field(min_length=1, max_length=500)
    cartridge_allocations: (
        dict[str, Annotated[int, Field(strict=True, ge=-(10**15), le=10**15)]] | None
    ) = Field(default=None, max_length=1000)

    @field_validator("amount_minor")
    @classmethod
    def nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Enter a non-zero adjustment")
        return value


def account_names(session: Session, user_id: str | None = None) -> dict[str, str]:
    """Include accounts with no printing yet, and retained historical identities."""
    names: dict[str, str] = {}
    for model in (UsageAdjustment, TapeAllocation):
        query = select(model.user_id, model.username).distinct()
        if user_id is not None:
            query = query.where(model.user_id == user_id)
        for identifier, username in session.execute(query):
            names[identifier] = username
    users = select(User.id, User.username)
    if user_id is not None:
        users = users.where(User.id == user_id)
    names.update(session.execute(users).all())
    return names


def adjust_account(session: Session, actor: Actor, body: AdjustmentInput) -> UsageAdjustment:
    identifier = str(body.request_id)
    existing = session.get(UsageAdjustment, identifier)
    requested = (
        {key: str(value) for key, value in sorted(body.cartridge_allocations.items())}
        if body.cartridge_allocations is not None
        else None
    )
    if existing is not None:
        if (
            existing.requested_allocations != requested
            or existing.actor_id != actor.id
            or any(
                getattr(existing, key) != getattr(body, key)
                for key in ("user_id", "recipient_id", "amount_minor", "currency", "note")
            )
        ):
            raise HTTPException(409, "This adjustment reference has already been used")
        return existing  # Retrying an uncertain response never records another payment.
    name = account_names(session, body.user_id).get(body.user_id)
    if name is None:
        raise HTTPException(404, "Usage account not found")
    recipient = account_names(session, body.recipient_id).get(body.recipient_id)
    if recipient is None:
        raise HTTPException(404, "Recipient account not found")
    if body.recipient_id == body.user_id:
        raise HTTPException(422, "Choose a different payer and recipient")
    from app.cartridge_debts import repayment_allocations

    allocations = repayment_allocations(
        session,
        body.user_id,
        body.recipient_id,
        body.currency,
        body.amount_minor * 10000,
        body.cartridge_allocations,
    )
    adjustment = UsageAdjustment(
        id=identifier,
        user_id=body.user_id,
        username=name,
        recipient_id=body.recipient_id,
        recipient_name=recipient,
        actor_id=actor.id,
        actor_name=actor.username,
        amount_minor=body.amount_minor,
        currency=body.currency,
        note=body.note,
        cartridge_allocations={key: str(value) for key, value in allocations.items()},
        requested_allocations=requested,
    )
    session.add(adjustment)
    session.flush()
    return adjustment


def account_report(
    session: Session, user_id: str | None, costs: dict[str, dict[str, int]]
) -> dict[str, Any]:
    from app.http import record
    from app.usage import money

    names = account_names(session, user_id)
    if user_id is not None:
        # Also support explicit local test identities without a User record.
        names.setdefault(user_id, user_id)
    balances = {
        identifier: {key: -value for key, value in cost.items()}
        for identifier, cost in costs.items()
    }
    query = select(UsageAdjustment)
    if user_id is not None:
        query = query.where(UsageAdjustment.user_id == user_id)
    adjustments: list[dict[str, Any]] = []
    for adjustment in session.scalars(
        query.order_by(UsageAdjustment.created_at.desc(), UsageAdjustment.id).execution_options(
            yield_per=500
        )
    ):
        balance = balances.setdefault(adjustment.user_id, {})
        balance[adjustment.currency] = (
            balance.get(adjustment.currency, 0) + adjustment.amount_minor * 10000
        )
        if len(adjustments) < 100:
            adjustments.append(record(adjustment))
    return {
        "accounts": [
            {
                "user_id": identifier,
                "username": name,
                "balances": {
                    key: money(value) for key, value in balances.get(identifier, {}).items()
                },
            }
            for identifier, name in sorted(
                names.items(), key=lambda item: (item[1].casefold(), item[0])
            )
        ],
        "adjustments": adjustments,
    }


def pairwise_report(session: Session, viewer_id: str | None = None) -> list[dict[str, Any]]:
    """Positive amounts are owed by requester to owner; currencies never mix."""
    from app.usage import money

    totals: dict[tuple[str, str, str], int] = {}
    unallocated: dict[tuple[str, str, str], int] = {}
    names = account_names(session)
    for row in session.scalars(select(TapeAllocation)):
        if row.recipient_id is None or row.user_id == row.recipient_id:
            continue
        if viewer_id is not None and viewer_id not in (row.user_id, row.recipient_id):
            continue
        if row.charged_micros is None:
            continue
        names.setdefault(row.recipient_id, row.recipient_name or row.recipient_id)
        key = (row.user_id, row.recipient_id, row.currency)
        totals[key] = totals.get(key, 0) + int(row.charged_micros)
    for adjustment in session.scalars(select(UsageAdjustment)):
        if adjustment.recipient_id is None or adjustment.user_id == adjustment.recipient_id:
            continue
        if viewer_id is not None and viewer_id not in (adjustment.user_id, adjustment.recipient_id):
            continue
        names.setdefault(
            adjustment.recipient_id, adjustment.recipient_name or adjustment.recipient_id
        )
        key = (adjustment.user_id, adjustment.recipient_id, adjustment.currency)
        totals[key] = totals.get(key, 0) - adjustment.amount_minor * 10000
        remainder = adjustment.amount_minor * 10000 - sum(
            int(value) for value in (adjustment.cartridge_allocations or {}).values()
        )
        unallocated[key] = unallocated.get(key, 0) - remainder
    return [
        {
            "requester_id": debtor,
            "requester_name": names.get(debtor, debtor),
            "recipient_id": creditor,
            "recipient_name": names.get(creditor, creditor),
            "currency": currency,
            "owed": money(amount),
            "unallocated_owed": money(unallocated.get((debtor, creditor, currency), 0)),
        }
        for (debtor, creditor, currency), amount in sorted(totals.items())
    ]
