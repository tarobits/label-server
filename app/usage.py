"""Requester accounting for frozen print attempts, independent of printer protocols."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, BatchItem, Cartridge, LabelCopy, PrintJob, TapeAllocation, TapeProfile
from app.printer.base import BatchPlan


def distribute(total: int, weights: list[Decimal]) -> list[int]:
    """Largest remainder allocation; every unit belongs to exactly one requester."""
    denominator = sum(weights)
    if not denominator:
        weights = [Decimal(1)] * len(weights)
        denominator = sum(weights)
    if not weights:
        return []
    exact = [Decimal(total) * weight / denominator for weight in weights]
    allocated = [int(value) for value in exact]
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i] - allocated[i]), i))
    for index in order[: total - sum(allocated)]:
        allocated[index] += 1
    return allocated


def prepare_usage(session: Session, batch: Batch, cartridge: Cartridge, plan: BatchPlan) -> None:
    """Freeze requester shares and purchase price before any hardware commands."""
    if session.scalar(select(TapeAllocation.batch_id).where(TapeAllocation.batch_id == batch.id)):
        return
    lengths = {entry.copy_id: entry.output_length_mm for entry in plan.label_output}
    weights: dict[str, Decimal] = defaultdict(Decimal)
    names: dict[str, str] = {}
    for item in session.scalars(
        select(BatchItem).where(BatchItem.batch_id == batch.id).order_by(BatchItem.position)
    ):
        copy = session.get(LabelCopy, item.copy_id)
        assert copy is not None
        job = session.get(PrintJob, copy.job_id)
        assert job is not None
        requester = (item.attribution or {}).get("requested_by") or {}
        user_id = requester.get("id") or job.owner_id
        names[user_id] = requester.get("name") or user_id
        weights[user_id] += Decimal(str(lengths.get(item.copy_id, job.length_mm)))
    users = sorted(weights)
    # Shared leader and any strip padding follow each requester's physical label length.
    micrometres = int((Decimal(str(batch.estimated_mm)) * 1000).to_integral_value(ROUND_HALF_UP))
    shares = distribute(micrometres, [weights[user] for user in users])
    for user, share in zip(users, shares, strict=True):
        session.add(
            TapeAllocation(
                batch_id=batch.id,
                user_id=user,
                username=names[user],
                planned_mm=share / 1000,
                nominal_length_mm=cartridge.nominal_length_mm,
                price_minor=cartridge.price_minor,
                currency=cartridge.currency,
            )
        )
    session.flush()


def reassign_usage(session: Session, batch: Batch, cartridge: Cartridge) -> None:
    """Use the reviewed cartridge's price without changing frozen requester shares."""
    rows = list(session.scalars(select(TapeAllocation).where(TapeAllocation.batch_id == batch.id)))
    if any(row.consumed_mm is not None for row in rows):
        raise ValueError("This attempt's tape usage has already been settled")
    for row in rows:
        row.nominal_length_mm = cartridge.nominal_length_mm
        row.price_minor = cartridge.price_minor
        row.currency = cartridge.currency


def settle_usage(session: Session, batch: Batch, consumed_mm: float) -> None:
    rows = list(
        session.scalars(
            select(TapeAllocation)
            .where(TapeAllocation.batch_id == batch.id)
            .order_by(TapeAllocation.user_id)
        )
    )
    if not rows or all(row.consumed_mm is not None for row in rows):
        return  # Legacy attempts have no price snapshot. Settling is idempotent.
    weights = [Decimal(str(row.planned_mm)) for row in rows]
    length = Decimal(str(consumed_mm))
    lengths = distribute(int((length * 1000).to_integral_value(ROUND_HALF_UP)), weights)
    price = rows[0].price_minor
    costs = None
    if price is not None:
        total = cost_micros(consumed_mm, price, rows[0].nominal_length_mm)
        costs = distribute(total, weights)
    for index, row in enumerate(rows):
        row.consumed_mm = lengths[index] / 1000
        row.cost_micros = str(costs[index]) if costs is not None else None


def usage_report(
    session: Session, user_id: str | None, cartridge_id: str | None = None
) -> dict[str, Any]:
    query = (
        select(
            TapeAllocation,
            Batch.created_at,
            Batch.state,
            Batch.consumption_source,
            Cartridge.id,
            Cartridge.name,
            TapeProfile.name,
        )
        .join(Batch, Batch.id == TapeAllocation.batch_id)
        .join(Cartridge, Cartridge.id == Batch.cartridge_id)
        .join(TapeProfile, TapeProfile.id == Cartridge.profile_id)
    )
    if user_id is not None:
        query = query.where(TapeAllocation.user_id == user_id)
    users: dict[str, dict[str, Any]] = {}
    cartridges: dict[str, dict[str, str]] = {}
    account_costs: dict[str, dict[str, int]] = defaultdict(dict)
    entries: list[dict[str, Any]] = []
    for row, created_at, state, source, cartridge, cartridge_name, profile_name in session.execute(
        query.order_by(Batch.created_at.desc(), Batch.id, TapeAllocation.user_id).execution_options(
            yield_per=500
        )
    ):
        cartridges[cartridge] = {
            "id": cartridge,
            "name": cartridge_name,
            "profile_name": profile_name,
        }
        # Account balances include all charges, regardless of the usage filter.
        if row.consumed_mm is not None and row.cost_micros is not None:
            costs = account_costs[row.user_id]
            costs[row.currency] = costs.get(row.currency, 0) + int(row.cost_micros)
        if cartridge_id is not None and cartridge != cartridge_id:
            continue
        summary = users.setdefault(
            row.user_id,
            {
                "user_id": row.user_id,
                "username": row.username,
                "consumed_mm": 0.0,
                "pending_mm": 0.0,
                "unpriced_mm": 0.0,
                "costs": {},
            },
        )
        pending = row.consumed_mm is None
        if pending:
            summary["pending_mm"] += row.planned_mm
        else:
            summary["consumed_mm"] += row.consumed_mm
            if row.cost_micros is None:
                summary["unpriced_mm"] += row.consumed_mm
            else:
                summary["costs"][row.currency] = summary["costs"].get(row.currency, 0) + int(
                    row.cost_micros
                )
        if len(entries) < 100:
            entries.append(
                {
                    "batch_id": row.batch_id,
                    "cartridge_id": cartridge,
                    "cartridge_name": cartridge_name,
                    "profile_name": profile_name,
                    "user_id": row.user_id,
                    "username": row.username,
                    "created_at": created_at,
                    "state": state.value,
                    "planned_mm": row.planned_mm,
                    "consumed_mm": row.consumed_mm,
                    "consumption_source": source,
                    "cost": money(int(row.cost_micros)) if row.cost_micros is not None else None,
                    "currency": row.currency,
                    "price_minor": row.price_minor,
                    "nominal_length_mm": row.nominal_length_mm,
                }
            )
    from app.usage_accounts import account_report

    accounts = account_report(session, user_id, account_costs)
    for summary in users.values():
        summary["costs"] = {currency: money(value) for currency, value in summary["costs"].items()}
    return {
        "users": list(users.values()),
        "entries": entries,
        "cartridges": sorted(
            cartridges.values(), key=lambda item: (item["name"].casefold(), item["id"])
        ),
        **accounts,
    }


def money(micros: int) -> str:
    return format(Decimal(micros) / 1000000, ".6f")


def cost_micros(consumed_mm: float, price_minor: int, nominal_length_mm: float) -> int:
    return int(
        (
            Decimal(str(consumed_mm)) * price_minor * 10000 / Decimal(str(nominal_length_mm))
        ).to_integral_value(ROUND_HALF_UP)
    )
