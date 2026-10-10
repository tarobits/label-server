"""PT-P710BT TZe raster adapter; protocol details must stay in this package.

Source: Brother PT-E550W/P750W/P710BT Raster Command Reference v1.02.
Use buffered PackBits transfers and explicit completion/idle status notifications.
No grayscale encoding or consumption counter is documented by this protocol.
"""

import math
import struct
import time
from dataclasses import dataclass
from typing import Sequence

from PIL import Image

from app.printer.base import (
    BatchPlan,
    PrinterStatus,
    PrintInterrupted,
    PrintNotStarted,
    PrintResult,
    RenderedLabel,
)
from app.printer.registry import ByteTransport, MediaKind, PrinterCapabilities

VENDOR_ID = 0x04F9
PRODUCT_ID = 0x20AF
PRINT_PINS = {3.5: 24, 6: 32, 9: 50, 12: 70, 18: 112, 24: 128}
WIDTH_CODES = {3.5: 4, 6: 6, 9: 9, 12: 12, 18: 18, 24: 24}
WIDTH_MM = {code: width for width, code in WIDTH_CODES.items()}
DPI = 180


def capabilities(*, high_resolution: bool = False) -> PrinterCapabilities:
    return PrinterCapabilities(
        MediaKind.CONTINUOUS,
        360 if high_resolution else DPI,
        DPI,
        tuple(PRINT_PINS),
        1,
        supports_cut=True,
        supports_consecutive=True,
        printable_widths_mm={str(width): pins * 25.4 / DPI for width, pins in PRINT_PINS.items()},
        resolution_modes={"normal": (180, 180), "high": (360, 180)},
    )


@dataclass(frozen=True)
class StatusPacket:
    width: int
    media: int
    kind: int
    phase: int
    errors: tuple[int, int]
    phase_number: int = 0

    @property
    def problem(self) -> str | None:
        if any(self.errors):
            return f"Printer error {self.errors[0]:02x}/{self.errors[1]:02x}; check tape, cutter, cover and battery"
        if self.kind == 4:
            return "Printer powered off"
        if self.kind == 2:
            return "Printer reported an error"
        if self.media not in (1, 3) or self.width not in WIDTH_MM:
            return "Install supported TZe tape"
        return None


def decode_status(data: bytes) -> StatusPacket:
    if len(data) != 32 or data[:4] != b"\x80\x20\x42\x30":
        raise ValueError("Invalid Brother status packet")
    return StatusPacket(
        data[10],
        data[11],
        data[18],
        data[19],
        (data[8], data[9]),
        int.from_bytes(data[20:22], "big"),
    )


