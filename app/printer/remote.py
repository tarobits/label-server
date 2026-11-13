"""Durable remote execution adapter; no remote I/O or printer protocol in the queue."""

import time
from collections.abc import Sequence
from dataclasses import asdict

from sqlalchemy.orm import Session, sessionmaker

from app.companion.companion_protocol import (
    BatchEnvelope,
    ExecutionResult,
    WireLabel,
    payload_digest,
)
from app.i18n import Message
from app.models import Companion, CompanionBatch, CompanionPrinter, PrinterDevice
from app.printer.base import (
    BatchPlan,
    DetectedMedia,
    LabelGeometry,
    MediaSelection,
    PrinterBackend,
    PrinterStatus,
    PrintInterrupted,
    PrintNotStarted,
    PrintResult,
    RenderedLabel,
    StopMode,
)
from app.printer.messages import restore_reason


class RemotePrinterBackend:
    def __init__(self, factory: sessionmaker[Session], printer_id: str, planner: PrinterBackend):
        self.factory, self.printer_id, self.planner = factory, printer_id, planner
        self.selection: MediaSelection | None = None

    def configure_media(self, selection: MediaSelection | None) -> None:
        self.selection = selection

    def plan_batch(self, labels: Sequence[RenderedLabel | LabelGeometry]) -> BatchPlan:
        return self.planner.plan_batch(labels)

    def estimate_consumption(self, labels: Sequence[RenderedLabel | LabelGeometry]) -> float:
        return self.planner.estimate_consumption(labels)

    def get_status(self) -> PrinterStatus:
        with self.factory() as session:
            link = session.get(CompanionPrinter, self.printer_id)
            companion = session.get(Companion, link.companion_id) if link else None
            if (
                not link
                or not link.enabled
                or not companion
                or not companion.key_hash
                or not link.last_seen_at
                or link.last_seen_at < time.time() - 30
            ):
                return PrinterStatus(False, None)
            data = dict(link.status)
            if data.get("media"):
                data["media"] = DetectedMedia(**data["media"])
            if link.blocked:
                problem = restore_reason(data.get("error"), data.get("error_translation"))
                data["error"] = (
                    Message("printerMessages.investigationReason", reason=problem)
                    if problem
                    else Message("printerMessages.investigation")
                )
                data["error_requires_investigation"] = True
            return PrinterStatus(**data)

    def print_batch(self, labels: Sequence[RenderedLabel]) -> PrintResult:
        raise PrintNotStarted("Remote printing requires a durable batch identity")

    def submit_batch(self, batch_id: str, labels: Sequence[RenderedLabel]) -> None:
        with self.factory.begin() as session:
            existing = session.get(CompanionBatch, batch_id)
            if existing:
                return
            link = session.get(CompanionPrinter, self.printer_id)
            device = session.get(PrinterDevice, self.printer_id)
            if not link or not device:
                raise PrintNotStarted("Companion printer is no longer registered")
            payload = BatchEnvelope(
                batch_id=batch_id,
                printer_id=device.id,
                local_id=link.local_id,
                driver=device.driver,
                configuration=device.config,
                labels=[WireLabel.from_rendered(label) for label in labels],
            ).model_dump()
            session.add(
                CompanionBatch(
                    batch_id=batch_id,
                    companion_id=link.companion_id,
                    printer_id=device.id,
                    payload=payload,
                    digest=payload_digest(payload),
                )
            )

    def has_batch(self, batch_id: str) -> bool:
        with self.factory() as session:
            row = session.get(CompanionBatch, batch_id)
            return bool(row and row.printer_id == self.printer_id)

    def poll_batch(self, batch_id: str) -> PrintResult | None:
        with self.factory() as session:
            row = session.get(CompanionBatch, batch_id)
            if not row or row.printer_id != self.printer_id:
                raise PrintNotStarted("Remote attempt was not dispatched")
            if row.result is None:
                return None
            result = ExecutionResult.model_validate(row.result)
            if result.outcome == "not_started":
                raise PrintNotStarted(
                    "Companion rejected the batch before printing; investigate the printer"
                )
            if result.outcome == "interrupted":
                raise PrintInterrupted(
                    "Companion printing was interrupted; investigate the printer",
                    result.confirmed_labels,
                )
            return PrintResult(result.consumed_mm)

    def request_stop(self, batch_id: str, mode: StopMode) -> None:
        with self.factory.begin() as session:
            row = session.get(CompanionBatch, batch_id)
            if row and row.printer_id == self.printer_id and row.stop_mode != "emergency":
                row.stop_mode = mode

    def media_configuration(self) -> dict[str, object] | None:
        return asdict(self.selection) if self.selection else None
