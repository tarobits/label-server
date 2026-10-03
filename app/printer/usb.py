"""PyUSB bulk transport. Discovery is restricted to an explicit USB device model."""

import time
from typing import Any

import usb.core  # type: ignore[import-untyped]
import usb.util  # type: ignore[import-untyped]


class UsbTransport:
    def __init__(self, vendor_id: int, product_id: int, serial: str | None = None):
        self.vendor_id, self.product_id, self.serial = vendor_id, product_id, serial
        self.device: Any = None
        self.detached = False
        self.claimed = False
        self.interface = 0
        self.in_endpoint = 0
        self.out_endpoint = 0

    def open(self) -> None:
        if self.device is not None:
            return
        devices = list(
            usb.core.find(find_all=True, idVendor=self.vendor_id, idProduct=self.product_id)
        )
        if self.serial:
            devices = [device for device in devices if device.serial_number == self.serial]
        if len(devices) != 1:
            raise OSError(
                "USB printer not found"
                if not devices
                else "Multiple matching USB printers; configure a serial number"
            )
        self.device = devices[0]
        try:
            try:
                config = self.device.get_active_configuration()
            except usb.core.USBError:
                self.device.set_configuration()
                config = self.device.get_active_configuration()
            interface = next((item for item in config if item.bInterfaceClass == 7), None)
            if interface is None:
                raise OSError("USB printer interface not found")
            self.interface = interface.bInterfaceNumber
            try:
                if self.device.is_kernel_driver_active(self.interface):
                    self.device.detach_kernel_driver(self.interface)
                    self.detached = True
            except NotImplementedError:
                pass
            usb.util.claim_interface(self.device, self.interface)
            self.claimed = True
            for endpoint in interface:
                if usb.util.endpoint_type(endpoint.bmAttributes) != usb.util.ENDPOINT_TYPE_BULK:
                    continue
                if usb.util.endpoint_direction(endpoint.bEndpointAddress) == usb.util.ENDPOINT_IN:
                    self.in_endpoint = endpoint.bEndpointAddress
                else:
                    self.out_endpoint = endpoint.bEndpointAddress
            if not self.in_endpoint or not self.out_endpoint:
                raise OSError("USB bulk endpoints not found")
        except Exception:
            self.close()
            raise

    def write(self, data: bytes) -> None:
        if self.device is None:
            raise OSError("USB transport is closed")
        # A short write is uncertain: do not blindly resend a partly delivered command.
        for start in range(0, len(data), 16384):
            chunk = data[start : start + 16384]
            if self.device.write(self.out_endpoint, chunk, timeout=5000) != len(chunk):
                raise OSError("Incomplete USB write")

    def read(self, size: int, timeout_seconds: float) -> bytes:
        if self.device is None:
            raise OSError("USB transport is closed")
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("USB read timed out")
            try:
                data = bytes(
                    self.device.read(
                        self.in_endpoint, size, timeout=max(1, round(remaining * 1000))
                    )
                )
            except usb.core.USBTimeoutError as error:
                raise TimeoutError("USB read timed out") from error
            if data:
                return data
            # A successful zero-length bulk transfer is a USB packet boundary,
            # not EOF. Keep the original deadline; actual disconnects raise USBError.

    def close(self) -> None:
        device, self.device = self.device, None
        if device is None:
            return
        try:
            if self.claimed:
                usb.util.release_interface(device, self.interface)
            if self.detached:
                device.attach_kernel_driver(self.interface)
        except (usb.core.USBError, NotImplementedError):
            pass
        finally:
            usb.util.dispose_resources(device)
            self.claimed = self.detached = False
            self.in_endpoint = self.out_endpoint = 0
