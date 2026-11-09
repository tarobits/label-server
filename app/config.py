from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LABEL_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: str = Field(default="sqlite:///./data/labels.db", repr=False)
    data_dir: Path | None = None
    asset_cache_idle_seconds: int = Field(default=604800, ge=60)

    @property
    def state_directory(self) -> Path:
        if self.data_dir is not None:
            return self.data_dir.resolve()
        url = make_url(self.database_url)
        if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
            return Path(url.database).resolve().parent
        return Path("data").resolve()

    @property
    def worker_lock_path(self) -> Path:
        url = make_url(self.database_url)
        if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
            return Path(url.database).resolve().with_suffix(".worker.lock")
        return self.state_directory / "server.worker.lock"

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
