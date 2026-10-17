"""Queue policy and durable physical-print attempts; no printer protocol knowledge."""

import math
import time
from _thread import LockType
from dataclasses import dataclass, replace
from threading import Lock
from typing import Protocol, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.destinations import printer_state
from app.font_assets import FontStore
from app.image_assets import ImageStore
from app.models import (
    Base,
    Batch,
    BatchItem,
    Cartridge,
    FlushRequest,
    LabelCopy,
    PrinterGroup,
    PrinterState,
    PrintJob,
    PrintRun,
    State,
    TapeProfile,
)
from app.notifications import enqueue, schedule_reminders, sync_empty_cartridge_alert
from app.printer.base import (
    ControlledPrinterBackend,
    PrintControl,
    PrinterBackend,
    PrinterStatus,
    PrintInterrupted,
    PrintNotStarted,
    RenderedLabel,
)
from app.render import render_job

Record = TypeVar("Record", bound=Base)
EMPTY_TAPE_BLOCKER = (
    "Installed cartridge is estimated empty; automatic printing is waiting for replacement tape."
)


def required(session: Session, model: type[Record], identifier: str) -> Record:
    value = session.get(model, identifier)
    if value is None:
        raise RuntimeError(f"Missing {model.__name__}: {identifier}")
    return value


