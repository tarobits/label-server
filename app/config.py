from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABEL_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/labels.db"
    worker_interval_seconds: float = Field(default=2, gt=0)
    public_url: str = "http://localhost:8000"
    trust_cloudflare_headers: bool = False
    frontend_dist: Path = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    check_for_updates: bool = True
    github_token: SecretStr | None = None
    github_token_file: Path | None = None
    vapid_private_key_file: Path | None = None
    vapid_subject: str = ""
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl", "plain"] = "starttls"
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_from: str = ""
    smtp_from_name: str = ""
