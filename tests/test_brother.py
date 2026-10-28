from collections import deque
from types import SimpleNamespace

import pytest
import usb.core
from PIL import Image

from app.printer.base import PrintControl, PrintInterrupted, PrintNotStarted, RenderedLabel
from app.printer.brother import BrotherPTP710BT, capabilities, decode_status, encode_raster
from app.printer.usb import UsbTransport
from app.render import RenderSpec, render_document
from app.template_schema import TemplateDocument


def packet(kind: int = 0, phase: int = 0, width: int = 24, error: int = 0) -> bytes:
    value = bytearray(32)
    value[:4] = b"\x80\x20\x42\x30"
    value[8], value[10], value[11], value[18], value[19] = error, width, 1, kind, phase
    return bytes(value)


def label() -> RenderedLabel:
    image = Image.new("1", (425, 170))
    image.putpixel((5, 21), 1)
    image.putpixel((6, 148), 1)
    return RenderedLabel("one", 24, 60, 425, 170, image.tobytes())


class Transport:
    def __init__(self, *, fail_page: int | None = None, width: int = 24):
        self.pending: deque[bytes] = deque()
        self.writes: list[bytes] = []
        self.fail_page, self.width, self.pages = fail_page, width, 0
        self.opened = False

    def open(self) -> None:
        self.opened = True

    def write(self, data: bytes) -> None:
        self.writes.append(data)
        if data == b"\x1biS":
            # Split status at arbitrary USB boundaries; reader must reassemble it.
            reply = packet(width=self.width)
            self.pending.extend((reply[:7], reply[7:]))
        elif data.startswith(b"\x1biz"):
            self.pages += 1
            if self.pages == self.fail_page:
                self.pending.append(packet(2, error=2))
            else:
                self.pending.append(packet(6, 1) + packet(1))
                self.pending.append(packet(6))

    def read(self, size: int, timeout_seconds: float) -> bytes:
        if self.pending:
            return self.pending.popleft()
        raise TimeoutError("Timed out")

    def close(self) -> None:
        self.opened = False


def test_status_raster_pins_and_buffered_multi_page_stream() -> None:
    raster = encode_raster(label())
    assert len(raster) == 425 * 20
    assert raster[5 * 20 : 6 * 20] == b"G\x11\x00\x0f\x80" + b"\0" * 15
    assert raster[6 * 20 : 7 * 20] == b"G\x11\x00\x0f" + b"\0" * 15 + b"\x01"
    transport = Transport()
    backend = BrotherPTP710BT(transport)
    assert backend.get_status().tape_width_mm == 24
    assert backend.print_batch([label(), label()]).consumed_mm is None
    pages = [data for data in transport.writes if data.startswith(b"\x1biz")]
    assert len(pages) == 2
    assert pages[0][-1:] == b"\x0c" and pages[1][-1:] == b"\x1a"
    assert b"\x1biK\x00" in pages[0] and b"\x1biK\x08" in pages[1]
    assert b"\x1biM\x40" in pages[0] and b"M\x02" in pages[0]
    assert pages[0][7:11] == (425).to_bytes(4, "little")
    assert not transport.opened


@pytest.mark.parametrize("dpi_x", [180, 360])
def test_short_12mm_batch_already_chains_until_the_final_feed(dpi_x) -> None:
    labels = []
    for index, length in enumerate((10, 15, 18)):
        image = Image.new("1", (round(length * dpi_x / 25.4), 85))
        image.putpixel((5, 20), 1)
        labels.append(
            RenderedLabel(str(index), 12, length, *image.size, image.tobytes(), dpi_x=dpi_x)
        )
    transport = Transport(width=12)
    BrotherPTP710BT(transport).print_batch(labels)
    pages = [data for data in transport.writes if data.startswith(b"\x1biz")]
    resolution = 0x40 if dpi_x == 360 else 0
    for index, (page, label) in enumerate(zip(pages, labels)):
        assert page[7:11] == label.pixel_width.to_bytes(4, "little")
        assert b"\x1biM\x40" in page  # Individual cutting stays enabled.
        final = index == len(labels) - 1
        assert b"\x1biK" + bytes([resolution | (8 if final else 0)]) in page
        assert page.endswith(b"\x1a" if final else b"\x0c")


