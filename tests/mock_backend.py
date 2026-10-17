from typing import Sequence

from app.printer.base import (
    BatchPlan,
    LabelGeometry,
    PrinterStatus,
    PrintInterrupted,
    PrintNotStarted,
    PrintResult,
    RenderedLabel,
)


class MockPrinterBackend:
    """Captures synthetic raster batches; all feed measurements are fixtures."""

    def __init__(self, width_mm: float | None = 24) -> None:
        self.width_mm = width_mm
        self.connected = True
        self.fail_after: int | None = None
        self.batches: list[tuple[RenderedLabel, ...]] = []

    def get_status(self) -> PrinterStatus:
        return PrinterStatus(self.connected, self.width_mm)

    def estimate_consumption(self, labels: Sequence[RenderedLabel | LabelGeometry]) -> float:
        return sum(label.length_mm for label in labels) + (20 if labels else 0)

    def plan_batch(self, labels: Sequence[RenderedLabel]) -> BatchPlan:
        return BatchPlan(
            self.estimate_consumption(labels),
            20 if labels else 0,
            0,
            True,
            tuple(label.length_mm for label in labels),
        )

    def print_batch(self, labels: Sequence[RenderedLabel]) -> PrintResult:
        if not self.connected:
            raise PrintNotStarted("Mock printer disconnected")
        self.batches.append(tuple(labels))
        if self.fail_after is not None:
            confirmed = min(self.fail_after, len(labels))
            self.fail_after = None
            raise PrintInterrupted("Simulated interruption", confirmed)
        return PrintResult(self.estimate_consumption(labels))
