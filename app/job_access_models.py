"""Durable administrator decisions for queued work after access revocation."""

import time

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class JobAccessHold(Base):
    __tablename__ = "job_access_holds"
    resolved_by_snapshot: Mapped[dict[str, str] | None] = mapped_column(JSON)
    job_id: Mapped[str] = mapped_column(ForeignKey("print_jobs.id"), primary_key=True)
    reason: Mapped[str]
    held_at: Mapped[float] = mapped_column(default=time.time)
    status: Mapped[str] = mapped_column(String, default="held")
    resolved_at: Mapped[float | None]
    resolved_by: Mapped[str | None]