def test_wrong_width_and_invalid_ink_never_send_print_commands() -> None:
    transport = Transport(width=12)
    with pytest.raises(PrintNotStarted, match="width"):
        BrotherPTP710BT(transport).print_batch([label()])
    assert transport.writes == [b"\x1biS"]
    image = Image.new("1", (425, 170), 1)
    invalid = RenderedLabel("one", 24, 60, 425, 170, image.tobytes())
    transport = Transport()
    with pytest.raises(PrintNotStarted, match="print head"):
        BrotherPTP710BT(transport).print_batch([label(), invalid])
    assert not transport.writes


@pytest.mark.parametrize("failure,confirmed", [(1, 0), (2, 0), (3, 1)])
def test_interruption_preserves_only_certain_prefix(failure: int, confirmed: int) -> None:
    transport = Transport(fail_page=failure)
    with pytest.raises(PrintInterrupted) as error:
        BrotherPTP710BT(transport).print_batch([label()] * 3)
    assert error.value.confirmed_labels == confirmed
    assert transport.pages == failure
    assert not transport.opened


def test_timeout_after_page_write_is_uncertain_and_never_retried() -> None:
    class MissingCompletion(Transport):
        def write(self, data: bytes) -> None:
            super().write(data)
            if data.startswith(b"\x1biz"):
                self.pending.clear()

    transport = MissingCompletion()
    with pytest.raises(PrintInterrupted):
        BrotherPTP710BT(transport).print_batch([label()])
    assert transport.pages == 1


def test_bad_status_and_idle_errors() -> None:
    with pytest.raises(ValueError):
        decode_status(b"0" * 32)
    assert decode_status(packet(error=1)).problem

    class NoDevice(Transport):
        def open(self) -> None:
            raise OSError("No printer")

    assert not BrotherPTP710BT(NoDevice()).get_status().connected


def test_actual_print_band_is_used_by_preview_and_encoder() -> None:
    caps = capabilities()
    document = TemplateDocument.model_validate(
        {
            "out_of_bounds": "clip",
            "elements": [
                {
                    "id": "r",
                    "kind": "rectangle",
                    "x": 2,
                    "y": 1,
                    "width": 40,
                    "height": 22,
                    "filled": True,
                }
            ],
        }
    )
    output = render_document(document, {}, RenderSpec(printable_widths_mm=caps.printable_widths_mm))
    assert output.warnings and "clipped" in output.warnings[0]
    from PIL import ImageOps

    ink = ImageOps.invert(output.image.convert("L")).convert("1")
    assert encode_raster(RenderedLabel("one", 24, 60, *ink.size, ink.tobytes()))


def test_strip_mode_and_estimate_are_explicit() -> None:
    transport = Transport()
    backend = BrotherPTP710BT(transport, cut_each=False, feed_mm=3, leader_mm=25)
    backend.print_batch([label(), label()])
    assert all(b"\x1biM\x00" in data for data in transport.writes if data.startswith(b"\x1biz"))
    plan = backend.plan_batch([label(), label()])
    assert not plan.cut_each and not plan.calibrated
    assert plan.estimated_mm == pytest.approx(25 + 120 + 4 * 21 * 25.4 / 180)


