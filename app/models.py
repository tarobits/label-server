"""Persistent domain records. Lengths are in millimetres; times are UTC epoch seconds."""

import enum
import time
import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.identity import DEFAULT_PRINTER_ID, LOCAL_OWNER_ID
from app.notification_types import DEFAULT_NOTIFICATION_PRIORITIES


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str]
    disabled: Mapped[bool] = mapped_column(default=False)
    role_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[float] = mapped_column(default=time.time)
    last_seen_version: Mapped[str | None]


class DeletedContent(Base):
    __tablename__ = "deleted_content"
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    identifier: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    owner_id: Mapped[str]
    deleted_by: Mapped[str]
    deleted_at: Mapped[float]
    purge_after: Mapped[float] = mapped_column(index=True)
    purged_at: Mapped[float | None]
    account_id: Mapped[str | None] = mapped_column(index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String, unique=True)
    permissions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    protected: Mapped[bool] = mapped_column(default=False, server_default="0")


class UserGroup(Base):
    __tablename__ = "user_groups"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String, unique=True)
    members: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")


class AccessChangeConfirmation(Base):
    __tablename__ = "access_change_confirmations"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_hash: Mapped[str]
    state_hash: Mapped[str]
    expires_at: Mapped[float]


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str]
    created_at: Mapped[float] = mapped_column(default=time.time)
    expires_at: Mapped[float]


class RegistrationCode(Base):
    __tablename__ = "registration_codes"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str]
    role_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    group_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    group_permissions: Mapped[dict[str, dict[str, bool]]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    created_at: Mapped[float] = mapped_column(default=time.time)
    expires_at: Mapped[float]
    redeemed_at: Mapped[float | None]
    redeemed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    revoked: Mapped[bool] = mapped_column(default=False)


class AuthSettings(Base):
    __tablename__ = "auth_settings"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    registration_code_required: Mapped[bool] = mapped_column(default=True)
    approval_notification_debounce_seconds: Mapped[int] = mapped_column(default=60)
    approval_notifications_enabled: Mapped[bool] = mapped_column(default=True)


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
    width_mm: Mapped[float]
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


class PrinterDevice(Base):
    __tablename__ = "printers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str]
    driver: Mapped[str]
    config: Mapped[dict[str, Any]] = mapped_column(JSON)


class PrinterGroup(Base):
    __tablename__ = "printer_groups"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str]
    printer_ids: Mapped[list[str]] = mapped_column(JSON)
    automatic_printing_held: Mapped[bool] = mapped_column(default=False, server_default="0")


class PrinterState(Base):
    __tablename__ = "printer_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[str] = mapped_column(
        String, unique=True, default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    active_cartridge_id: Mapped[str | None] = mapped_column(ForeignKey("cartridges.id"))
    empty_alert_cartridge_id: Mapped[str | None] = mapped_column(String)
    blocker: Mapped[str | None]
    automatic_printing_held: Mapped[bool] = mapped_column(default=False, server_default="0")


class LabelTemplate(Base):
    __tablename__ = "label_templates"
    group_id: Mapped[str | None] = mapped_column(String)
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
    created_at: Mapped[float | None] = mapped_column(default=time.time)
    edited_by: Mapped[dict[str, str] | None] = mapped_column(JSON)
    restored_from_revision: Mapped[int | None]


class PrintJob(Base):
    __tablename__ = "print_jobs"
    attribution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    authorization_basis: Mapped[str] = mapped_column(
        String, default="print", server_default="print"
    )
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
    width_mm: Mapped[float]
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
    trigger: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    printer_id: Mapped[str] = mapped_column(
        String, default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
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
    attribution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), primary_key=True)
    copy_id: Mapped[str] = mapped_column(ForeignKey("label_copies.id"), primary_key=True)
    position: Mapped[int]
    outcome: Mapped[State] = mapped_column(default=State.PRINTING)


class FlushRequest(Base):
    __tablename__ = "flush_requests"
    started_by: Mapped[dict[str, str] | None] = mapped_column(JSON)
    printer_id: Mapped[str] = mapped_column(
        String, default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    destination_id: Mapped[str] = mapped_column(
        String, default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    cartridge_id: Mapped[str] = mapped_column(ForeignKey("cartridges.id"))
    copy_ids: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(default=time.time)
    completed: Mapped[bool] = mapped_column(default=False)


class Notification(Base):
    __tablename__ = "notifications"
    kind: Mapped[str] = mapped_column(String, default="general", server_default="general")
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
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
    routed_at: Mapped[float | None]


class NotificationEndpoint(Base):
    __tablename__ = "notification_endpoints"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str]
    url: Mapped[str]
    topic: Mapped[str]
    token: Mapped[str] = mapped_column(default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    destination_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    all_printers: Mapped[bool] = mapped_column(default=False, server_default="0")
    priorities: Mapped[dict[str, int]] = mapped_column(
        JSON, default=lambda: dict(DEFAULT_NOTIFICATION_PRIORITIES)
    )
    kinds: Mapped[list[str]] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[float] = mapped_column(default=time.time)
    deleted_at: Mapped[float | None]


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (UniqueConstraint("notification_id", "endpoint_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    notification_id: Mapped[str] = mapped_column(ForeignKey("notifications.id"), index=True)
    endpoint_id: Mapped[str] = mapped_column(ForeignKey("notification_endpoints.id"))
    endpoint_revision: Mapped[int]
    endpoint_name: Mapped[str]
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[float] = mapped_column(default=time.time)
    delivered_at: Mapped[float | None]
    cancelled: Mapped[bool] = mapped_column(default=False)
    last_error: Mapped[str | None]


class PrintRun(Base):
    __tablename__ = "print_runs"
    assigned_printer_id: Mapped[str | None] = mapped_column(String)
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


class JobSubmission(Base):
    """Retry receipt: a caller key belongs to one actor and one frozen job."""

    __tablename__ = "job_submissions"
    owner_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_key: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str]
    job_id: Mapped[str] = mapped_column(ForeignKey("print_jobs.id"))
