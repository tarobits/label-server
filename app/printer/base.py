from dataclasses import dataclass
from threading import Event
from typing import Literal, Protocol, Sequence, runtime_checkable

StopMode = Literal["after_current", "emergency"]


class PrintControl:
    """Thread-safe intent consumed by the hardware owner at safe boundaries."""

    def __init__(self) -> None:
        self.stop = Event()
        self.emergency = Event()

    def request(self, mode: StopMode) -> None:
        if mode == "emergency":
            self.emergency.set()
        self.stop.set()

    def clear(self) -> None:
        self.stop.clear()
        self.emergency.clear()

    @property
    def mode(self) -> StopMode | None:
        return (
            "emergency"
            if self.emergency.is_set()
            else "after_current"
            if self.stop.is_set()
            else None
        )


@dataclass(frozen=True)
class PrinterStatus:
    connected: bool
    tape_width_mm: float | None
    error: str | None = None


@dataclass(frozen=True)
class LabelGeometry:
    """Saved physical dimensions for estimating consumption without rasterizing."""

    copy_id: str
    tape_width_mm: float
    length_mm: float
    dpi_x: int = 180
    dpi_y: int = 180
    template_padding_mm: float = 0


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
    template_padding_mm: float = 0


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
class LabelOutputPlan:
    copy_id: str
    design_length_mm: float
    feed_mm: float
    output_length_mm: float
    minimum_padding_mm: float
    trim_required: bool
    template_padding_mm: float = 0


@dataclass(frozen=True)
class TapeBreakdown:
    design_mm: float
    feed_mm: float
    leader_mm: float
    unused_mm: float


@dataclass(frozen=True)
class BatchPlan:
    estimated_mm: float
    leader_mm: float
    feed_per_label_mm: float
    cut_each: bool
    label_lengths_mm: tuple[float, ...]
    calibrated: bool = False
    minimum_cut_length_mm: float | None = None
    label_output: tuple[LabelOutputPlan, ...] = ()
    strip_padding_mm: float = 0
    breakdown: TapeBreakdown | None = None


class PrinterBackend(Protocol):
    def plan_batch(self, labels: Sequence[RenderedLabel | LabelGeometry]) -> BatchPlan: ...
    def get_status(self) -> PrinterStatus: ...
    def estimate_consumption(self, labels: Sequence[RenderedLabel | LabelGeometry]) -> float: ...
    def print_batch(self, labels: Sequence[RenderedLabel]) -> PrintResult: ...


@runtime_checkable
class ControlledPrinterBackend(Protocol):
    def print_batch_controlled(
        self, labels: Sequence[RenderedLabel], control: PrintControl
    ) -> PrintResult: ...