def compatible_copies(
    session: Session, profile: TapeProfile, destination_id: str
) -> list[LabelCopy]:
    return list(
        session.scalars(
            select(LabelCopy)
            .join(PrintJob)
            .where(
                LabelCopy.state == State.QUEUED,
                PrintJob.profile_id == profile.id,
                PrintJob.destination_id == destination_id,
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


def require_idle(session: Session, printer_id: str) -> None:
    if session.scalar(
        select(Batch.id)
        .where(
            Batch.printer_id == printer_id, Batch.state.in_([State.PRINTING, State.NEEDS_REVIEW])
        )
        .limit(1)
    ):
        raise ValueError("Resolve the active print/review batch first")


def complete_empty_flushes(session: Session) -> None:
    """Cancelled selections release reservations even when their cartridge is absent."""
    session.flush()
    for pending in session.scalars(select(FlushRequest).where(FlushRequest.completed.is_(False))):
        if not session.scalar(
            select(LabelCopy.id)
            .where(LabelCopy.id.in_(pending.copy_ids), LabelCopy.state == State.QUEUED)
            .limit(1)
        ):
            pending.completed = True


class ChoosePrinter(Protocol):
    def __call__(
        self,
        session: Session,
        job: PrintJob,
        manual: bool = False,
        required_printer: str | None = None,
        *,
        require_ready: bool = True,
    ) -> str | None: ...


def record_blocker(session: Session, state: PrinterState, reason: str | None) -> None:
    if reason and state.blocker != reason:
        enqueue(
            session,
            "Printing blocked",
            reason,
            f"/#/printers?printer={state.printer_id}",
            kind="printer_blocked",
            context={"printer_id": state.printer_id, "reason": reason},
        )
    state.blocker = reason


@dataclass(frozen=True)
class PreparedBatch:
    id: str
    request_id: str | None


class QueueWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        backend: PrinterBackend,
        fonts: FontStore | None = None,
        images: ImageStore | None = None,
        *,
        printer_id: str,
        lock: LockType | None = None,
        choose: ChoosePrinter | None = None,
        enforce_job_access: bool = True,
    ) -> None:
        self.fonts = fonts
        self.images = images
        self.factory = factory
        self.backend = backend
        self.printer_id = printer_id
        self.choose = choose
        self.enforce_job_access = enforce_job_access
        self.lock = lock or Lock()
        self.printer_lock = Lock()
        self.control = PrintControl()
        self.latest_status = PrinterStatus(False, None)

    def recover(self) -> None:
        """A committed PRINTING intent may have reached hardware before a crash."""
        with self.lock, self.factory.begin() as session:
            for batch in session.scalars(
                select(Batch).where(
                    Batch.printer_id == self.printer_id, Batch.state == State.PRINTING
                )
            ):
                self._uncertain(session, batch, 0, "Server restarted during printing")

    def tick(self, now: float | None = None) -> None:
        stamp = time.time() if now is None else now
        with self.printer_lock:
            with self.lock:
                self.control.clear()
            try:
                self.latest_status = self.backend.get_status()
            except Exception:
                self.latest_status = PrinterStatus(False, None)
            prepared = self._reserve(stamp)
            if prepared is None:
                return
            batch_id = prepared.id
            labels: tuple[RenderedLabel, ...] = ()
            try:
                # Saved jobs protect their assets, and PRINTING prevents cancellation or
                # configuration changes while this immutable snapshot is rendered.
                try:
                    labels, estimate = self._render_reserved(batch_id)
                except Exception as error:
                    raise PrintNotStarted(f"Could not prepare labels: {error}") from error
                with self.lock, self.factory.begin() as session:
                    batch = required(session, Batch, batch_id)
                    cartridge = required(session, Cartridge, batch.cartridge_id)
                    batch.estimated_mm = estimate
                    batch.shortage_warning = estimate > cartridge.remaining_mm
                result = (
                    self.backend.print_batch_controlled(labels, self.control)
                    if isinstance(self.backend, ControlledPrinterBackend)
                    else self.backend.print_batch(labels)
                )
                consumed = estimate if result.consumed_mm is None else result.consumed_mm
                if not math.isfinite(consumed) or consumed < 0:
                    raise ValueError("Invalid backend consumption result")
            except PrintNotStarted as error:
                with self.lock, self.factory.begin() as session:
                    batch = required(session, Batch, batch_id)
                    batch.state, batch.error, batch.finished_at = (
                        State.FAILED,
                        str(error),
                        time.time(),
                    )
                    for item in session.scalars(
                        select(BatchItem).where(BatchItem.batch_id == batch_id)
                    ):
                        item.outcome = State.FAILED
                        copy = required(session, LabelCopy, item.copy_id)
                        copy.state = State.QUEUED
                    if prepared.request_id and not self.control.stop.is_set():
                        stored_request = required(session, FlushRequest, prepared.request_id)
                        stored_request.completed = False
                    state = printer_state(session, self.printer_id)
                    record_blocker(session, state, str(error))
            except Exception as error:
                with self.lock, self.factory.begin() as session:
                    batch = required(session, Batch, batch_id)
                    confirmed = error.confirmed_labels if isinstance(error, PrintInterrupted) else 0
                    if not 0 <= confirmed <= len(labels):
                        confirmed = 0
                    self._uncertain(session, batch, confirmed, str(error))
            else:
                with self.lock, self.factory.begin() as session:
                    state = printer_state(session, self.printer_id)
                    record_blocker(session, state, None)
                    batch = required(session, Batch, batch_id)
                    batch.state, batch.finished_at, batch.consumed_mm = (
                        State.PRINTED,
                        time.time(),
                        consumed,
                    )
                    cartridge = required(session, Cartridge, batch.cartridge_id)
                    cartridge.remaining_mm = max(0, cartridge.remaining_mm - consumed)
                    sync_empty_cartridge_alert(session, state, cartridge, time.time())
                    for item in session.scalars(
                        select(BatchItem).where(BatchItem.batch_id == batch_id)
                    ):
                        item.outcome = State.PRINTED
                        copy = required(session, LabelCopy, item.copy_id)
                        copy.state = State.PRINTED
            with self.lock, self.factory.begin() as session:
                schedule_reminders(session, stamp)

    def _reserve(self, stamp: float) -> PreparedBatch | None:
        """Freeze eligible copies and persist intent before any hardware write."""
        with self.lock, self.factory.begin() as session:
            if self.enforce_job_access:
                from app.job_access import reconcile_access_holds

                reconcile_access_holds(session, stamp)
            complete_empty_flushes(session)
            schedule_reminders(session, stamp)
            if session.scalar(
                select(Batch.id)
                .where(
                    Batch.printer_id == self.printer_id,
                    Batch.state.in_([State.NEEDS_REVIEW, State.PRINTING]),
                )
                .limit(1)
            ):
                return None
            state = printer_state(session, self.printer_id)
            if not state.active_cartridge_id:
                state.empty_alert_cartridge_id = None
                if state.blocker == EMPTY_TAPE_BLOCKER:
                    state.blocker = None
                return None
            cartridge = required(session, Cartridge, state.active_cartridge_id)
            profile = required(session, TapeProfile, cartridge.profile_id)
            request = session.scalar(
                select(FlushRequest)
                .where(
                    FlushRequest.printer_id == self.printer_id,
                    FlushRequest.completed.is_(False),
                    FlushRequest.cartridge_id == cartridge.id,
                )
                .order_by(FlushRequest.created_at)
                .limit(1)
            )
            sync_empty_cartridge_alert(session, state, cartridge, stamp)
            if request is None and cartridge.remaining_mm <= 0:
                state.blocker = EMPTY_TAPE_BLOCKER
                return None
            if cartridge.remaining_mm > 0 and state.blocker == EMPTY_TAPE_BLOCKER:
                state.blocker = None
            destinations = [self.printer_id] + [
                group.id
                for group in session.scalars(select(PrinterGroup))
                if self.printer_id in group.printer_ids
            ]
            copies = []
            blocked_demand = False
            for destination in destinations:
                if request and request.destination_id != destination:
                    continue
                group = session.get(PrinterGroup, destination)
                if not request and (
                    state.automatic_printing_held or (group and group.automatic_printing_held)
                ):
                    continue
                eligible = compatible_copies(session, profile, destination)
                reserved = {
                    identifier
                    for pending in session.scalars(
                        select(FlushRequest).where(FlushRequest.completed.is_(False))
                    )
                    if not request or pending.id != request.id
                    for identifier in pending.copy_ids
                }
                eligible = [copy for copy in eligible if copy.id not in reserved]
                if self.enforce_job_access:
                    from app.job_access import job_eligible

                    allowed: dict[str, bool] = {}
                    for copy in eligible:
                        if copy.job_id not in allowed:
                            allowed[copy.job_id] = job_eligible(
                                session, required(session, PrintJob, copy.job_id)
                            )
                    eligible = [copy for copy in eligible if allowed[copy.job_id]]
                if request:
                    eligible = [copy for copy in eligible if copy.id in set(request.copy_ids)]
                elif len(eligible) < profile.auto_print_threshold:
                    continue
                for copy in eligible:
                    job = required(session, PrintJob, copy.job_id)
                    selected = (
                        self.choose(
                            session, job, bool(request), self.printer_id if request else None
                        )
                        if self.choose
                        else None
                    )
                    if destination == self.printer_id or selected == self.printer_id:
                        copies.append(copy)
                    elif (
                        selected is None
                        and self.choose
                        and self.choose(
                            session, job, bool(request), self.printer_id, require_ready=False
                        )
                        == self.printer_id
                    ):
                        blocked_demand = True
                if copies:
                    break
            if not copies and not blocked_demand:
                record_blocker(session, state, None)
                if request and not session.scalar(
                    select(LabelCopy.id)
                    .where(LabelCopy.id.in_(request.copy_ids), LabelCopy.state == State.QUEUED)
                    .limit(1)
                ):
                    request.completed = True
                return None
            status = self.latest_status
            if not status.connected:
                record_blocker(session, state, "Printer disconnected")
                return None
            if status.error:
                record_blocker(session, state, status.error)
                return None
            if status.tape_width_mm != profile.width_mm:
                record_blocker(
                    session,
                    state,
                    f"Expected {profile.width_mm} mm tape; detected {status.tape_width_mm or 'unknown'}",
                )
                return None
            record_blocker(session, state, None)
            if not copies:
                return None
            estimate = 0.0  # Filled after raster preparation, before hardware I/O.
            for copy in copies:
                job = required(session, PrintJob, copy.job_id)
                if job.run_id:
                    run = session.get(PrintRun, job.run_id)
                    if run:
                        run.assigned_printer_id = self.printer_id
            batch = Batch(
                printer_id=self.printer_id,
                cartridge_id=cartridge.id,
                estimated_mm=estimate,
                shortage_warning=estimate > cartridge.remaining_mm,
                created_at=stamp,
                trigger={
                    "kind": "manual" if request else "automatic",
                    "actor": request.started_by if request else None,
                    "at": request.created_at if request else stamp,
                    "flush_request_id": request.id if request else None,
                },
            )
            session.add(batch)
            session.flush()
            batch_id = batch.id
            for position, copy in enumerate(copies):
                from app.print_audit import job_attribution

                copy.state = State.PRINTING
                session.add(
                    BatchItem(
                        batch_id=batch.id,
                        copy_id=copy.id,
                        position=position,
                        attribution=job_attribution(
                            session, required(session, PrintJob, copy.job_id)
                        ),
                    )
                )
            if request:
                request.completed = True
        return PreparedBatch(batch_id, request.id if request else None)

    def _render_reserved(self, batch_id: str) -> tuple[tuple[RenderedLabel, ...], float]:
        labels: list[RenderedLabel] = []
        rendered_jobs: dict[str, RenderedLabel] = {}
        with self.factory() as session:
            for item in session.scalars(
                select(BatchItem).where(BatchItem.batch_id == batch_id).order_by(BatchItem.position)
            ):
                copy = required(session, LabelCopy, item.copy_id)
                job = required(session, PrintJob, copy.job_id)
                if job.id not in rendered_jobs:
                    rendered_jobs[job.id] = render_job(job, copy, self.fonts, self.images)
                labels.append(replace(rendered_jobs[job.id], copy_id=copy.id))
        estimate = self.backend.estimate_consumption(labels)
        if not math.isfinite(estimate) or estimate < 0:
            raise ValueError("Invalid backend consumption estimate")
        return tuple(labels), estimate

    def _uncertain(self, session: Session, batch: Batch, confirmed: int, error: str) -> None:
        batch.state, batch.error = State.NEEDS_REVIEW, error
        cartridge = required(session, Cartridge, batch.cartridge_id)
        cartridge.consumption_uncertain = True
        items = session.scalars(
            select(BatchItem).where(BatchItem.batch_id == batch.id).order_by(BatchItem.position)
        )
        for index, item in enumerate(items):
            item.outcome = State.PRINTED if index < confirmed else State.NEEDS_REVIEW
            copy = required(session, LabelCopy, item.copy_id)
            copy.state = item.outcome
        enqueue(
            session,
            "Print batch needs review",
            "Printing may have stopped partway through. Review the batch before printing again.",
            f"/#/batches/{batch.id}",
            kind="batch_review",
            context={"printer_id": batch.printer_id, "batch_id": batch.id},
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
            copy.state = item.outcome
    cartridge = required(session, Cartridge, batch.cartridge_id)
    cartridge.remaining_mm = max(0, cartridge.remaining_mm - consumed_mm)
    cartridge.consumption_uncertain = False
    sync_empty_cartridge_alert(
        session, printer_state(session, batch.printer_id), cartridge, time.time()
    )
    batch.consumed_mm = consumed_mm
    batch.finished_at = time.time()
    batch.state = (
        State.PRINTED if all(item.outcome == State.PRINTED for item in items) else State.FAILED
    )
