"""Inventory lifecycle guards; historical consumption remains attached to cartridges."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, Cartridge, FlushRequest, PrinterState, State


def archive_blockers(session: Session) -> dict[str, str]:
    blocked = {
        identifier: "Remove this cartridge from the printer before archiving it."
        for identifier in session.scalars(select(PrinterState.active_cartridge_id))
        if identifier is not None
    }
    for identifier, state in session.execute(
        select(Batch.cartridge_id, Batch.state).where(
            Batch.state.in_([State.PRINTING, State.NEEDS_REVIEW])
        )
    ):
        blocked.setdefault(
            identifier,
            "Finish printing before archiving this cartridge."
            if state == State.PRINTING
            else "Resolve the pending review before archiving this cartridge.",
        )
    for identifier in session.scalars(
        select(FlushRequest.cartridge_id).where(FlushRequest.completed.is_(False))
    ):
        blocked.setdefault(
            identifier, "Cancel or finish the pending print before archiving this cartridge."
        )
    for identifier in session.scalars(
        select(Cartridge.id).where(Cartridge.consumption_uncertain.is_(True))
    ):
        blocked.setdefault(
            identifier, "Reconcile uncertain tape consumption before archiving this cartridge."
        )
    return blocked


def deletion_blockers(session: Session, archive_reasons: dict[str, str]) -> dict[str, str]:
    blocked = {
        key: reason.replace("archiving", "deleting") for key, reason in archive_reasons.items()
    }
    for model in (Batch, FlushRequest):
        for identifier in session.scalars(select(model.cartridge_id).distinct()):
            blocked.setdefault(
                identifier, "This cartridge has print or queue history. Archive it instead."
            )
    return blocked
