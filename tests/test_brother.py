from collections import deque
from types import SimpleNamespace

import pytest
import usb.core
from PIL import Image

from app.printer.base import PrintInterrupted, PrintNotStarted, RenderedLabel
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
