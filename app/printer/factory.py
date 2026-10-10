"""Configured device construction; protocol choices remain inside printer adapters."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.printer.base import PrinterBackend
from app.printer.brother import PRODUCT_ID, VENDOR_ID, BrotherPTP710BT, capabilities
from app.printer.registry import PrinterDefinition, UsbConnection
from app.printer.usb import UsbTransport


class DeviceConfiguration(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    usb_serial: str | None = Field(default=None, min_length=1, max_length=128)
    resolution: Literal["normal", "high"] = "normal"
    timeout_seconds: float = Field(default=120, ge=5, le=600)
    feed_mm: float = Field(default=2, ge=2, le=127)
    leader_mm: float = Field(default=24.5, ge=0, le=200)
    cut_each: bool = True


def configured_printer(
    driver: str, config: dict[str, Any]
) -> tuple[PrinterDefinition, PrinterBackend]:
    if driver != "brother-pt-p710bt":
        raise ValueError("Unsupported printer driver")
    config = DeviceConfiguration.model_validate(config).model_dump()
    connection = UsbConnection(
        vendor_id=VENDOR_ID, product_id=PRODUCT_ID, serial=config.get("usb_serial")
    )
    return (
        PrinterDefinition(
            "",
            "Brother PT-P710BT",
            "brother-pt-p710bt",
            connection,
            capabilities(high_resolution=config.get("resolution", "normal") == "high"),
        ),
        BrotherPTP710BT(
            UsbTransport(VENDOR_ID, PRODUCT_ID, config.get("usb_serial")),
            timeout=config.get("timeout_seconds", 120),
            feed_mm=config.get("feed_mm", 2),
            leader_mm=config.get("leader_mm", 24.5),
            cut_each=config.get("cut_each", True),
        ),
    )
