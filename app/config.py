from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABEL_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/labels.db"
    worker_interval_seconds: float = Field(default=2, gt=0)
    printer_backend: Literal["mock", "brother-pt-p710bt"] = "mock"
    printer_usb_serial: str | None = None
    printer_timeout_seconds: float = Field(default=120, ge=5, le=600)
    printer_feed_mm: float = Field(default=2, ge=2, le=127)
    printer_leader_mm: float = Field(default=24.5, ge=0, le=200)
    printer_cut_each: bool = True
    printer_resolution: Literal["normal", "high"] = "normal"
    mock_tape_width_mm: int = Field(default=24, gt=0)
    ntfy_url: str = ""
    ntfy_topic: str = ""
    ntfy_token: SecretStr = SecretStr("")
    public_url: str = "http://localhost:8000"
    frontend_dist: Path = Path(__file__).resolve().parent.parent / "frontend" / "dist"

    @model_validator(mode="after")
    def validate_notifications(self) -> "Settings":
        if bool(self.ntfy_url) != bool(self.ntfy_topic):
            raise ValueError("Set both ntfy URL and topic, or neither")
        return self
