"""Configured device construction; protocol choices remain inside printer adapters."""

from app.config import Settings
from app.printer.base import PrinterBackend
from app.printer.brother import PRODUCT_ID, VENDOR_ID, BrotherPTP710BT, capabilities
from app.printer.mock import MockPrinterBackend
from app.printer.registry import MediaKind, PrinterCapabilities, PrinterDefinition, UsbConnection
from app.printer.usb import UsbTransport


def configured_printer(settings: Settings) -> tuple[PrinterDefinition, PrinterBackend]:
    if settings.printer_backend == "mock":
        return (
            PrinterDefinition(
                "main",
                "Mock printer",
                "mock",
                None,
                PrinterCapabilities(
                    MediaKind.CONTINUOUS,
                    180,
                    180,
                    (4, 6, 9, 12, 18, 24),
                    1,
                    resolution_modes={"normal": (180, 180), "high": (360, 180)},
                ),
            ),
            MockPrinterBackend(settings.mock_tape_width_mm),
        )
    connection = UsbConnection(
        vendor_id=VENDOR_ID, product_id=PRODUCT_ID, serial=settings.printer_usb_serial
    )
    return (
        PrinterDefinition(
            "main",
            "Brother PT-P710BT",
            "brother-pt-p710bt",
            connection,
            capabilities(high_resolution=settings.printer_resolution == "high"),
        ),
        BrotherPTP710BT(
            UsbTransport(VENDOR_ID, PRODUCT_ID, settings.printer_usb_serial),
            timeout=settings.printer_timeout_seconds,
            feed_mm=settings.printer_feed_mm,
            leader_mm=settings.printer_leader_mm,
            cut_each=settings.printer_cut_each,
        ),
    )