@pytest.mark.parametrize("resolution,dpi_x", [("normal", 180), ("high", 360)])
def test_configured_brother_uses_real_capabilities_and_builtin_layout(
    client, resolution, dpi_x
) -> None:
    from conftest import create_test_app as create_app
    from conftest import install, profile
    from fastapi.testclient import TestClient

    from app.models import PrinterDevice

    settings = client.app.state.settings
    with client.app.state.factory.begin() as session:
        printer = session.get(PrinterDevice, "main")
        printer.driver = "brother-pt-p710bt"
        printer.config = {"resolution": resolution}
    client.__exit__(None, None, None)
    transport = Transport()
    with TestClient(
        create_app(settings, {"main": BrotherPTP710BT(transport)}, start_worker=False)
    ) as real:
        tape = profile(real, threshold=1)
        install(real, tape["id"])
        response = real.post(
            "/api/jobs", json={"tape_profile": tape["id"], "data": {"text": "Physical layout"}}
        )
        assert response.status_code == 201, response.text
        assert response.json()["template_snapshot"]["render_spec"]["dpi_x"] == dpi_x
        assert real.get("/api/printers").json()[0]["capabilities"]["dpi_x"] == dpi_x
        assert real.get("/api/status").json()["backend"] == "brother-pt-p710bt"
        assert real.get("/api/printer/mock").status_code == 404
        real.app.state.fleet.workers["main"].tick()
        assert real.get(f"/api/jobs/{response.json()['id']}").json()["status"] == "printed"
        assert transport.pages == 1


def test_resolution_is_selected_per_frozen_label_in_a_mixed_batch() -> None:
    from dataclasses import replace

    standard = label()
    image = Image.new("1", (850, 170))
    image.putpixel((5, 21), 1)
    high = replace(standard, pixel_width=850, raster=image.tobytes(), dpi_x=360)
    assert len(encode_raster(high)) == 850 * 20
    transport = Transport()
    BrotherPTP710BT(transport).print_batch([high, standard, high])
    pages = [data for data in transport.writes if data.startswith(b"\x1biz")]
    for page, dots, mode, feed in zip(pages, (850, 425, 850), (0x40, 0, 0x48), (28, 14, 28)):
        assert page[7:11] == dots.to_bytes(4, "little")
        assert b"\x1biK" + bytes([mode]) in page
        assert b"\x1bid" + feed.to_bytes(2, "little") in page
    assert pages[-1].endswith(b"\x1a")
    bad = replace(high, dpi_x=180)
    transport = Transport()
    with pytest.raises(PrintNotStarted, match="dimensions"):
        BrotherPTP710BT(transport).print_batch([bad])
    assert not transport.writes


def test_acceptance_generator_only_prepares_a_draft(client, monkeypatch, capsys) -> None:
    import sys

    from conftest import profile

    from scripts import prepare_acceptance

    tape = profile(client)

    def request(server, path, body, raw=False):
        response = client.post("/api" + path, **({"content": body} if raw else {"json": body}))
        assert response.status_code in (200, 201), response.text
        return response.json()

    monkeypatch.setattr(prepare_acceptance, "request", request)
    monkeypatch.setattr(sys, "argv", ["prepare_acceptance", "--profile", tape["id"]])
    prepare_acceptance.main()
    assert "/#/runs/" in capsys.readouterr().out
    assert client.get("/api/jobs").json() == []
    draft = client.get("/api/runs").json()[0]
    assert draft["copies"] == 3 and draft["submitted_at"] is None


def test_final_cut_error_in_separate_usb_transfer_requires_review() -> None:
    class LateError(Transport):
        def write(self, data: bytes) -> None:
            super().write(data)
            if data.startswith(b"\x1biz"):
                self.pending.append(packet(2, error=4))

    transport = LateError()
    with pytest.raises(PrintInterrupted) as error:
        BrotherPTP710BT(transport).print_batch([label()])
    assert error.value.confirmed_labels == 0


def test_multi_page_completion_survives_empty_usb_transfers() -> None:
    class EmptyPacketTransport(Transport):
        def write(self, data: bytes) -> None:
            super().write(data)
            # Include empty transfers before/between fragmented and coalesced statuses,
            # and after the final completion. No real USB device is opened.
            replies = list(self.pending)
            self.pending.clear()
            for reply in replies:
                self.pending.extend((b"", reply, b""))

        def read(self, size: int, timeout_seconds: float) -> bytes:
            def device_read(*args, **kwargs):
                if self.pending:
                    return self.pending.popleft()
                raise usb.core.USBTimeoutError("timeout")

            transport = UsbTransport(0x04F9, 0x20AF)
            transport.device = SimpleNamespace(read=device_read)
            return transport.read(size, timeout_seconds)

    transport = EmptyPacketTransport()
    assert BrotherPTP710BT(transport).print_batch([label()] * 3).consumed_mm is None
    assert transport.pages == 3
    assert not transport.opened


