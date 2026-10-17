"""Scoped messages and independent ntfy delivery; never affect print state."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import (
    Notification,
    NotificationDelivery,
    NotificationEndpoint,
    PrinterDevice,
    PrinterGroup,
)
from app.notification_types import PRINTER_NOTIFICATION_KINDS
from app.notifications import NtfySender, notification_valid, waiting_destinations
from app.request_models import PrintRequest


def notifications_enabled(session: Session) -> bool:
    return (
        session.scalar(
            select(NotificationEndpoint.id)
            .where(
                NotificationEndpoint.enabled.is_(True), NotificationEndpoint.deleted_at.is_(None)
            )
            .limit(1)
        )
        is not None
    )


def scope_matches(
    session: Session,
    endpoint: NotificationEndpoint,
    destination: str,
    *,
    include_members: bool = True,
) -> bool:
    """Explicit scopes only; group channels include alerts from physical members."""
    target_group = session.get(PrinterGroup, destination)
    target_printer = session.get(PrinterDevice, destination)
    if target_group is None and (target_printer is None or target_printer.config.get("retired")):
        return False
    if endpoint.all_printers:
        return True
    for identifier in endpoint.destination_ids:
        group = session.get(PrinterGroup, identifier)
        if identifier == destination or (
            include_members and group and destination in group.printer_ids
        ):
            return True
    return False


def endpoint_message(
    session: Session, notice: Notification, endpoint: NotificationEndpoint
) -> Notification | None:
    if not endpoint.enabled or endpoint.deleted_at is not None or notice.kind not in endpoint.kinds:
        return None
    if notice.kind in PRINTER_NOTIFICATION_KINDS and not (
        endpoint.all_printers or endpoint.destination_ids
    ):
        return None
    message, path = notice.message, notice.path
    if notice.kind == "approval_digest":
        # Unrestricted summaries are global; selected destinations narrow them.
        pending = list(
            session.scalars(select(PrintRequest).where(PrintRequest.status == "pending"))
        )
        if not endpoint.all_printers and endpoint.destination_ids:
            pending = [
                request
                for request in pending
                if scope_matches(session, endpoint, request.destination_id, include_members=False)
            ]
        if not pending:
            return None
        message = f"{len(pending)} print request(s) await review."
    elif notice.kind == "tape_waiting":
        from app.models import TapeProfile

        profile = session.get(TapeProfile, notice.profile_id) if notice.profile_id else None
        if profile is None:
            return None
        recorded = set(notice.context.get("destination_ids", []))
        waiting = [
            (identifier, name, count)
            for identifier, name, count in waiting_destinations(session, profile)
            if identifier in recorded and scope_matches(session, endpoint, identifier)
        ]
        if not waiting:
            return None
        message = f"{profile.name} is needed: " + "; ".join(
            f"{count} queued copies at {name}" for _, name, count in waiting
        )
    elif destination := notice.context.get("printer_id") or notice.context.get("destination_id"):
        if not scope_matches(session, endpoint, destination):
            return None
        if notice.kind in ("printer_blocked", "batch_review"):
            device = session.get(PrinterDevice, destination)
            message = f"{device.name if device else destination}: {message}"
    elif notice.kind in PRINTER_NOTIFICATION_KINDS:
        # Malformed historical printer events cannot become global messages.
        return None
    return Notification(
        id=notice.id,
        title=notice.title,
        message=message,
        path=path,
        kind=notice.kind,
        context=notice.context,
    )


def refresh_summary(session: Session, notice: Notification) -> None:
    deliveries = list(
        session.scalars(
            select(NotificationDelivery).where(NotificationDelivery.notification_id == notice.id)
        )
    )
    if not deliveries:
        return
    pending = [
        delivery
        for delivery in deliveries
        if delivery.delivered_at is None and not delivery.cancelled
    ]
    notice.attempts = sum(delivery.attempts for delivery in deliveries)
    notice.last_error = (
        "Delivery failed; will retry" if any(delivery.last_error for delivery in pending) else None
    )
    if pending:
        notice.next_attempt_at = min(delivery.next_attempt_at for delivery in pending)
    else:
        delivered = [
            delivery.delivered_at for delivery in deliveries if delivery.delivered_at is not None
        ]
        if delivered:
            notice.delivered_at = max(delivered)
        else:
            notice.cancelled = True


def deliver_routed_pending(
    factory: sessionmaker[Session],
    settings: Settings,
    now: float,
    send: Callable[[NotificationEndpoint, Notification], None] | None = None,
) -> None:
    # Freeze the endpoint set once, then retry each delivery separately. Adding
    # another endpoint never replays an event that already finished routing.
    with factory.begin() as session:
        endpoints = list(
            session.scalars(
                select(NotificationEndpoint).where(
                    NotificationEndpoint.enabled.is_(True),
                    NotificationEndpoint.deleted_at.is_(None),
                )
            )
        )
        for queued_notice in session.scalars(
            select(Notification)
            .where(
                Notification.delivered_at.is_(None),
                Notification.cancelled.is_(False),
                Notification.routed_at.is_(None),
                Notification.next_attempt_at <= now,
            )
            .order_by(Notification.next_attempt_at, Notification.created_at, Notification.id)
            .limit(100)
        ):
            if not notification_valid(session, queued_notice, now):
                queued_notice.cancelled = True
                for invalid_delivery in session.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == queued_notice.id,
                        NotificationDelivery.delivered_at.is_(None),
                    )
                ):
                    invalid_delivery.cancelled = True
                continue
            if queued_notice.routed_at is None:
                matching = [
                    endpoint
                    for endpoint in endpoints
                    if endpoint_message(session, queued_notice, endpoint) is not None
                ]
                if matching:
                    queued_notice.routed_at = now
                    for matched_endpoint in matching:
                        session.add(
                            NotificationDelivery(
                                notification_id=queued_notice.id,
                                endpoint_id=matched_endpoint.id,
                                endpoint_revision=matched_endpoint.revision,
                                endpoint_name=matched_endpoint.name,
                                next_attempt_at=now,
                            )
                        )
                else:
                    # Give newer alerts a turn even when old events have no channel.
                    queued_notice.next_attempt_at = now + 60
            session.flush()
            refresh_summary(session, queued_notice)
    with factory() as session:
        ids = list(
            session.scalars(
                select(NotificationDelivery.id)
                .where(
                    NotificationDelivery.delivered_at.is_(None),
                    NotificationDelivery.cancelled.is_(False),
                    NotificationDelivery.next_attempt_at <= now,
                )
                .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
                .limit(20)
            )
        )
    for identifier in ids:
        with factory.begin() as session:
            delivery = session.get(NotificationDelivery, identifier)
            if (
                delivery is None
                or delivery.cancelled
                or delivery.delivered_at is not None
                or delivery.next_attempt_at > now
            ):
                continue
            notice = session.get(Notification, delivery.notification_id)
            endpoint = session.get(NotificationEndpoint, delivery.endpoint_id)
            message = (
                endpoint_message(session, notice, endpoint)
                if notice is not None and endpoint is not None
                else None
            )
            if (
                notice is None
                or notice.cancelled
                or not notification_valid(session, notice, now)
                or endpoint is None
                or endpoint.revision != delivery.endpoint_revision
                or message is None
            ):
                delivery.cancelled = True
                if notice is not None:
                    refresh_summary(session, notice)
                continue
            session.expunge(endpoint)
        failed = False
        try:
            if send is None:
                NtfySender(settings, endpoint).send(message)
            else:
                send(endpoint, message)
        except Exception:
            failed = True
        with factory.begin() as session:
            stored = session.get(NotificationDelivery, identifier)
            if stored is None:
                continue
            stored.attempts += 1
            if failed:
                stored.last_error = "Delivery failed; will retry"
                stored.next_attempt_at = now + min(3600, 30 * 2 ** min(stored.attempts - 1, 7))
            else:
                stored.delivered_at = now
                stored.last_error = None
            notice = session.get(Notification, stored.notification_id)
            if notice is not None:
                refresh_summary(session, notice)
