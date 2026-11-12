"""Independent group accounts and append-only obligations/payment allocations."""

import time
from typing import Any

from sqlalchemy import JSON, Connection, ForeignKey, String, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.models import Base, new_id


class BillingAccount(Base):
    __tablename__ = "billing_accounts"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    archived: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[float] = mapped_column(default=time.time)


class BillingGrant(Base):
    __tablename__ = "billing_grants"
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_accounts.id"), primary_key=True)
    principal_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)
    effect: Mapped[str] = mapped_column(String(8))


class BillingRequest(Base):
    __tablename__ = "billing_requests"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_accounts.id"), index=True)
    requester_id: Mapped[str] = mapped_column(String(128), index=True)
    requester_name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(default=time.time)
    decided_at: Mapped[float | None]
    decided_by: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(String(500))


class BillingCharge(Base):
    __tablename__ = "billing_charges"
    __table_args__ = (UniqueConstraint("request_id", "batch_id", "kind"),)
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_accounts.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("billing_requests.id"))
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"))
    requester_id: Mapped[str] = mapped_column(String(128))
    requester_name: Mapped[str] = mapped_column(String(100))
    recipient_id: Mapped[str | None] = mapped_column(String(128), index=True)
    recipient_name: Mapped[str | None] = mapped_column(String(100))
    cartridge_id: Mapped[str] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(3))
    # transfer offsets personal debt; reimbursement pays the member; supply is self-owned tape.
    kind: Mapped[str] = mapped_column(String(16))
    amount_micros: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[float] = mapped_column(default=time.time)


class BillingPayment(Base):
    __tablename__ = "billing_payments"
    request_id: Mapped[str] = mapped_column(ForeignKey("billing_requests.id"), primary_key=True)
    charge_id: Mapped[str] = mapped_column(ForeignKey("billing_charges.id"), primary_key=True)
    amount_micros: Mapped[str] = mapped_column(String(128))
    confirmed_by: Mapped[str] = mapped_column(String(128))
    confirmed_at: Mapped[float] = mapped_column(default=time.time)


class BillingEvent(Base):
    __tablename__ = "billing_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("billing_accounts.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    actor_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(default=time.time)


@event.listens_for(BillingEvent, "before_update")
@event.listens_for(BillingEvent, "before_delete")
@event.listens_for(BillingPayment, "before_update")
@event.listens_for(BillingPayment, "before_delete")
@event.listens_for(BillingCharge, "before_delete")
def immutable_entry(mapper: Mapper[Any], connection: Connection, target: Base) -> None:
    raise ValueError("Group financial evidence cannot be edited or deleted")


@event.listens_for(BillingCharge, "before_update")
def assign_creditor_only(
    mapper: Mapper[Any], connection: Connection, target: BillingCharge
) -> None:
    changes = {
        attribute.key for attribute in inspect(target).attrs if attribute.history.has_changes()
    }
    if changes - {"recipient_id", "recipient_name"}:
        raise ValueError("Group charges are immutable; only unowned creditor assignment is allowed")
    history = inspect(target).attrs.recipient_id.history
    if history.deleted and history.deleted[0] is not None:
        raise ValueError("An assigned group creditor cannot be replaced")