class ControlledTransport(Transport):
    """Completion follows the terminal command, rather than the page header."""

    def write(self, data: bytes) -> None:
        super().write(data)
        if data.startswith(b"\x1biz"):
            self.pending.clear()
        elif data in (b"\x0c", b"\x1a"):
            self.pending.extend((packet(6, 1), packet(1), packet(6)))


@pytest.mark.parametrize("mode", ["after_current", "emergency"])
def test_stop_before_transmission_never_opens_printer(mode) -> None:
    control = PrintControl()
    control.request(mode)
    transport = ControlledTransport()
    with pytest.raises(PrintNotStarted, match="before transmission"):
        BrotherPTP710BT(transport).print_batch_controlled([label()], control)
    assert not transport.opened and not transport.writes


def test_stop_after_initialization_before_first_page_has_no_raster_or_print_command() -> None:
    control = PrintControl()

    class StopOnInitialize(ControlledTransport):
        def write(self, data: bytes) -> None:
            super().write(data)
            if data.startswith(b"\x00" * 100):
                control.request("after_current")

    transport = StopOnInitialize()
    with pytest.raises(PrintNotStarted, match="stopped"):
        BrotherPTP710BT(transport).print_batch_controlled([label()], control)
    assert transport.pages == 0
    assert transport.writes[-1] == b"\x1b@"
    assert not transport.opened


def test_stop_capabilities_do_not_advertise_an_unsupported_manual_cutter() -> None:
    modes = capabilities()
    assert modes.supports_stop_after_current and modes.supports_emergency_stop
    assert modes.supports_cut and not modes.supports_manual_cut


def test_emergency_during_upload_cancels_at_a_raster_command_boundary() -> None:
    control = PrintControl()

    class StopOnRaster(ControlledTransport):
        def write(self, data: bytes) -> None:
            super().write(data)
            if data.startswith(b"G"):
                control.request("emergency")

    transport = StopOnRaster()
    with pytest.raises(PrintInterrupted, match="Emergency stop") as interrupted:
        BrotherPTP710BT(transport).print_batch_controlled([label()] * 3, control)
    assert interrupted.value.confirmed_labels == 0
    raster_writes = [data for data in transport.writes if data.startswith(b"G")]
    assert raster_writes == [encode_raster(label())[:3200]]
    assert len(raster_writes[0]) % 20 == 0
    assert transport.writes[-1] == b"\x1b@"
    assert b"\x0c" not in transport.writes and b"\x1a" not in transport.writes
    assert transport.pages == 1 and not transport.opened
    assert transport.writes.count(b"\x1biS") == 1


def test_after_current_finishes_upload_and_waits_before_cancelling_chain() -> None:
    control = PrintControl()

    class StopOnRaster(ControlledTransport):
        def write(self, data: bytes) -> None:
            super().write(data)
            if data.startswith(b"G"):
                control.request("after_current")

    transport = StopOnRaster()
    with pytest.raises(PrintInterrupted, match="after the current label") as interrupted:
        BrotherPTP710BT(transport).print_batch_controlled([label()] * 3, control)
    assert interrupted.value.confirmed_labels == 0
    assert b"".join(data for data in transport.writes if data.startswith(b"G")) == encode_raster(
        label()
    )
    assert transport.writes[-2:] == [b"\x0c", b"\x1b@"]
    assert not transport.pending  # Page completion and idle were read before cancelling.
    assert transport.pages == 1 and not transport.opened


def test_stopped_batch_only_preserves_certain_prefix() -> None:
    control = PrintControl()

    class StopThirdPage(ControlledTransport):
        def write(self, data: bytes) -> None:
            super().write(data)
            if self.pages == 3 and data.startswith(b"G"):
                control.request("after_current")

    transport = StopThirdPage()
    with pytest.raises(PrintInterrupted) as interrupted:
        BrotherPTP710BT(transport).print_batch_controlled([label()] * 4, control)
    assert interrupted.value.confirmed_labels == 2
    assert transport.pages == 3
    assert transport.writes.count(b"\x0c") == 3
    assert transport.writes[-1] == b"\x1b@"