def encode_raster(label: RenderedLabel) -> bytes:
    if label.tape_width_mm not in PRINT_PINS or not math.isfinite(label.length_mm):
        raise ValueError("Unsupported tape width or length")
    if label.dpi_x not in (180, 360) or label.dpi_y != DPI:
        raise ValueError(
            "Label raster must use 180 or 360 dpi along the tape and 180 dpi across it"
        )
    expected = (
        round(label.length_mm * label.dpi_x / 25.4),
        round((label.canvas_width_mm or label.tape_width_mm) * DPI / 25.4),
    )
    minimum, maximum = (60, 14172) if label.dpi_x == 360 else (31, 7086)
    if (
        label.pixel_width,
        label.pixel_height,
    ) != expected or not minimum <= label.pixel_width <= maximum:
        raise ValueError("Label raster dimensions do not match its resolution or supported length")
    if len(label.raster) != ((label.pixel_width + 7) // 8) * label.pixel_height:
        raise ValueError("Invalid packed raster size")
    source = Image.frombytes("1", expected, label.raster)
    pins = PRINT_PINS[label.tape_width_mm]
    top = (label.pixel_height - pins) // 2
    # Never silently discard ink from a job prepared with incompatible print margins.
    if (
        source.crop((0, 0, label.pixel_width, top)).getbbox()
        or source.crop((0, top + pins, label.pixel_width, label.pixel_height)).getbbox()
    ):
        raise ValueError(
            "Label exceeds the print head area; reopen and save the template for this printer"
        )
    head = Image.new("1", (label.pixel_width, 128))
    head.paste(source.crop((0, top, label.pixel_width, top + pins)), (0, (128 - pins) // 2))
    # Feed direction becomes successive rows, with the top of the label at the MSB end.
    rows = head.transpose(Image.Transpose.TRANSPOSE).tobytes()
    output = bytearray()
    for offset in range(0, len(rows), 16):
        line = rows[offset : offset + 16]
        # A literal PackBits run keeps transfer bounded and forces buffered mode.
        output.extend(b"G\x11\x00\x0f" + line)
    return bytes(output)


class BrotherPTP710BT:
    def __init__(
        self,
        transport: ByteTransport,
        *,
        timeout: float = 120,
        feed_mm: float = 2,
        leader_mm: float = 24.5,
        cut_each: bool = True,
    ):
        if timeout <= 0 or not 2 <= feed_mm <= 127 or leader_mm < 0:
            raise ValueError("Invalid printer timing or feed calibration")
        self.transport = transport
        self.timeout, self.feed_mm, self.leader_mm, self.cut_each = (
            timeout,
            feed_mm,
            leader_mm,
            cut_each,
        )
        self.buffer = bytearray()

    def _read(self, deadline: float) -> StatusPacket:
        while len(self.buffer) < 32:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Printer status timed out")
            data = self.transport.read(64, remaining)
            if not data:
                raise OSError("Printer disconnected while reading status")
            self.buffer.extend(data)
            if len(self.buffer) > 4096:
                raise ValueError("Invalid status stream")
        packet = bytes(self.buffer[:32])
        del self.buffer[:32]
        return decode_status(packet)

    def _query(self) -> StatusPacket:
        # Discard stale completions from an earlier connection before requesting fresh status.
        self.buffer.clear()
        for _ in range(64):
            try:
                if not self.transport.read(64, 0.02):
                    break
            except TimeoutError:
                break
        else:
            raise OSError("Printer status stream did not become idle")
        self.transport.write(b"\x1biS")
        deadline = time.monotonic() + min(5, self.timeout)
        while True:
            status = self._read(deadline)
            if status.kind == 0:
                return status
            if status.problem:
                raise OSError(status.problem)

    def _close(self) -> None:
        try:
            self.transport.close()
        except Exception:
            pass  # Completion certainty comes from status, not releasing a disconnected handle.

    def get_status(self) -> PrinterStatus:
        try:
            self.transport.open()
            status = self._query()
            problem = status.problem or (
                "Printer is busy" if status.phase or status.phase_number else None
            )
            return PrinterStatus(True, WIDTH_MM.get(status.width), problem)
        except Exception as error:
            return PrinterStatus(False, None, str(error))
        finally:
            self._close()

    def estimate_consumption(self, labels: Sequence[RenderedLabel]) -> float:
        if not labels:
            return 0
        lengths = [label.length_mm + self._feed_per_label(label) for label in labels]
        return self.leader_mm + (
            sum(max(24.5, length) for length in lengths)
            if self.cut_each
            else max(24.5, sum(lengths))
        )

    def plan_batch(self, labels: Sequence[RenderedLabel]) -> BatchPlan:
        return BatchPlan(
            self.estimate_consumption(labels),
            self.leader_mm if labels else 0,
            self._feed_per_label(labels[0]) if labels else 0,
            self.cut_each,
            tuple(label.length_mm for label in labels),
        )

    def _feed_per_label(self, label: RenderedLabel) -> float:
        return 2 * round(self.feed_mm * label.dpi_x / 25.4) * 25.4 / label.dpi_x

    def _wait_page(self) -> None:
        deadline = time.monotonic() + self.timeout
        completed = False
        while True:
            status = self._read(deadline)
            if status.problem:
                raise OSError(status.problem)
            if status.kind == 1:
                completed = True
            if completed and status.kind == 6 and status.phase == 0 and status.phase_number == 0:
                return

    def print_batch(self, labels: Sequence[RenderedLabel]) -> PrintResult:
        if not labels:
            return PrintResult(0)
        # Validate the entire batch before touching USB, not halfway through its transmission.
        try:
            if len({label.tape_width_mm for label in labels}) != 1:
                raise ValueError("Batch contains mixed tape widths")
            for label in labels:
                encode_raster(label)
        except ValueError as error:
            raise PrintNotStarted(str(error)) from error
        started, completed = False, 0
        try:
            self.transport.open()
            status = self._query()
            if (
                status.problem
                or status.phase
                or status.phase_number
                or WIDTH_MM.get(status.width) != labels[0].tape_width_mm
            ):
                raise PrintNotStarted(status.problem or "Printer busy or tape width does not match")
            self.transport.write(b"\x00" * 100 + b"\x1b@\x1bia\x01\x1bi!\x00")
            for index, label in enumerate(labels):
                final = index == len(labels) - 1
                controls = (
                    b"\x1biz"
                    + bytes((0x86, status.media, status.width, 0))
                    + struct.pack("<I", label.pixel_width)
                    + bytes((bool(index), 0))
                    + b"\x1biM"
                    + bytes((0x40 if self.cut_each else 0,))
                    + b"\x1biK"
                    + bytes(((8 if final else 0) | (0x40 if label.dpi_x == 360 else 0),))
                    + b"\x1bid"
                    + struct.pack("<H", round(self.feed_mm * label.dpi_x / 25.4))
                    + b"M\x02"
                )
                # From this point any failure is uncertain, even a short USB write.
                started = True
                self.transport.write(
                    controls + encode_raster(label) + (b"\x1a" if final else b"\x0c")
                )
                self._wait_page()
                completed += 1
            # A final feed/cut error can arrive in a separate USB transfer.
            # Read briefly without issuing any command before accepting completion.
            deadline = time.monotonic() + 0.25
            while True:
                try:
                    trailing = self._read(deadline)
                except TimeoutError:
                    if self.buffer:
                        raise OSError("Incomplete final status packet")
                    break
                if trailing.problem:
                    raise OSError(trailing.problem)
            return PrintResult()  # No documented measured-consumption counter.
        except PrintNotStarted:
            raise
        except Exception as error:
            if started:
                # The preceding page may still be in the final feed/cut stage.
                raise PrintInterrupted(str(error), max(0, completed - 1)) from error
            raise PrintNotStarted(str(error)) from error
        finally:
            self._close()
