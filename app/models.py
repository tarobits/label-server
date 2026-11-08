"""Persistent domain records. Lengths are in millimetres; times are UTC epoch seconds."""

import enum
import time
import uuid
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Double, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.identity import DEFAULT_PRINTER_ID, LOCAL_OWNER_ID
from app.notification_types import DEFAULT_NOTIFICATION_PRIORITIES


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    type_annotation_map = {
        str: String().with_variant(LONGTEXT(), "mysql", "mariadb"),
        float: Double(),
    }


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (CheckConstraint("parent_id != id", name="ck_location_not_own_parent"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str]
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"), index=True)
    owner_id: Mapped[str | None] = mapped_column(String(128), index=True)


class ReleaseMigration(Base):
    __tablename__ = "release_migrations"
    version: Mapped[str] = mapped_column(String(128), primary_key=True)
    draft: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed_at: Mapped[float | None]
    completed_by: Mapped[str | None]


class ResourceOwnership(Base):
    """Retained owner identity for reviewed attempts and later ownership transfers."""

    __tablename__ = "resource_ownership"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    kind: Mapped[str]
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_id: Mapped[str]
    owner_name: Mapped[str]
    effective_at: Mapped[float]
    ended_at: Mapped[float | None]


class ResourceGrant(Base):
    """Explicit allow/deny rules; polymorphic references are validated before writing."""

    __tablename__ = "resource_grants"
    __table_args__ = (
        CheckConstraint("effect IN ('allow', 'deny')", name="ck_grant_effect"),
        CheckConstraint("principal_kind IN ('user', 'role')", name="ck_grant_principal_kind"),
        CheckConstraint(
            "scope_kind IN ('printer', 'printer_group', 'cartridge', 'location', 'companion')",
            name="ck_grant_scope_kind",
        ),
    )
    principal_kind: Mapped[str] = mapped_column(String(128), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope_kind: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    permission: Mapped[str] = mapped_column(String(128), primary_key=True)
    effect: Mapped[str] = mapped_column(String(8), default="allow", server_default="allow")


class AuditEvent(Base):
    """Structured evidence; clients receive only a permission-filtered projection."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('succeeded', 'denied', 'failed')", name="ck_audit_event_outcome"
        ),
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    action: Mapped[str] = mapped_column(String(128), index=True)
    outcome: Mapped[str]
    occurred_at: Mapped[float] = mapped_column(index=True)
    recorded_at: Mapped[float] = mapped_column(default=time.time)
    scopes: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    fields: Mapped[dict[str, Any]] = mapped_column(JSON)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    password_hash: Mapped[str]
    disabled: Mapped[bool] = mapped_column(default=False)
    role_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[float] = mapped_column(default=time.time)
    last_seen_version: Mapped[str | None]
    email: Mapped[str | None]


class RecoveryToken(Base):
    __tablename__ = "recovery_tokens"
    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str]
    email: Mapped[str]
    password_fingerprint: Mapped[str]
    expires_at: Mapped[float] = mapped_column(index=True)


class DeletedContent(Base):
    __tablename__ = "deleted_content"
    kind: Mapped[str] = mapped_column(String(128), primary_key=True)
    identifier: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str]
    owner_id: Mapped[str]
    deleted_by: Mapped[str]
    deleted_at: Mapped[float]
    purge_after: Mapped[float] = mapped_column(index=True)
    purged_at: Mapped[float | None]
    account_id: Mapped[str | None] = mapped_column(String(128), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    permissions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    protected: Mapped[bool] = mapped_column(default=False, server_default="0")


class UserGroup(Base):
    __tablename__ = "user_groups"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    members: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")


class AccessChangeConfirmation(Base):
    __tablename__ = "access_change_confirmations"
    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_hash: Mapped[str]
    state_hash: Mapped[str]
    expires_at: Mapped[float]


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), unique=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str]
    created_at: Mapped[float] = mapped_column(default=time.time)
    expires_at: Mapped[float]
    last_seen_at: Mapped[float | None]
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]
    location: Mapped[str | None]


class RegistrationCode(Base):
    __tablename__ = "registration_codes"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
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
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str]
    width_mm: Mapped[float]
    media_family: Mapped[str] = mapped_column(String(32), default="tze", server_default="tze")
    label_length_mm: Mapped[float | None]
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
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    archived: Mapped[bool] = mapped_column(default=False, server_default="0")
    profile_id: Mapped[str] = mapped_column(ForeignKey("tape_profiles.id"))
    name: Mapped[str]
    nominal_length_mm: Mapped[float]
    remaining_mm: Mapped[float]
    consumption_uncertain: Mapped[bool] = mapped_column(default=False)
    price_minor: Mapped[int | None]
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    owner_id: Mapped[str | None] = mapped_column(String(128), index=True)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"), index=True)
    notes: Mapped[str] = mapped_column(default="", server_default="")


class PrinterDevice(Base):
    __tablename__ = "printers"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str]
    driver: Mapped[str]
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    owner_id: Mapped[str | None] = mapped_column(String(128), index=True)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"), index=True)


class PrinterGroup(Base):
    __tablename__ = "printer_groups"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str]
    printer_ids: Mapped[list[str]] = mapped_column(JSON)
    automatic_printing_held: Mapped[bool] = mapped_column(default=False, server_default="0")


class Companion(Base):
    __tablename__ = "companions"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str]
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id"))
    bound_user_id: Mapped[str | None] = mapped_column(String(128))
    key_hash: Mapped[str | None] = mapped_column(String(128), unique=True)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[float] = mapped_column(default=time.time)
    last_seen_at: Mapped[float | None]


class CompanionPin(Base):
    __tablename__ = "companion_pins"
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    pin_hash: Mapped[str]


class CompanionSession(Base):
    __tablename__ = "companion_sessions"
    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    companion_id: Mapped[str] = mapped_column(ForeignKey("companions.id"), index=True)
    user_id: Mapped[str]
    revision: Mapped[int]
    pin_fingerprint: Mapped[str | None]
    expires_at: Mapped[float]


class CompanionPrinter(Base):
    __tablename__ = "companion_printers"
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    companion_id: Mapped[str] = mapped_column(ForeignKey("companions.id"), index=True)
    local_id: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)
    status: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[float | None]
    blocked: Mapped[bool] = mapped_column(default=False)
    clearance: Mapped[int] = mapped_column(default=0)


class CompanionBatch(Base):
    __tablename__ = "companion_batches"
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), primary_key=True)
    companion_id: Mapped[str] = mapped_column(ForeignKey("companions.id"), index=True)
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    digest: Mapped[str]
    go_token: Mapped[str | None]
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    stop_mode: Mapped[str | None]
    created_at: Mapped[float] = mapped_column(default=time.time)


class PrinterState(Base):
    __tablename__ = "printer_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[str] = mapped_column(
        String(128), unique=True, default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    active_cartridge_id: Mapped[str | None] = mapped_column(ForeignKey("cartridges.id"))
    media_confirmation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    media_verified_fingerprint: Mapped[str | None] = mapped_column(String(128))
    cartridge_check_enabled: Mapped[bool] = mapped_column(default=True, server_default="1")
    cartridge_check_pending: Mapped[bool] = mapped_column(default=False, server_default="0")
    empty_alert_cartridge_id: Mapped[str | None] = mapped_column(String(128))
    blocker: Mapped[str | None]
    automatic_printing_held: Mapped[bool] = mapped_column(default=False, server_default="0")


class LabelTemplate(Base):
    __tablename__ = "label_templates"
    group_id: Mapped[str | None] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(String(128), default="personal", server_default="personal")
    owner_id: Mapped[str] = mapped_column(
        String(128), default=LOCAL_OWNER_ID, server_default=LOCAL_OWNER_ID
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
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
        String(128), default="print", server_default="print"
    )
    destination_id: Mapped[str] = mapped_column(
        String(128), default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    owner_id: Mapped[str] = mapped_column(
        String(128), default=LOCAL_OWNER_ID, server_default=LOCAL_OWNER_ID
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("tape_profiles.id"), index=True)
    template_id: Mapped[str]
    run_id: Mapped[str | None] = mapped_column(ForeignKey("print_runs.id"), index=True)
    run_position: Mapped[int | None]
    source_row: Mapped[int | None]
    template_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    width_mm: Mapped[float]
    length_mm: Mapped[float]
    copies: Mapped[int]
    notify_on_completion: Mapped[bool] = mapped_column(default=True, server_default="1")
    completion_notified_at: Mapped[float | None]
    created_at: Mapped[float] = mapped_column(default=time.time)


class LabelCopy(Base):
    __tablename__ = "label_copies"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("print_jobs.id"), index=True)
    ordinal: Mapped[int]
    state: Mapped[State] = mapped_column(default=State.QUEUED, index=True)


class Batch(Base):
    __tablename__ = "batches"
    trigger: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    print_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    consumption_source: Mapped[str | None] = mapped_column(String(128))
    printer_id: Mapped[str] = mapped_column(
        String(128), default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    cartridge_id: Mapped[str] = mapped_column(ForeignKey("cartridges.id"))
    state: Mapped[State] = mapped_column(default=State.PRINTING)
    created_at: Mapped[float] = mapped_column(default=time.time)
    finished_at: Mapped[float | None]
    completion_notified_at: Mapped[float | None]
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
    use_authorizations: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    printer_id: Mapped[str] = mapped_column(
        String(128), default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    destination_id: Mapped[str] = mapped_column(
        String(128), default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    cartridge_id: Mapped[str] = mapped_column(ForeignKey("cartridges.id"))
    copy_ids: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(default=time.time)
    completed: Mapped[bool] = mapped_column(default=False)


class PriceQuote(Base):
    __tablename__ = "price_quotes"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    user_id: Mapped[str]
    geometry_key: Mapped[str]
    quotes: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    expires_at: Mapped[float]


class CartridgeQuoteOffer(Base):
    __tablename__ = "cartridge_quote_offers"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("print_jobs.id"), index=True)
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"))
    cartridge_id: Mapped[str]
    requester_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    acceptance: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(default=time.time)


class UnitCharge(Base):
    __tablename__ = "unit_charges"
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("print_jobs.id"), primary_key=True)
    planned_mm: Mapped[float]
    currency: Mapped[str]
    reserved_micros: Mapped[str | None]
    cap_micros: Mapped[str | None]
    actual_micros: Mapped[str | None]
    charged_micros: Mapped[str | None]
    authorization: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class Notification(Base):
    __tablename__ = "notifications"
    kind: Mapped[str] = mapped_column(String(128), default="general", server_default="general")
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    recipient_id: Mapped[str] = mapped_column(
        String(128), default=LOCAL_OWNER_ID, server_default=LOCAL_OWNER_ID
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
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


class NotificationRead(Base):
    __tablename__ = "notification_reads"
    notification_id: Mapped[str] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    read_at: Mapped[float] = mapped_column(default=time.time)


class NotificationEndpoint(Base):
    __tablename__ = "notification_endpoints"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str]
    transport: Mapped[str] = mapped_column(default="ntfy", server_default="ntfy")
    email: Mapped[str] = mapped_column(default="", server_default="")
    owner_id: Mapped[str | None] = mapped_column(String(128), index=True)
    push_subscription: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    push_session_hash: Mapped[str | None] = mapped_column(String(128))
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
    printer_kinds: Mapped[dict[str, list[str]]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    printer_priorities: Mapped[dict[str, dict[str, int]]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[float] = mapped_column(default=time.time)
    deleted_at: Mapped[float | None]


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (UniqueConstraint("notification_id", "endpoint_id"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
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
    assigned_printer_id: Mapped[str | None] = mapped_column(String(128))
    destination_id: Mapped[str] = mapped_column(
        String(128), default=DEFAULT_PRINTER_ID, server_default=DEFAULT_PRINTER_ID
    )
    owner_id: Mapped[str] = mapped_column(
        String(128), default=LOCAL_OWNER_ID, server_default=LOCAL_OWNER_ID
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    request_key: Mapped[str] = mapped_column(String(128), unique=True)
    request_hash: Mapped[str]
    name: Mapped[str]
    profile_id: Mapped[str] = mapped_column(ForeignKey("tape_profiles.id"))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(default=time.time)
    submitted_at: Mapped[float | None]


class JobSubmission(Base):
    """Retry receipt: a caller key belongs to one actor and one frozen job."""

    __tablename__ = "job_submissions"
    owner_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str]
    job_id: Mapped[str] = mapped_column(ForeignKey("print_jobs.id"))


class RetryOffer(Base):
    """Explicit retry funding, preserving the original attempt and requester."""

    __tablename__ = "retry_offers"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    request_key: Mapped[str] = mapped_column(String(128), index=True)
    request_hash: Mapped[str]
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    source_job_id: Mapped[str] = mapped_column(ForeignKey("print_jobs.id"))
    copy_ids: Mapped[list[str]] = mapped_column(JSON)
    requester_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str]
    actor_name: Mapped[str]
    mode: Mapped[str]
    cartridge_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(128), default="pending")
    job_id: Mapped[str | None] = mapped_column(ForeignKey("print_jobs.id"))
    created_at: Mapped[float] = mapped_column(default=time.time)
    accepted_at: Mapped[float | None]


class TapeAllocation(Base):
    """Immutable requester/price snapshot; settled with cartridge consumption."""

    __tablename__ = "tape_allocations"
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), primary_key=True)
    # Retain attribution when an account is purged, like the existing print audit.
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)
    username: Mapped[str]
    planned_mm: Mapped[float]
    consumed_mm: Mapped[float | None]
    nominal_length_mm: Mapped[float]
    price_minor: Mapped[int | None]
    currency: Mapped[str] = mapped_column(String(3))
    # Integer millionths of currency stored as text to avoid overflow and float rounding.
    cost_micros: Mapped[str | None] = mapped_column(String(128))
    cartridge_id: Mapped[str | None] = mapped_column(String(128))
    recipient_id: Mapped[str | None] = mapped_column(String(128), index=True)
    recipient_name: Mapped[str | None]
    charged_micros: Mapped[str | None] = mapped_column(String(128))
    recipient_assigned_at: Mapped[float | None]


class UsageAdjustment(Base):
    """Append-only payments/corrections; identities survive account deletion."""

    __tablename__ = "usage_adjustments"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    username: Mapped[str]
    actor_id: Mapped[str]
    actor_name: Mapped[str]
    amount_minor: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str]
    created_at: Mapped[float] = mapped_column(default=time.time)
    recipient_id: Mapped[str | None] = mapped_column(String(128), index=True)
    recipient_name: Mapped[str | None]
    cartridge_allocations: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    requested_allocations: Mapped[dict[str, str] | None] = mapped_column(JSON)
