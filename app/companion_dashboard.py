"""Content-free operational summaries for a station's own physical printers."""

import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Batch,
    BatchItem,
    Cartridge,
    LabelCopy,
    PrinterGroup,
    PrinterState,
    PrintJob,
    State,
    TapeProfile,
)


def printer_dashboard(session: Session, printer_id: str) -> dict[str, Any]:
    now = time.time()
    state = session.scalar(select(PrinterState).where(PrinterState.printer_id == printer_id))
    groups = [
        group.id
        for group in session.scalars(select(PrinterGroup))
        if printer_id in group.printer_ids
    ]
    counts = dict(
        session.execute(
            select(PrintJob.destination_id, func.count(LabelCopy.id))
            .join(LabelCopy, LabelCopy.job_id == PrintJob.id)
            .where(
                LabelCopy.state == State.QUEUED, PrintJob.destination_id.in_([printer_id, *groups])
            )
            .group_by(PrintJob.destination_id)
        ).all()
    )
    stock = (
        session.get(Cartridge, state.active_cartridge_id)
        if state and state.active_cartridge_id
        else None
    )
    profile = session.get(TapeProfile, stock.profile_id) if stock else None
    current = session.scalar(
        select(Batch)
        .where(Batch.printer_id == printer_id, Batch.state == State.PRINTING)
        .order_by(Batch.created_at.desc())
        .limit(1)
    )
    latest = session.scalar(
        select(Batch)
        .where(Batch.printer_id == printer_id, Batch.finished_at.is_not(None))
        .order_by(Batch.finished_at.desc())
        .limit(1)
    )

    def batch_summary(batch: Batch | None) -> dict[str, Any] | None:
        if batch is None:
            return None
        total = (
            session.scalar(
                select(func.count()).select_from(BatchItem).where(BatchItem.batch_id == batch.id)
            )
            or 0
        )
        confirmed = (
            session.scalar(
                select(func.count())
                .select_from(BatchItem)
                .where(BatchItem.batch_id == batch.id, BatchItem.outcome == State.PRINTED)
            )
            or 0
        )
        return {
            "state": batch.state.value,
            "total_labels": total,
            "confirmed_labels": confirmed,
            "finished_at": batch.finished_at,
        }

    printed = (
        session.scalar(
            select(func.count())
            .select_from(BatchItem)
            .join(Batch, Batch.id == BatchItem.batch_id)
            .where(
                Batch.printer_id == printer_id,
                Batch.finished_at >= now - 86400,
                BatchItem.outcome == State.PRINTED,
            )
        )
        or 0
    )
    return {
        "held": bool(state and state.automatic_printing_held),
        "cartridge_check_pending": bool(state and state.cartridge_check_pending),
        "queued_labels": counts.get(printer_id, 0),
        "shared_queued_labels": sum(counts.get(identifier, 0) for identifier in groups),
        "printed_last_24h": printed,
        "cartridge": {
            "name": stock.name,
            "remaining_mm": stock.remaining_mm,
            "nominal_length_mm": stock.nominal_length_mm,
            "uncertain": stock.consumption_uncertain,
            "profile_name": profile.name if profile else None,
            "width_mm": profile.width_mm if profile else None,
            "foreground": profile.foreground if profile else None,
            "background": profile.background if profile else None,
        }
        if stock
        else None,
        "active_batch": batch_summary(current),
        "last_batch": batch_summary(latest),
    }
