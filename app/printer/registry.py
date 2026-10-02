"""Device/driver/transport separation for future multi-printer orchestration.

A Wi-Fi printer is a network endpoint, not a different label format. Registration
alone must never open a connection or imply that a device has a working driver.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.printer.base import PrinterBackend


class MediaKind(str, Enum):
    CONTINUOUS = "continuous"
    FIXED_LABEL = "fixed_label"


class UsbConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["usb"] = "usb"
    serial: str | None = None
    vendor_id: int = Field(ge=0, le=65535)
    product_id: int = Field(ge=0, le=65535)


class NetworkConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["network"] = "network"
    link: Literal["wifi", "ethernet", "unspecified"] = "unspecified"
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    protocol: Literal["raw_tcp", "ipp", "ipps", "vendor"]
    # Secrets belong in deployment configuration, not device descriptors or UI responses.
    credential_reference: str | None = None


@dataclass(frozen=True)
class PrinterCapabilities:
    media_kind: MediaKind
    dpi_x: int
    dpi_y: int
    supported_widths_mm: tuple[float, ...]
    printable_margin_mm: float
    fixed_label_sizes_mm: tuple[tuple[float, float], ...] = ()
    supports_cut: bool = False
    supports_consecutive: bool = False


@dataclass(frozen=True)
class PrinterDefinition:
    id: str
    name: str
    driver: str
    connection: UsbConnection | NetworkConnection | None
    capabilities: PrinterCapabilities


class ByteTransport(Protocol):
    """Implemented by a future USB or network transport; no queue/domain state."""

    def open(self) -> None: ...
    def write(self, data: bytes) -> None: ...
    def read(self, size: int, timeout_seconds: float) -> bytes: ...
    def close(self) -> None: ...


class PrinterRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, PrinterDefinition] = {}
        self._backends: dict[str, PrinterBackend] = {}

    def register(
        self, definition: PrinterDefinition, backend: PrinterBackend | None = None
    ) -> None:
        if definition.id in self._definitions:
            raise ValueError("Printer ID already registered")
        self._definitions[definition.id] = definition
        if backend is not None:
            self._backends[definition.id] = backend

    def definitions(self) -> tuple[PrinterDefinition, ...]:
        return tuple(self._definitions.values())

    def definition(self, printer_id: str) -> PrinterDefinition:
        return self._definitions[printer_id]

    def backend(self, printer_id: str) -> PrinterBackend:
        if printer_id not in self._backends:
            raise ValueError("Printer has no enabled driver")
        return self._backends[printer_id]
