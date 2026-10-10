from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABEL_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/labels.db"
    worker_interval_seconds: float = Field(default=2, gt=0)
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
