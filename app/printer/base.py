from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class PrinterStatus:
    connected: bool
    tape_width_mm: float | None
    error: str | None = None


@dataclass(frozen=True)
class RenderedLabel:
    """A protocol-independent, packed 1-bit image (MSB first, row padded)."""

    copy_id: str
    tape_width_mm: float
    length_mm: float
    pixel_width: int
    pixel_height: int
    raster: bytes
    dpi_x: int = 180
    dpi_y: int = 180
    # A saved canvas may have different dimensions from its physical media.
    canvas_width_mm: float | None = None


@dataclass(frozen=True)
class PrintResult:
    consumed_mm: float | None = None


class PrintNotStarted(Exception):
    """Backend guarantees that no tape was consumed and no label was printed."""


class PrintInterrupted(Exception):
    """Only this prefix of the ordered labels is confirmed complete."""

    def __init__(self, message: str, confirmed_labels: int = 0) -> None:
        super().__init__(message)
        self.confirmed_labels = confirmed_labels


@dataclass(frozen=True)
class BatchPlan:
    estimated_mm: float
    leader_mm: float
    feed_per_label_mm: float
    cut_each: bool
    label_lengths_mm: tuple[float, ...]
    calibrated: bool = False


class PrinterBackend(Protocol):
    def plan_batch(self, labels: Sequence[RenderedLabel]) -> BatchPlan: ...
    def get_status(self) -> PrinterStatus: ...
    def estimate_consumption(self, labels: Sequence[RenderedLabel]) -> float: ...
    def print_batch(self, labels: Sequence[RenderedLabel]) -> PrintResult: ...
