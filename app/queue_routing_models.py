"""Append-only destination changes, retained independently of jobs and accounts."""

import time

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, new_id


class QueueDestinationChange(Base):
    __tablename__ = "queue_destination_changes"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String)
    job_name: Mapped[str]
    copy_ids: Mapped[list[str]] = mapped_column(JSON)
    actor: Mapped[dict[str, str]] = mapped_column(JSON)
    source_id: Mapped[str] = mapped_column(String, index=True)
    target_id: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[dict[str, str]] = mapped_column(JSON)
    target: Mapped[dict[str, str]] = mapped_column(JSON)
    previous_assignment: Mapped[dict[str, str] | None] = mapped_column(JSON)
    reason: Mapped[str]
    created_at: Mapped[float] = mapped_column(default=time.time, index=True)
