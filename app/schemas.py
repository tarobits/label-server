from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProfileInput(Input):
    name: str = Field(min_length=1, max_length=100)
    width_mm: Literal[4, 6, 9, 12, 18, 24]
    foreground: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")
    background: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    auto_print_threshold: int = Field(default=10, ge=1, le=10000)
    waiting_notification_enabled: bool = False
    waiting_notification_interval_seconds: int = Field(default=86400, ge=60)


class CartridgeInput(Input):
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


class JobInput(Input):
    template: str = Field(default="text", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    tape_profile: str
    copies: int = Field(default=1, ge=1, le=1000)
    length_mm: float | None = Field(default=None, ge=10, le=1000)
    data: dict[str, str] = Field(max_length=20)


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


class MockPrinterInput(Input):
    connected: bool
    tape_width_mm: int | None = Field(default=24, ge=1, le=100)
    fail_after: int | None = Field(default=None, ge=0, le=1000)


class AutomaticPrintingInput(Input):
    held: bool


class CopySelectionInput(Input):
    copy_ids: list[str] = Field(min_length=1, max_length=10000)
