"""One hardware owner per local printer; execution is independent of network I/O."""

from threading import Lock
from typing import Any

from app.companion.companion_protocol import BatchEnvelope, ExecutionResult, payload_digest
from app.printer.base import (
    ControlledPrinterBackend,
    PrintControl,
    PrinterBackend,
    PrintInterrupted,
    PrintNotStarted,
)
from companion.journal import Journal


class Executor:
    def __init__(self, journal: Journal, local_id: str, backend: PrinterBackend):
        self.journal, self.local_id, self.backend = journal, local_id, backend
        self.lock = Lock()
        self.control = PrintControl()

    def execute(self, payload: dict[str, Any]) -> None:
        envelope = BatchEnvelope.model_validate(payload)
        if envelope.local_id != self.local_id:
            raise ValueError("Batch belongs to a different local printer")
        with self.lock:
            row = self.journal.row(envelope.batch_id)
            if payload_digest(envelope.model_dump()) != row["digest"]:
                raise ValueError("Execution payload differs from the authorized batch")
            if not self.journal.start(envelope.batch_id):
                return
            result = ExecutionResult(
                digest=row["digest"], go_token=row["go_token"], outcome="interrupted"
            )
            try:
                if self.journal.blocked(self.local_id):
                    raise PrintNotStarted("Printer requires investigation")
                if self.control.stop.is_set():
                    raise PrintNotStarted("Printing was stopped")
                labels = tuple(label.rendered() for label in envelope.labels)
                output = (
                    self.backend.print_batch_controlled(labels, self.control)
                    if isinstance(self.backend, ControlledPrinterBackend)
                    else self.backend.print_batch(labels)
                )
                result = ExecutionResult(
                    digest=row["digest"],
                    go_token=row["go_token"],
                    outcome="printed",
                    confirmed_labels=len(labels),
                    consumed_mm=output.consumed_mm,
                )
            except PrintNotStarted:
                result.outcome = "not_started"
            except PrintInterrupted as error:
                result.confirmed_labels = (
                    error.confirmed_labels
                    if 0 <= error.confirmed_labels <= len(envelope.labels)
                    else 0
                )
            except Exception:
                # Unknown failures after entering execution are uncertain. Raw driver
                # messages never become remote payloads or evidence containing secrets.
                pass
            self.journal.finish(envelope.batch_id, result)
