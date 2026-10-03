from types import SimpleNamespace

import pytest
import usb.core

from app.printer.usb import UsbTransport


class Interface(list):
    bInterfaceClass = 7
    bInterfaceNumber = 0


class Device:
    serial_number = "test-serial"

    def __init__(self):
        self.detached = self.attached = False
        self.short = False

    def get_active_configuration(self):
        return [
            Interface(
                [
                    SimpleNamespace(bmAttributes=2, bEndpointAddress=0x81),
                    SimpleNamespace(bmAttributes=2, bEndpointAddress=2),
                ]
            )
        ]

    def is_kernel_driver_active(self, number):
        return True

    def detach_kernel_driver(self, number):
        self.detached = True

    def attach_kernel_driver(self, number):
        self.attached = True

    def write(self, endpoint, data, timeout):
        assert endpoint == 2 and timeout == 5000
        return len(data) - int(self.short)

    def read(self, endpoint, size, timeout):
        assert endpoint == 0x81
        raise usb.core.USBTimeoutError("timeout")


def test_usb_claim_endpoints_timeout_short_write_and_cleanup(monkeypatch):
    device = Device()
    calls = []
    monkeypatch.setattr("usb.core.find", lambda **kwargs: [device])
    monkeypatch.setattr("usb.util.claim_interface", lambda *args: calls.append("claim"))
    monkeypatch.setattr("usb.util.release_interface", lambda *args: calls.append("release"))
    monkeypatch.setattr("usb.util.dispose_resources", lambda *args: calls.append("dispose"))
    transport = UsbTransport(0x04F9, 0x20AF, "test-serial")
    transport.open()
    assert device.detached
    transport.write(b"x" * 20000)
    with pytest.raises(TimeoutError):
        transport.read(64, 1)
    device.short = True
    with pytest.raises(OSError, match="Incomplete"):
        transport.write(b"print data")
    transport.close()
    assert calls == ["claim", "release", "dispose"] and device.attached
    transport.close()
    assert calls == ["claim", "release", "dispose"]


def test_usb_requires_unambiguous_device(monkeypatch):
    monkeypatch.setattr("usb.core.find", lambda **kwargs: [Device(), Device()])
    with pytest.raises(OSError, match="Multiple"):
        UsbTransport(0x04F9, 0x20AF).open()


def test_empty_usb_packets_are_skipped_without_resetting_deadline(monkeypatch):
    times = iter([10.0, 10.1, 10.4, 10.8])
    monkeypatch.setattr("app.printer.usb.time.monotonic", lambda: next(times))
    replies = iter([b"", b"", b"status"])
    timeouts = []

    def read(endpoint, size, timeout):
        timeouts.append(timeout)
        return next(replies)

    transport = UsbTransport(0x04F9, 0x20AF)
    transport.device = SimpleNamespace(read=read)
    assert transport.read(64, 1) == b"status"
    assert timeouts == [900, 600, 200]


def test_only_empty_usb_packets_still_time_out(monkeypatch):
    times = iter([10.0, 10.1, 11.0])
    monkeypatch.setattr("app.printer.usb.time.monotonic", lambda: next(times))
    transport = UsbTransport(0x04F9, 0x20AF)
    transport.device = SimpleNamespace(read=lambda *args, **kwargs: b"")
    with pytest.raises(TimeoutError, match="USB read timed out"):
        transport.read(64, 1)


def test_real_usb_disconnect_is_not_swallowed():
    def read(*args, **kwargs):
        raise usb.core.USBError("No such device", error_code=-4)

    transport = UsbTransport(0x04F9, 0x20AF)
    transport.device = SimpleNamespace(read=read)
    with pytest.raises(usb.core.USBError, match="No such device"):
        transport.read(64, 1)
