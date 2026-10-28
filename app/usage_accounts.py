"""Auditable account adjustments, independent of immutable printing charges."""

from typing import Any
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
    amount_minor: int = Field(strict=True, ge=-1_000_000_000, le=1_000_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    note: str = Field(min_length=1, max_length=500)

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
    if existing is not None:
        if existing.actor_id != actor.id or any(
            getattr(existing, key) != getattr(body, key)
            for key in ("user_id", "amount_minor", "currency", "note")
        ):
            raise HTTPException(409, "This adjustment reference has already been used")
        return existing  # Retrying an uncertain response never records another payment.
    name = account_names(session, body.user_id).get(body.user_id)
    if name is None:
        raise HTTPException(404, "Usage account not found")
    adjustment = UsageAdjustment(
        id=identifier,
        user_id=body.user_id,
        username=name,
        actor_id=actor.id,
        actor_name=actor.username,
        amount_minor=body.amount_minor,
        currency=body.currency,
        note=body.note,
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
