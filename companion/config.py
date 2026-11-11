from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.printer.factory import DeviceConfiguration


class LocalPrinter(BaseModel):
    local_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    driver: str = "brother-pt-p710bt"
    configuration: DeviceConfiguration = Field(default_factory=DeviceConfiguration)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LABEL_COMPANION_",
        env_file=".env.companion",
        extra="ignore",
        hide_input_in_errors=True,
    )
    server_url: str
    api_key: SecretStr
    status_api_key: SecretStr = SecretStr("")
    data_dir: Path = Path("data/companion")
    printers: list[LocalPrinter] = Field(default_factory=list, max_length=32)
    single_user_id: str | None = None
    shared_pin: SecretStr | None = None
    lock_timeout_seconds: int = Field(default=300, ge=30, le=86400)
    show_locked_dashboard_details: bool = True
    pin_keypad_enabled: bool = False
    pin_keypad_shuffle: Literal["none", "once", "each_keypress"] = "none"
    allow_locked_emergency_stop: bool = False
    allow_locked_stop_after_label: bool = False
    allow_offline_emergency_stop: bool = False
    allow_offline_stop_after_label: bool = False
    public_url: str = "http://localhost:8001"
    host: str = "127.0.0.1"
    port: int = Field(default=8001, ge=1, le=65535)

    @model_validator(mode="after")
    def valid_deployment(self) -> "Settings":
        status_key = self.status_api_key.get_secret_value()
        if status_key and (
            not 32 <= len(status_key) <= 512
            or not status_key.isascii()
            or any(character.isspace() for character in status_key)
            or status_key == self.api_key.get_secret_value()
        ):
            raise ValueError(
                "Status API key must be a separate 32–512 character ASCII token without whitespace"
            )
        for value in (self.server_url, self.public_url):
            url = urlsplit(value)
            if (
                url.scheme not in ("https", "http")
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("Use an HTTP(S) URL without credentials, query, or fragment")
            if url.scheme != "https" and url.hostname not in (
                "localhost",
                "127.0.0.1",
                "::1",
                "testserver",
            ):
                raise ValueError("Non-local connections require HTTPS")
        self.server_url = self.server_url.rstrip("/")
        if len({device.local_id for device in self.printers}) != len(self.printers):
            raise ValueError("Each printer needs a unique local ID")
        if bool(self.single_user_id) != bool(self.shared_pin):
            raise ValueError("Single-user mode requires both a user ID and shared PIN")
        if self.shared_pin:
            pin = self.shared_pin.get_secret_value()
            if not 4 <= len(pin) <= 12 or not pin.isascii() or not pin.isdigit():
                raise ValueError("Shared PIN must contain 4–12 digits")
        return self
