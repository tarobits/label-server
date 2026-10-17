from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LABEL_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/labels.db"
    worker_interval_seconds: float = Field(default=2, gt=0)
    public_url: str = "http://localhost:8000"
    frontend_dist: Path = Path(__file__).resolve().parent.parent / "frontend" / "dist"