def test_emergency_upgrade_interrupts_after_current_while_waiting_for_status() -> None:
    control = PrintControl()

    class UpgradeOnWait(ControlledTransport):
        def write(self, data: bytes) -> None:
            super().write(data)
            if data.startswith(b"G"):
                control.request("after_current")
            if data == b"\x0c":
                self.pending.clear()

        def read(self, size: int, timeout_seconds: float) -> bytes:
            if self.pages and not self.pending:
                assert timeout_seconds <= 0.1
                control.request("emergency")
                raise TimeoutError("No completion yet")
            return super().read(size, timeout_seconds)

    transport = UpgradeOnWait()
    with pytest.raises(PrintInterrupted, match="Emergency stop") as interrupted:
        BrotherPTP710BT(transport).print_batch_controlled([label()] * 2, control)
    assert interrupted.value.confirmed_labels == 0
    assert control.mode == "emergency"
    assert transport.writes[-2:] == [b"\x0c", b"\x1b@"]
    assert transport.pages == 1 and not transport.opened


def test_controlled_status_poll_preserves_fragments_and_overall_deadline(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("app.printer.brother.time.monotonic", lambda: clock[0])
    control = PrintControl()

    class DelayedFragment(ControlledTransport):
        def __init__(self):
            super().__init__()
            self.waits = []

        def write(self, data: bytes) -> None:
            super().write(data)
            if data == b"\x1a":
                statuses = b"".join(self.pending)
                self.pending.clear()
                self.pending.extend((statuses[:5], b"wait", statuses[5:]))

        def read(self, size: int, timeout_seconds: float) -> bytes:
            if self.pages:
                self.waits.append(timeout_seconds)
            if self.pending and self.pending[0] == b"wait":
                self.pending.popleft()
                clock[0] += timeout_seconds
                raise TimeoutError("Still printing")
            if not self.pending:
                clock[0] += timeout_seconds
            return super().read(size, timeout_seconds)

    transport = DelayedFragment()
    assert (
        BrotherPTP710BT(transport, timeout=0.3)
        .print_batch_controlled([label()], control)
        .consumed_mm
        is None
    )
    assert max(transport.waits) <= 0.1
    assert transport.pages == 1 and not transport.opened
    assert b"\x1b@" not in transport.writes


def test_controlled_status_timeouts_do_not_reset_the_completion_deadline(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("app.printer.brother.time.monotonic", lambda: clock[0])

    class NoCompletion(ControlledTransport):
        def write(self, data: bytes) -> None:
            super().write(data)
            if data in (b"\x0c", b"\x1a"):
                self.pending.clear()

        def read(self, size: int, timeout_seconds: float) -> bytes:
            if not self.pending:
                clock[0] += timeout_seconds
            return super().read(size, timeout_seconds)

    transport = NoCompletion()
    with pytest.raises(PrintInterrupted, match="timed out"):
        BrotherPTP710BT(transport, timeout=0.3).print_batch_controlled([label()], PrintControl())
    assert clock[0] == pytest.approx(0.32)
    assert transport.pages == 1 and not transport.opened
    assert b"\x1b@" not in transport.writes  # Unknown write failures never provoke blind retries.


def test_cancellation_write_failure_stays_uncertain_and_is_not_retried() -> None:
    control = PrintControl()

    class FailedCancellation(ControlledTransport):
        def write(self, data: bytes) -> None:
            super().write(data)
            if data.startswith(b"G"):
                control.request("emergency")
            if data == b"\x1b@":
                raise OSError("USB disconnected")

    transport = FailedCancellation()
    with pytest.raises(PrintInterrupted, match="cancellation could not be confirmed"):
        BrotherPTP710BT(transport).print_batch_controlled([label()], control)
    assert transport.writes.count(b"\x1b@") == 1
    assert not transport.opened
