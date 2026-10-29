"""PT-P710BT TZe raster adapter; protocol details must stay in this package.

Source: Brother PT-E550W/P750W/P710BT Raster Command Reference v1.02.
Use buffered PackBits transfers and explicit completion/idle status notifications.
No grayscale encoding or consumption counter is documented by this protocol.
"""

import hashlib
import math
import struct
import time
import uuid
from dataclasses import dataclass
from typing import Sequence

from PIL import Image

from app.printer.base import (
    BatchPlan,
    DetectedMedia,
    LabelGeometry,
    LabelOutputPlan,
    MediaSelection,
    PrintControl,
    PrinterStatus,
    PrintInterrupted,
    PrintNotStarted,
    PrintResult,
    RenderedLabel,
    TapeBreakdown,
)
from app.printer.registry import ByteTransport, MediaKind, PrinterCapabilities

VENDOR_ID = 0x04F9
PRODUCT_ID = 0x20AF
PRINT_PINS = {3.5: 24, 6: 32, 9: 50, 12: 70, 18: 112, 24: 128}
WIDTH_CODES = {3.5: 4, 6: 6, 9: 9, 12: 12, 18: 18, 24: 24}
WIDTH_MM = {code: width for width, code in WIDTH_CODES.items()}
# Raster Command Reference v1.02, printed pp.27, 29–30.
MEDIA_NAMES = {
    0: "No tape",
    1: "Laminated tape",
    3: "Non-laminated tape",
    0x11: "Heat-shrink tube (2:1)",
    0x17: "Heat-shrink tube (3:1)",
    0xFF: "Incompatible tape",
}
TAPE_COLORS = {
    1: "White",
    2: "Other",
    3: "Clear",
    4: "Red",
    5: "Blue",
    6: "Yellow",
    7: "Green",
    8: "Black",
    9: "Clear (white text)",
    0x20: "Matte white",
    0x21: "Matte clear",
    0x22: "Matte silver",
    0x23: "Satin gold",
    0x24: "Satin silver",
    0x30: "Dark blue",
    0x31: "Dark red",
    0x40: "Fluorescent orange",
    0x41: "Fluorescent yellow",
    0x50: "Berry pink",
    0x51: "Light gray",
    0x52: "Lime green",
    0x60: "Fabric yellow",
    0x61: "Fabric pink",
    0x62: "Fabric blue",
    0x70: "Heat-shrink white",
    0x90: "Flexible ID white",
    0x91: "Flexible ID yellow",
    0xF0: "Cleaning",
    0xF1: "Stencil",
    0xFF: "Incompatible",
}
TEXT_COLORS = {
    1: "White",
    2: "Other",
    4: "Red",
    5: "Blue",
    8: "Black",
    0x0A: "Gold",
    0x62: "Fabric blue",
    0xF0: "Cleaning",
    0xF1: "Stencil",
    0xFF: "Incompatible",
}
DPI = 180
# Raster Command Reference, printed p.18: cutter position limits fed-out tape.
MINIMUM_CUT_LENGTH_MM = 24.5


