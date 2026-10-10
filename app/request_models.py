"""Frozen submissions awaiting an administrator's decision."""

import time
from typing import Any

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, new_id


class PrintRequest(Base):
    __tablename__ = "print_requests"
    requested_by: Mapped[dict[str, str] | None] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("owner_id", "request_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(index=True)
    destination_id: Mapped[str]
    kind: Mapped[str]
    run_id: Mapped[str | None] = mapped_column(unique=True)
    request_key: Mapped[str | None]
    request_hash: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    labels: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    job_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[float] = mapped_column(default=time.time)
    decided_at: Mapped[float | None]
    decided_by: Mapped[str | None]
    reason: Mapped[str | None]


class RequestDigest(Base):
    __tablename__ = "request_digest"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    first_at: Mapped[float]
    due_at: Mapped[float]
    count: Mapped[int] = mapped_column(default=1)
