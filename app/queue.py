"""Queue policy and durable physical-print attempts; no printer protocol knowledge."""

import math
import time
from dataclasses import dataclass, replace
from threading import Lock
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.font_assets import FontStore
from app.identity import DEFAULT_PRINTER_ID
from app.image_assets import ImageStore
from app.models import (
    Base,
    Batch,
    BatchItem,
    Cartridge,
    FlushRequest,
    LabelCopy,
    PrinterState,
    PrintJob,
    State,
    TapeProfile,
)
from app.notifications import enqueue, schedule_reminders
from app.printer.base import (
    PrinterBackend,
    PrinterStatus,
    PrintInterrupted,
    PrintNotStarted,
    RenderedLabel,
)
from app.render import render_job

Record = TypeVar("Record", bound=Base)


def required(session: Session, model: type[Record], identifier: str) -> Record:
    value = session.get(model, identifier)
    if value is None:
        raise RuntimeError(f"Missing {model.__name__}: {identifier}")
    return value


def compatible_copies(session: Session, profile: TapeProfile) -> list[LabelCopy]:
    return list(
        session.scalars(
            select(LabelCopy)
            .join(PrintJob)
            .where(
                LabelCopy.state == State.QUEUED,
                PrintJob.profile_id == profile.id,
                PrintJob.destination_id == DEFAULT_PRINTER_ID,
                PrintJob.width_mm == profile.width_mm,
            )
            .order_by(
                PrintJob.created_at,
                PrintJob.run_id,
                PrintJob.run_position,
                PrintJob.id,
                LabelCopy.ordinal,
            )
        )
    )


def require_idle(session: Session) -> None:
    if session.scalar(
        select(Batch.id).where(Batch.state.in_([State.PRINTING, State.NEEDS_REVIEW])).limit(1)
    ):
        raise ValueError("Resolve the active print/review batch first")


def record_blocker(session: Session, state: PrinterState, reason: str | None) -> None:
    if reason and state.blocker != reason:
        enqueue(session, "Printing blocked", reason, "/#/settings")
    state.blocker = reason


@dataclass(frozen=True)
class PreparedBatch:
    id: str
    labels: tuple[RenderedLabel, ...]
    estimated_mm: float
    request_id: str | None


class QueueWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        backend: PrinterBackend,
        fonts: FontStore | None = None,
        images: ImageStore | None = None,
    ) -> None:
        self.fonts = fonts
        self.images = images
        self.factory = factory
        self.backend = backend
        self.lock = Lock()
        self.printer_lock = Lock()
        self.latest_status = PrinterStatus(False, None)

    def recover(self) -> None:
        """A committed PRINTING intent may have reached hardware before a crash."""
        with self.lock, self.factory.begin() as session:
            for batch in session.scalars(select(Batch).where(Batch.state == State.PRINTING)):
                self._uncertain(session, batch, 0, "Server restarted during printing")

    def tick(self, now: float | None = None) -> None:
        stamp = time.time() if now is None else now
        with self.printer_lock:
            try:
                self.latest_status = self.backend.get_status()
            except Exception:
                self.latest_status = PrinterStatus(False, None)
            prepared = self._reserve(stamp)
            if prepared is None:
                return
            batch_id, labels, estimate = prepared.id, prepared.labels, prepared.estimated_mm
            # The PRINTING intent is committed BEFORE the first possible hardware write.
            try:
                result = self.backend.print_batch(labels)
                consumed = estimate if result.consumed_mm is None else result.consumed_mm
                if not math.isfinite(consumed) or consumed < 0:
                    raise ValueError("Invalid backend consumption result")
            except PrintNotStarted as error:
                with self.lock, self.factory.begin() as session:
                    batch = required(session, Batch, batch_id)
                    assert batch is not None
                    batch.state, batch.error, batch.finished_at = State.FAILED, str(error), stamp
                    for item in session.scalars(
                        select(BatchItem).where(BatchItem.batch_id == batch_id)
                    ):
                        item.outcome = State.FAILED
                        copy = required(session, LabelCopy, item.copy_id)
                        assert copy is not None
                        copy.state = State.QUEUED
                    if prepared.request_id:
                        stored_request = session.get(FlushRequest, prepared.request_id)
                        assert stored_request is not None
                        stored_request.completed = False
                    state = session.get(PrinterState, 1)
                    assert state is not None
                    record_blocker(session, state, str(error))
            except Exception as error:
                with self.lock, self.factory.begin() as session:
                    batch = required(session, Batch, batch_id)
                    assert batch is not None
                    confirmed = error.confirmed_labels if isinstance(error, PrintInterrupted) else 0
                    if not 0 <= confirmed <= len(labels):
                        confirmed = 0
                    self._uncertain(session, batch, confirmed, str(error))
            else:
                with self.lock, self.factory.begin() as session:
                    state = session.get(PrinterState, 1)
                    assert state is not None
                    record_blocker(session, state, None)
                    batch = required(session, Batch, batch_id)
                    assert batch is not None
                    batch.state, batch.finished_at, batch.consumed_mm = (
                        State.PRINTED,
                        stamp,
                        consumed,
                    )
                    cartridge = session.get(Cartridge, batch.cartridge_id)
                    assert cartridge is not None
                    cartridge.remaining_mm = max(0, cartridge.remaining_mm - consumed)
                    for item in session.scalars(
                        select(BatchItem).where(BatchItem.batch_id == batch_id)
                    ):
                        item.outcome = State.PRINTED
                        copy = required(session, LabelCopy, item.copy_id)
                        assert copy is not None
                        copy.state = State.PRINTED
            with self.lock, self.factory.begin() as session:
                schedule_reminders(session, stamp)

    def _reserve(self, stamp: float) -> PreparedBatch | None:
        """Freeze eligible copies and persist intent before any hardware write."""
        with self.lock, self.factory.begin() as session:
            schedule_reminders(session, stamp)
            if session.scalar(
                select(Batch.id)
                .where(Batch.state.in_([State.NEEDS_REVIEW, State.PRINTING]))
                .limit(1)
            ):
                return None
            state = session.get(PrinterState, 1)
            assert state is not None
            if not state.active_cartridge_id:
                return None
            cartridge = session.get(Cartridge, state.active_cartridge_id)
            assert cartridge is not None
            profile = session.get(TapeProfile, cartridge.profile_id)
            assert profile is not None
            copies = compatible_copies(session, profile)
            request = session.scalar(
                select(FlushRequest)
                .where(
                    FlushRequest.completed.is_(False),
                    FlushRequest.cartridge_id == cartridge.id,
                )
                .order_by(FlushRequest.created_at)
                .limit(1)
            )
            if request:
                wanted = set(request.copy_ids)
                copies = [copy for copy in copies if copy.id in wanted]
                if not copies:
                    request.completed = True
                    return None
            elif state.automatic_printing_held or len(copies) < profile.auto_print_threshold:
                return None
            status = self.latest_status
            if not status.connected:
                record_blocker(session, state, "Printer disconnected")
                return None
            if status.tape_width_mm != profile.width_mm:
                record_blocker(
                    session,
                    state,
                    f"Expected {profile.width_mm} mm tape; detected {status.tape_width_mm or 'unknown'}",
                )
                return None
            labels: list[RenderedLabel] = []
            rendered_jobs: dict[str, RenderedLabel] = {}
            for copy in copies:
                job = session.get(PrintJob, copy.job_id)
                assert job is not None
                if job.id not in rendered_jobs:
                    rendered_jobs[job.id] = render_job(job, copy, self.fonts, self.images)
                labels.append(replace(rendered_jobs[job.id], copy_id=copy.id))
            estimate = self.backend.estimate_consumption(labels)
            if not math.isfinite(estimate) or estimate < 0:
                raise ValueError("Invalid backend consumption estimate")
            batch = Batch(
                cartridge_id=cartridge.id,
                estimated_mm=estimate,
                shortage_warning=estimate > cartridge.remaining_mm,
            )
            session.add(batch)
            session.flush()
            batch_id = batch.id
            for position, copy in enumerate(copies):
                copy.state = State.PRINTING
                session.add(BatchItem(batch_id=batch.id, copy_id=copy.id, position=position))
            if request:
                request.completed = True
        return PreparedBatch(batch_id, tuple(labels), estimate, request.id if request else None)

    def _uncertain(self, session: Session, batch: Batch, confirmed: int, error: str) -> None:
        batch.state, batch.error = State.NEEDS_REVIEW, error
        cartridge = session.get(Cartridge, batch.cartridge_id)
        assert cartridge is not None
        cartridge.consumption_uncertain = True
        items = session.scalars(
            select(BatchItem).where(BatchItem.batch_id == batch.id).order_by(BatchItem.position)
        )
        for index, item in enumerate(items):
            item.outcome = State.PRINTED if index < confirmed else State.NEEDS_REVIEW
            copy = required(session, LabelCopy, item.copy_id)
            assert copy is not None
            copy.state = item.outcome
        enqueue(
            session,
            "Print batch needs review",
            "Printing may have stopped partway through. Review the batch before printing again.",
            f"/#/batches/{batch.id}",
        )


def resolve_batch(
    session: Session, batch: Batch, decisions: dict[str, State], consumed_mm: float
) -> None:
    if batch.state != State.NEEDS_REVIEW:
        raise ValueError("Batch is not waiting for review")
    items = list(session.scalars(select(BatchItem).where(BatchItem.batch_id == batch.id)))
    pending = {item.copy_id for item in items if item.outcome == State.NEEDS_REVIEW}
    if set(decisions) != pending:
        raise ValueError("Provide exactly one decision for every uncertain copy")
    for item in items:
        if item.copy_id in decisions:
            item.outcome = decisions[item.copy_id]
            copy = required(session, LabelCopy, item.copy_id)
            assert copy is not None
            copy.state = item.outcome
    cartridge = session.get(Cartridge, batch.cartridge_id)
    assert cartridge is not None
    cartridge.remaining_mm = max(0, cartridge.remaining_mm - consumed_mm)
    cartridge.consumption_uncertain = False
    batch.consumed_mm = consumed_mm
    batch.finished_at = time.time()
    batch.state = (
        State.PRINTED if all(item.outcome == State.PRINTED for item in items) else State.FAILED
    )