def capabilities(*, high_resolution: bool = False) -> PrinterCapabilities:
    return PrinterCapabilities(
        MediaKind.CONTINUOUS,
        360 if high_resolution else DPI,
        DPI,
        tuple(PRINT_PINS),
        1,
        supports_cut=True,
        supports_stop_after_current=True,
        supports_emergency_stop=True,
        supports_manual_cut=False,
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
    tape_color: int = 0
    text_color: int = 0
    raw: bytes = b""

    @property
    def hardware_problem(self) -> str | None:
        if any(self.errors):
            return f"Printer error {self.errors[0]:02x}/{self.errors[1]:02x}; check tape, cutter, cover and battery"
        if self.kind == 4:
            return "Printer powered off"
        if self.kind == 2:
            return "Printer reported an error"
        return None

    @property
    def media_problem(self) -> str | None:
        if self.media not in (1, 3) or self.width not in WIDTH_MM:
            return "Install supported TZe tape"
        return None

    @property
    def problem(self) -> str | None:
        return self.hardware_problem or self.media_problem

    @property
    def media_identity(self) -> bytes:
        return bytes((self.width, self.media, self.tape_color, self.text_color))

    @property
    def description(self) -> str:
        width = WIDTH_MM.get(self.width)
        size = f"{width:g} mm" if width else f"Unknown width (0x{self.width:02x})"
        kind = MEDIA_NAMES.get(self.media, f"Unknown tape type (0x{self.media:02x})")
        tape = TAPE_COLORS.get(self.tape_color, f"Unknown tape color (0x{self.tape_color:02x})")
        ink = TEXT_COLORS.get(self.text_color, f"Unknown ink color (0x{self.text_color:02x})")
        return f"{size} · {kind} · {ink} on {tape}"

    @property
    def diagnostics(self) -> dict[str, str]:
        def code(value: int) -> str:
            return f"0x{value:02x} ({value})"

        def named(value: int, names: dict[int, str]) -> str:
            return f"{names.get(value, 'Unknown')} · {code(value)}"

        def flags(value: int, names: dict[int, str]) -> str:
            active = [name for bit, name in names.items() if value & bit]
            return f"{', '.join(active) or ('Unknown flags' if value else 'None')} · {code(value)}"

        return {
            "Media": self.description,
            "Media width code": code(self.width),
            "Media type": named(self.media, MEDIA_NAMES),
            "Tape color": named(self.tape_color, TAPE_COLORS),
            "Text color": named(self.text_color, TEXT_COLORS),
            "Errors 1": flags(
                self.errors[0],
                {
                    1: "No media",
                    4: "Cutter jam",
                    8: "Weak batteries",
                    0x40: "High-voltage adapter",
                },
            ),
            "Errors 2": flags(
                self.errors[1],
                {
                    1: "Wrong media",
                    0x10: "Cover open",
                    0x20: "Overheating",
                },
            ),
            "Status type": named(
                self.kind,
                {
                    0: "Status reply",
                    1: "Printing completed",
                    2: "Error",
                    3: "Exit interface mode",
                    4: "Powered off",
                    5: "Notification",
                    6: "Phase change",
                },
            ),
            "Phase type": named(self.phase, {0: "Editing / ready", 1: "Printing"}),
            "Phase number": str(self.phase_number),
            **(
                {
                    "Header": self.raw[:4].hex(" "),
                    "Model code": code(self.raw[4]),
                    "Country code": code(self.raw[5]),
                    "Reserved (6–7)": self.raw[6:8].hex(" "),
                    "Number of colors": code(self.raw[12]),
                    "Fonts": code(self.raw[13]),
                    "Reserved (14)": code(self.raw[14]),
                    "Mode": code(self.raw[15]),
                    "Density": code(self.raw[16]),
                    "Media length code": code(self.raw[17]),
                    "Notification": named(
                        self.raw[22], {0: "None", 1: "Cover open", 2: "Cover closed"}
                    ),
                    "Expansion area size": code(self.raw[23]),
                    "Hardware settings": self.raw[26:30].hex(" "),
                    "Reserved (30–31)": self.raw[30:32].hex(" "),
                    "Raw status (32 bytes)": self.raw.hex(" "),
                }
                if self.raw
                else {}
            ),
        }


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
        data[24],
        data[25],
        data,
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


class _StopRequested(Exception):
    pass


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
        self.selection: MediaSelection | None = None
        self._media_identity: bytes | None = None
        self._media_epoch = 0
        self._media_unavailable = False
        self._access_epoch = 0
        self._access_session = uuid.uuid4().hex
        self._media_changed = False
        self._cover_open = False

    def configure_media(self, selection: MediaSelection | None) -> None:
        self.selection = selection

    def _fingerprint(self, status: StatusPacket) -> str:
        return hashlib.sha256(
            status.media_identity + str(self._media_epoch).encode("ascii")
        ).hexdigest()

    def _confirmable(self, status: StatusPacket) -> bool:
        return (
            not status.hardware_problem
            and status.media not in (0, 0x11, 0x17)
            and status.width != 0
            and not status.phase
            and not status.phase_number
        )

    def _verification_key(self, status: StatusPacket) -> str:
        return hashlib.sha256(
            f"{self._access_session}:{self._fingerprint(status)}:{self._access_epoch}".encode()
        ).hexdigest()

    def _needs_verification(self, status: StatusPacket) -> bool:
        if self.selection and not self.selection.verify_after_change:
            return False
        return bool(
            self.selection
            and self.selection.verification_required
            or self._media_changed
            and (
                not self.selection
                or self.selection.verified_fingerprint != self._verification_key(status)
            )
        )

    def _confirmed(self, status: StatusPacket) -> bool:
        return bool(
            self.selection
            and self.selection.width_mm in WIDTH_CODES
            and self.selection.confirmation == self._fingerprint(status)
            and not status.hardware_problem
            and status.media not in (0, 0x11, 0x17)
            and status.width != 0
        )

    def _problem(self, status: StatusPacket) -> str | None:
        return (
            status.hardware_problem
            or (
                "Printer was opened or tape changed; confirm the installed cartridge"
                if self.selection and self._needs_verification(status)
                else None
            )
            or (None if self._confirmed(status) else status.media_problem)
        )

    def _invalidate_media(self) -> None:
        if not self._media_unavailable:
            self._media_epoch += 1
        self._media_unavailable = True

    def _read(self, deadline: float, control: PrintControl | None = None) -> StatusPacket:
        while len(self.buffer) < 32:
            if control is not None and control.emergency.is_set():
                raise _StopRequested("Emergency stop requested")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Printer status timed out")
            try:
                data = self.transport.read(64, min(remaining, 0.1) if control else remaining)
            except TimeoutError:
                if control is None:
                    raise
                continue  # Keep the original deadline and any partial status packet.
            if not data:
                raise OSError("Printer disconnected while reading status")
            self.buffer.extend(data)
            if len(self.buffer) > 4096:
                raise ValueError("Invalid status stream")
        packet = bytes(self.buffer[:32])
        del self.buffer[:32]
        return self._observe(decode_status(packet))

    def _observe(self, status: StatusPacket) -> StatusPacket:
        if self._media_identity is not None and self._media_identity != status.media_identity:
            self._media_epoch += 1
            self._media_changed = True
        self._media_identity = status.media_identity
        notification = status.raw[22] if status.raw and status.kind == 5 else 0
        opened = bool(status.errors[1] & 0x10) or notification == 1
        if opened and not self._cover_open or notification == 2 and not self._cover_open:
            self._access_epoch += 1
            self._media_changed = True
        self._cover_open = opened
        if status.errors[0] & 1 or status.kind == 4:
            self._invalidate_media()
        else:
            self._media_unavailable = False
        return status

    def _query(self) -> StatusPacket:
        # Consume old notifications for cartridge access before requesting fresh status.
        stale = bytearray(self.buffer)
        self.buffer.clear()
        for _ in range(64):
            try:
                data = self.transport.read(64, 0.02)
                if not data:
                    break
                stale.extend(data)
            except TimeoutError:
                break
        else:
            raise OSError("Printer status stream did not become idle")
        for offset in range(0, len(stale) - 31, 32):
            self._observe(decode_status(bytes(stale[offset : offset + 32])))
        self.transport.write(b"\x1biS")
        deadline = time.monotonic() + min(5, self.timeout)
        while True:
            status = self._read(deadline)
            if status.kind == 0:
                return status
            if status.hardware_problem:
                raise OSError(status.hardware_problem)

    def _close(self) -> None:
        try:
            self.transport.close()
        except Exception:
            pass  # Completion certainty comes from status, not releasing a disconnected handle.

    def get_status(self) -> PrinterStatus:
        try:
            self.transport.open()
            status = self._query()
            confirmed = self._confirmed(status)
            problem = self._problem(status) or (
                "Printer is busy" if status.phase or status.phase_number else None
            )
            width = (
                self.selection.width_mm
                if confirmed and self.selection
                else WIDTH_MM.get(status.width)
            )
            return PrinterStatus(
                True,
                width,
                problem,
                DetectedMedia(
                    WIDTH_MM.get(status.width),
                    status.description,
                    self._fingerprint(status),
                    status.media_problem,
                    self._confirmable(status),
                    self._verification_key(status),
                ),
                confirmed,
                status.diagnostics,
                self._needs_verification(status),
            )
        except Exception as error:
            self._invalidate_media()
            return PrinterStatus(False, None, str(error))
        finally:
            self._close()

    def estimate_consumption(self, labels: Sequence[RenderedLabel | LabelGeometry]) -> float:
        if not labels:
            return 0
        lengths = [label.length_mm + self._feed_per_label(label) for label in labels]
        return self.leader_mm + (
            sum(max(MINIMUM_CUT_LENGTH_MM, length) for length in lengths)
            if self.cut_each
            else max(MINIMUM_CUT_LENGTH_MM, sum(lengths))
        )

    def plan_batch(self, labels: Sequence[RenderedLabel | LabelGeometry]) -> BatchPlan:
        outputs = []
        for label in labels:
            feed = self._feed_per_label(label)
            length = label.length_mm + feed
            padding = max(0, MINIMUM_CUT_LENGTH_MM - length) if self.cut_each else 0
            outputs.append(
                LabelOutputPlan(
                    label.copy_id,
                    label.length_mm - label.template_padding_mm,
                    feed,
                    length + padding,
                    padding,
                    bool(padding or label.template_padding_mm) or not self.cut_each,
                    label.template_padding_mm,
                )
            )
        strip_padding = (
            max(0, MINIMUM_CUT_LENGTH_MM - sum(item.output_length_mm for item in outputs))
            if outputs and not self.cut_each
            else 0
        )
        leader = self.leader_mm if labels else 0
        return BatchPlan(
            self.estimate_consumption(labels),
            leader,
            self._feed_per_label(labels[0]) if labels else 0,
            self.cut_each,
            tuple(label.length_mm for label in labels),
            minimum_cut_length_mm=MINIMUM_CUT_LENGTH_MM,
            label_output=tuple(outputs),
            strip_padding_mm=strip_padding,
            breakdown=TapeBreakdown(
                sum(item.design_length_mm for item in outputs),
                sum(item.feed_mm for item in outputs),
                leader,
                sum(item.minimum_padding_mm + item.template_padding_mm for item in outputs)
                + strip_padding,
            ),
        )

    def _feed_per_label(self, label: RenderedLabel | LabelGeometry) -> float:
        return 2 * round(self.feed_mm * label.dpi_x / 25.4) * 25.4 / label.dpi_x

    def _wait_page(self, control: PrintControl | None = None) -> None:
        deadline = time.monotonic() + self.timeout
        completed = False
        while True:
            status = self._read(deadline, control)
            if self._problem(status):
                raise OSError(self._problem(status))
            if status.kind == 1:
                completed = True
            if completed and status.kind == 6 and status.phase == 0 and status.phase_number == 0:
                return

    def print_batch(self, labels: Sequence[RenderedLabel]) -> PrintResult:
        return self._print_batch(labels)

    def print_batch_controlled(
        self, labels: Sequence[RenderedLabel], control: PrintControl
    ) -> PrintResult:
        return self._print_batch(labels, control)

    def _print_batch(
        self, labels: Sequence[RenderedLabel], control: PrintControl | None = None
    ) -> PrintResult:
        if not labels:
            return PrintResult(0)
        if control is not None and control.stop.is_set():
            raise PrintNotStarted("Printing stopped before transmission")
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
                self._problem(status)
                or status.phase
                or status.phase_number
                or (
                    self.selection.width_mm
                    if self._confirmed(status) and self.selection
                    else WIDTH_MM.get(status.width)
                )
                != labels[0].tape_width_mm
            ):
                raise PrintNotStarted(
                    self._problem(status) or "Printer busy or tape width does not match"
                )
            confirmed = self._confirmed(status)
            if control is not None and control.stop.is_set():
                raise PrintNotStarted("Printing stopped before transmission")
            self.transport.write(b"\x00" * 100 + b"\x1b@\x1bia\x01\x1bi!\x00")
            for index, label in enumerate(labels):
                if control is not None and control.stop.is_set():
                    raise _StopRequested("Printing stopped after the current label")
                final = index == len(labels) - 1
                controls = (
                    b"\x1biz"
                    # After explicit confirmation, skip the firmware's type/width comparison.
                    # Reference v1.02 p.32: PI_KIND=0x02, PI_WIDTH=0x04.
                    + bytes(
                        (
                            0x80 if confirmed else 0x86,
                            1 if confirmed else status.media,
                            WIDTH_CODES[labels[0].tape_width_mm] if confirmed else status.width,
                            0,
                        )
                    )
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
                raster = encode_raster(label)
                ending = b"\x1a" if final else b"\x0c"
                if control is None:
                    self.transport.write(controls + raster + ending)
                else:
                    # Every G command is exactly 20 bytes in our literal PackBits encoding.
                    # Cancel only between complete commands, never within USB's arbitrary
                    # chunk boundaries. An already blocked write can still delay the stop.
                    self.transport.write(controls)
                    for offset in range(0, len(raster), 3200):
                        if control.emergency.is_set():
                            raise _StopRequested("Emergency stop requested")
                        self.transport.write(raster[offset : offset + 3200])
                    if control.emergency.is_set():
                        raise _StopRequested("Emergency stop requested")
                    self.transport.write(ending)
                self._wait_page(control)
                completed += 1
            if control is not None and control.stop.is_set():
                raise _StopRequested("Printing stopped after the current label")
            # A final feed/cut error can arrive in a separate USB transfer.
            # Read briefly without issuing any command before accepting completion.
            deadline = time.monotonic() + 0.25
            while True:
                try:
                    trailing = self._read(deadline, control)
                except TimeoutError:
                    if self.buffer:
                        raise OSError("Incomplete final status packet")
                    break
                if trailing.problem:
                    raise OSError(trailing.problem)
            return PrintResult()  # No documented measured-consumption counter.
        except _StopRequested as error:
            # ESC @ cancels printing and clears the chain buffer (Brother reference p.23).
            # This runs on the hardware-owning thread with the already-open transport.
            message = str(error)
            try:
                self.transport.write(b"\x1b@")
            except Exception as cancel_error:
                message += f"; printer cancellation could not be confirmed: {cancel_error}"
            if started:
                raise PrintInterrupted(message, max(0, completed - 1)) from error
            raise PrintNotStarted(message) from error
        except PrintNotStarted:
            raise
        except Exception as error:
            if started:
                # The preceding page may still be in the final feed/cut stage.
                raise PrintInterrupted(str(error), max(0, completed - 1)) from error
            raise PrintNotStarted(str(error)) from error
        finally:
            self._close()
