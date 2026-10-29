from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ProcessName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProfileInput(Input):
    name: str = Field(min_length=1, max_length=100)
    width_mm: float = Field(gt=0, le=100)
    foreground: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")
    background: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    auto_print_threshold: int = Field(default=10, ge=1, le=10000)
    waiting_notification_enabled: bool = False
    waiting_notification_interval_seconds: int = Field(default=86400, ge=60)


class CartridgePriceInput(Input):
    price_minor: int | None = Field(default=None, ge=0, le=1000000000, strict=True)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")


class CartridgeInput(CartridgePriceInput):
    profile_id: str
    name: str = Field(min_length=1, max_length=100)
    nominal_length_mm: float = Field(gt=0, le=1000000)
    remaining_mm: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_remaining(self) -> "CartridgeInput":
        if self.remaining_mm is not None and self.remaining_mm > self.nominal_length_mm:
            raise ValueError("Remaining length exceeds nominal length")
        return self


class RemainingInput(Input):
    remaining_mm: float = Field(ge=0)


class ActiveTapeInput(Input):
    cartridge_id: str | None
    media_confirmation: str | None = Field(default=None, max_length=64)


class CartridgeCheckInput(Input):
    enabled: bool


class JobInput(Input):
    process_name: ProcessName | None = None
    destination_id: str | None = None
    template: str = Field(default="text", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    tape_profile: str
    copies: int = Field(default=1, ge=1, le=1000)
    length_mm: float | None = Field(default=None, ge=10, le=300)
    data: dict[str, str] = Field(max_length=20)


class ImageJobInput(Input):
    process_name: ProcessName | None = None
    destination_id: str | None = None
    image_asset: str = Field(pattern=r"^[a-f0-9]{64}$")
    tape_profile: str
    copies: int = Field(default=1, ge=1, le=1000)
    length_mm: float | None = Field(default=None, ge=10, le=300)
    print_resolution: Literal["printer", "normal", "high"] = "printer"
    image_mode: Literal["threshold", "dither"] = "threshold"
    image_threshold: int = Field(default=128, ge=1, le=255)


class ReminderInput(Input):
    action: Literal["silence", "snooze", "resume"]
    until: float | None = None

    @model_validator(mode="after")
    def check_snooze(self) -> "ReminderInput":
        if self.action == "snooze" and self.until is None:
            raise ValueError("Snooze requires a UTC epoch timestamp")
        return self


class ReviewInput(Input):
    decisions: dict[str, Literal["printed", "queued", "cancelled"]]
    consumed_mm: float = Field(
        ge=0,
        description="Total tape consumed by this attempt, including confirmed copies and waste",
    )


class AutomaticPrintingInput(Input):
    held: bool


class PrinterStopInput(Input):
    mode: Literal["after_current", "emergency"]


class CopySelectionInput(Input):
    copy_ids: list[str] = Field(min_length=1, max_length=10000)


class PrinterInput(Input):
    name: str = Field(min_length=1, max_length=100)
    driver: str = Field(default="brother-pt-p710bt", min_length=1, max_length=100)
    usb_serial: str | None = Field(default=None, min_length=1, max_length=128)
    resolution: Literal["normal", "high"] = "normal"
    feed_mm: float = Field(default=2, ge=2, le=127)
    leader_mm: float = Field(default=24.5, ge=0, le=200)
    cut_each: bool = True
    timeout_seconds: float = Field(default=120, ge=5, le=600)


class PrinterGroupInput(Input):
    name: str = Field(min_length=1, max_length=100)
    printer_ids: list[str] = Field(min_length=1, max_length=32)
