"""Versioned, bounded wire objects shared by the server and lightweight executor."""

import base64
import hashlib
import json
from dataclasses import asdict
from typing import Any, Literal

from pydantic import Field, model_validator

from app.printer.base import RenderedLabel
from app.schemas import Input


class WireLabel(Input):
    copy_id: str = Field(min_length=1, max_length=100)
    tape_width_mm: float = Field(gt=0, le=1000)
    length_mm: float = Field(gt=0, le=10000)
    pixel_width: int = Field(gt=0, le=32000)
    pixel_height: int = Field(gt=0, le=32000)
    raster: str = Field(max_length=4_000_000)
    dpi_x: int = Field(gt=0, le=2400)
    dpi_y: int = Field(gt=0, le=2400)
    canvas_width_mm: float | None = Field(default=None, gt=0, le=1000)
    template_padding_mm: float = Field(default=0, ge=0, le=1000)

    @model_validator(mode="after")
    def valid_raster(self) -> "WireLabel":
        try:
            data = base64.b64decode(self.raster, validate=True)
        except ValueError as error:
            raise ValueError("Invalid raster encoding") from error
        if len(data) != ((self.pixel_width + 7) // 8) * self.pixel_height:
            raise ValueError("Raster dimensions do not match its data")
        return self

    def rendered(self) -> RenderedLabel:
        return RenderedLabel(**{**self.model_dump(), "raster": base64.b64decode(self.raster)})

    @classmethod
    def from_rendered(cls, label: RenderedLabel) -> "WireLabel":
        return cls.model_validate(
            {**asdict(label), "raster": base64.b64encode(label.raster).decode("ascii")}
        )


class BatchEnvelope(Input):
    version: Literal[1] = 1
    batch_id: str = Field(min_length=1, max_length=100)
    printer_id: str = Field(min_length=1, max_length=100)
    local_id: str = Field(min_length=1, max_length=100)
    driver: str = Field(min_length=1, max_length=100)
    configuration: dict[str, Any]
    labels: list[WireLabel] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def bounded_batch(self) -> "BatchEnvelope":
        if sum(len(label.raster) for label in self.labels) > 32_000_000:
            raise ValueError("Rendered batch exceeds transfer limit")
        if len({label.copy_id for label in self.labels}) != len(self.labels):
            raise ValueError("Duplicate copy identity")
        return self


class BatchReceipt(Input):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExecutionResult(BatchReceipt):
    go_token: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    outcome: Literal["printed", "not_started", "interrupted"]
    confirmed_labels: int = Field(default=0, ge=0, le=1000)
    consumed_mm: float | None = Field(default=None, ge=0, le=10_000_000)


def payload_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
