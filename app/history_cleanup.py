"""Permanent removal of redundant, known-not-started print attempts."""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.http import job_template_name
from app.models import (
    Batch,
    BatchItem,
    LabelCopy,
    Notification,
    NotificationDelivery,
    PrintJob,
    State,
    TapeAllocation,
)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@dataclass
class DuplicateHistory:
    groups: list[dict[str, Any]]
    batch_ids: list[str]
    notification_ids: list[str]
    delivery_ids: list[str]
    item_count: int
    allocation_count: int

    def preview(self) -> dict[str, Any]:
        result = {
            "groups": self.groups,
            "batches": len(self.batch_ids),
            "items": self.item_count,
            "allocations": self.allocation_count,
            "notifications": len(self.notification_ids),
            "deliveries": len(self.delivery_ids),
        }
        return {
            **result,
            "confirmation": fingerprint(
                [result, self.batch_ids, self.notification_ids, self.delivery_ids]
            ),
        }


def duplicate_history(session: Session) -> DuplicateHistory:
    # FAILED alone is insufficient: review can also settle a partial print as
    # failed. No-start failures have no consumption source and failed items.
    eligible = select(Batch.id).where(
        Batch.state == State.FAILED,
        Batch.finished_at.is_not(None),
        Batch.error.is_not(None),
        Batch.consumed_mm.is_(None),
        Batch.consumption_source.is_(None),
    )
    items: dict[str, list[BatchItem]] = defaultdict(list)
    allocations: dict[str, list[TapeAllocation]] = defaultdict(list)
    for item in session.scalars(
        select(BatchItem)
        .where(BatchItem.batch_id.in_(eligible))
        .order_by(BatchItem.position, BatchItem.copy_id)
    ):
        items[item.batch_id].append(item)
    for allocation in session.scalars(
        select(TapeAllocation).where(TapeAllocation.batch_id.in_(eligible))
    ):
        allocations[allocation.batch_id].append(allocation)

    matches: dict[str, list[Batch]] = defaultdict(list)
    for batch in session.scalars(
        select(Batch).where(Batch.id.in_(eligible)).order_by(Batch.created_at, Batch.id)
    ):
        batch_items = items[batch.id]
        if not batch_items or any(item.outcome != State.FAILED for item in batch_items):
            continue
        # Missing allocations are normal for legacy/rendering failures. Existing
        # allocations must be settled at zero, never pending, charged or uncertain.
        if any(
            row.consumed_mm != 0 or row.cost_micros not in (None, "0")
            for row in allocations[batch.id]
        ):
            continue
        trigger = dict(batch.trigger or {})
        if trigger.get("kind") == "automatic":
            trigger.pop("at", None)  # Automatic retries have a new poll timestamp.
        signature = fingerprint(
            [
                batch.printer_id,
                batch.cartridge_id,
                batch.error,
                trigger,  # Separate explicit manual requests remain separate.
                batch.estimated_mm,
                batch.print_plan,
                batch.shortage_warning,
                [(item.copy_id, item.position, item.attribution) for item in batch_items],
            ]
        )
        matches[signature].append(batch)

    groups: list[dict[str, Any]] = []
    batch_ids: list[str] = []
    for group in matches.values():
        if len(group) < 2:
            continue
        first = group[0]
        names = []
        for job in session.scalars(
            select(PrintJob)
            .join(LabelCopy, LabelCopy.job_id == PrintJob.id)
            .join(BatchItem, BatchItem.copy_id == LabelCopy.id)
            .where(BatchItem.batch_id == first.id)
            .order_by(BatchItem.position)
        ).unique():
            name = job.template_snapshot.get("process_name") or job_template_name(session, job)
            if name not in names:
                names.append(name)
        groups.append(
            {
                "retained_batch_id": first.id,
                "process_names": names,
                "printer_id": first.printer_id,
                "cartridge_id": first.cartridge_id,
                "error": first.error,
                "copies": len(items[first.id]),
                "duplicates": len(group) - 1,
                "first_at": first.created_at,
                "last_at": group[-1].created_at,
            }
        )
        batch_ids.extend(batch.id for batch in group[1:])

    # Delete only notices explicitly linked to removed attempts. Printer-blocked
    # alerts have no batch link and may describe separate incidents; retain them.
    notification_ids: list[str] = []
    delivery_ids: list[str] = []
    for start in range(0, len(batch_ids), 400):
        chunk = batch_ids[start : start + 400]
        notification_ids.extend(
            session.scalars(
                select(Notification.id).where(
                    or_(
                        Notification.context["batch_id"].as_string().in_(chunk),
                        Notification.path.in_([f"/#/batches/{identifier}" for identifier in chunk]),
                    )
                )
            )
        )
    notification_ids = sorted(set(notification_ids))
    for start in range(0, len(notification_ids), 400):
        delivery_ids.extend(
            session.scalars(
                select(NotificationDelivery.id).where(
                    NotificationDelivery.notification_id.in_(notification_ids[start : start + 400])
                )
            )
        )
    return DuplicateHistory(
        groups=groups,
        batch_ids=sorted(batch_ids),
        notification_ids=notification_ids,
        delivery_ids=sorted(delivery_ids),
        item_count=sum(len(items[identifier]) for identifier in batch_ids),
        allocation_count=sum(len(allocations[identifier]) for identifier in batch_ids),
    )


def purge_duplicate_history(session: Session, confirmation: str) -> dict[str, Any]:
    """Caller holds the mutation lock and transaction across recheck and deletion."""
    plan = duplicate_history(session)
    preview = plan.preview()
    if confirmation != preview["confirmation"]:
        raise ValueError("Duplicate history changed. Review a fresh preview before purging.")
    for start in range(0, len(plan.notification_ids), 400):
        chunk = plan.notification_ids[start : start + 400]
        session.execute(
            delete(NotificationDelivery).where(NotificationDelivery.notification_id.in_(chunk))
        )
        session.execute(delete(Notification).where(Notification.id.in_(chunk)))
    for start in range(0, len(plan.batch_ids), 400):
        chunk = plan.batch_ids[start : start + 400]
        session.execute(delete(TapeAllocation).where(TapeAllocation.batch_id.in_(chunk)))
        session.execute(delete(BatchItem).where(BatchItem.batch_id.in_(chunk)))
        session.execute(delete(Batch).where(Batch.id.in_(chunk)))
    return {
        key: preview[key]
        for key in ("batches", "items", "allocations", "notifications", "deliveries")
    }
