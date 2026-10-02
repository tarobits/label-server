"""Persistent domain records. Lengths are in millimetres; times are UTC epoch seconds."""

import enum
import time
import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.identity import DEFAULT_PRINTER_ID, LOCAL_OWNER_ID


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class State(str, enum.Enum):
    QUEUED = "queued"
    PRINTING = "printing"
    PRINTED = "printed"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TapeProfile(Base):
    __tablename__ = "tape_profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str]
    width_mm: Mapped[int]
    foreground: Mapped[str] = mapped_column(default="#000000")
    background: Mapped[str] = mapped_column(default="#ffffff")
    auto_print_threshold: Mapped[int] = mapped_column(default=10)
    waiting_notification_enabled: Mapped[bool] = mapped_column(default=False)
    waiting_notification_interval_seconds: Mapped[int] = mapped_column(default=86400)
    reminder_silenced: Mapped[bool] = mapped_column(default=False)
    reminder_snoozed_until: Mapped[float | None]
    reminder_last_at: Mapped[float | None]
    reminder_episode: Mapped[int] = mapped_column(default=0)
    reminder_active: Mapped[bool] = mapped_column(default=False)


class Cartridge(Base):
    __tablename__ = "cartridges"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("tape_profiles.id"))
    name: Mapped[str]
    nominal_length_mm: Mapped[float]
    remaining_mm: Mapped[float]
    consumption_uncertain: Mapped[bool] = mapped_column(default=False)


class PrinterState(Base):
    __tablename__ = "printer_state"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    active_cartridge_id: Mapped[str | None] = mapped_column(ForeignKey("cartridges.id"))
    blocker: Mapped[str | None]
    automatic_printing_held: Mapped[bool] = mapped_column(default=False, server_default="0")


class LabelTemplate(Base):
    __tablename__ = "label_templates"
    scope: Mapped[str] = mapped_column(String, default="personal", server_default="personal")
    owner_id: Mapped[str] = mapped_column(
        String, default=LOCAL_OWNER_ID, server_default=LOCAL_OWNER_ID
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    archived: Mapped[bool] = mapped_column(default=False)


class TemplateRevision(Base):
    __tablename__ = "template_revisions"
    template_id: Mapped[str] = mapped_column(ForeignKey("label_templates.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    document: Mapped[dict[str, Any]] = mapped_column(JSON)


class PrintJob(Base):
    __tablename__ = "print_jobs"
    destination_id: Mapped[str] = mapped_column(
        String, default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    owner_id: Mapped[str] = mapped_column(
        String, default=LOCAL_OWNER_ID, server_default=LOCAL_OWNER_ID
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("tape_profiles.id"), index=True)
    template_id: Mapped[str]
    run_id: Mapped[str | None] = mapped_column(ForeignKey("print_runs.id"), index=True)
    run_position: Mapped[int | None]
    source_row: Mapped[int | None]
    template_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload: Mapped[dict[str, str]] = mapped_column(JSON)
    width_mm: Mapped[int]
    length_mm: Mapped[float]
    copies: Mapped[int]
    created_at: Mapped[float] = mapped_column(default=time.time)


class LabelCopy(Base):
    __tablename__ = "label_copies"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("print_jobs.id"), index=True)
    ordinal: Mapped[int]
    state: Mapped[State] = mapped_column(default=State.QUEUED, index=True)


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    cartridge_id: Mapped[str] = mapped_column(ForeignKey("cartridges.id"))
    state: Mapped[State] = mapped_column(default=State.PRINTING)
    created_at: Mapped[float] = mapped_column(default=time.time)
    finished_at: Mapped[float | None]
    error: Mapped[str | None]
    estimated_mm: Mapped[float]
    consumed_mm: Mapped[float | None]
    shortage_warning: Mapped[bool] = mapped_column(default=False)


class BatchItem(Base):
    __tablename__ = "batch_items"
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), primary_key=True)
    copy_id: Mapped[str] = mapped_column(ForeignKey("label_copies.id"), primary_key=True)
    position: Mapped[int]
    outcome: Mapped[State] = mapped_column(default=State.PRINTING)


class FlushRequest(Base):
    __tablename__ = "flush_requests"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    cartridge_id: Mapped[str] = mapped_column(ForeignKey("cartridges.id"))
    copy_ids: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(default=time.time)
    completed: Mapped[bool] = mapped_column(default=False)


class Notification(Base):
    __tablename__ = "notifications"
    recipient_id: Mapped[str] = mapped_column(
        String, default=LOCAL_OWNER_ID, server_default=LOCAL_OWNER_ID
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    title: Mapped[str]
    message: Mapped[str]
    path: Mapped[str]
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("tape_profiles.id"))
    episode: Mapped[int | None]
    created_at: Mapped[float] = mapped_column(default=time.time)
    next_attempt_at: Mapped[float] = mapped_column(default=time.time)
    attempts: Mapped[int] = mapped_column(default=0)
    delivered_at: Mapped[float | None]
    cancelled: Mapped[bool] = mapped_column(default=False)
    last_error: Mapped[str | None]


class PrintRun(Base):
    __tablename__ = "print_runs"
    destination_id: Mapped[str] = mapped_column(
        String, default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    owner_id: Mapped[str] = mapped_column(
        String, default=LOCAL_OWNER_ID, server_default=LOCAL_OWNER_ID
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    request_key: Mapped[str] = mapped_column(String, unique=True)
    request_hash: Mapped[str]
    name: Mapped[str]
    profile_id: Mapped[str] = mapped_column(ForeignKey("tape_profiles.id"))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(default=time.time)
    submitted_at: Mapped[float | None]
