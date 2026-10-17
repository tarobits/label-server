"""Durable outbox and profile reminder episodes, independent of print outcomes."""

import time
from typing import Any, Protocol

import httpx
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.destinations import installed_profile
from app.identity import LOCAL_OWNER_ID
from app.job_access_models import JobAccessHold
from app.models import (
    Batch,
    Cartridge,
    LabelCopy,
    Notification,
    NotificationEndpoint,
    PrinterDevice,
    PrinterGroup,
    PrinterState,
    PrintJob,
    State,
    TapeProfile,
)
from app.notification_types import (
    DEFAULT_NOTIFICATION_PRIORITIES,
)


def enqueue(
    session: Session,
    title: str,
    message: str,
    path: str,
    profile: TapeProfile | None = None,
    now: float | None = None,
    *,
    recipient_id: str = LOCAL_OWNER_ID,
    kind: str = "general",
    context: dict[str, Any] | None = None,
) -> None:
    stamp = time.time() if now is None else now
    session.add(
        Notification(
            kind=kind,
            context=context or {},
            recipient_id=recipient_id,
            title=title,
            message=message,
            path=path,
            created_at=stamp,
            next_attempt_at=stamp,
            profile_id=profile.id if profile else None,
            episode=profile.reminder_episode if profile else None,
        )
    )


def clear_empty_cartridge_alert(session: Session, state: PrinterState) -> None:
    """End the depletion episode and discard unsent alerts before a later episode."""
    if state.empty_alert_cartridge_id is None:
        return
    for notice in session.scalars(
        select(Notification).where(
            Notification.kind == "empty_tape",
            Notification.context["printer_id"].as_string() == state.printer_id,
            Notification.delivered_at.is_(None),
            Notification.cancelled.is_(False),
        )
    ):
        notice.cancelled = True
    state.empty_alert_cartridge_id = None


def sync_empty_cartridge_alert(
    session: Session, state: PrinterState, cartridge: Cartridge, now: float
) -> None:
    """One durable administrator alert per installed cartridge depletion episode."""
    if cartridge.remaining_mm > 0:
        clear_empty_cartridge_alert(session, state)
        return
    if state.empty_alert_cartridge_id == cartridge.id:
        return
    device = session.get(PrinterDevice, state.printer_id)
    if device is None or device.config.get("retired"):
        return
    state.empty_alert_cartridge_id = cartridge.id
    enqueue(
        session,
        "Installed cartridge is empty",
        f"{device.name}: {cartridge.name} has an estimated 0 mm of tape remaining. "
        "Automatic printing will wait for replacement tape or a remaining-length correction.",
        f"/#/printers?printer={device.id}",
        now=now,
        recipient_id="administrators",
        kind="empty_tape",
        context={"printer_id": device.id, "cartridge_id": cartridge.id},
    )


def empty_tape_alert_valid(session: Session, notification: Notification) -> bool:
    state = session.scalar(
        select(PrinterState).where(
            PrinterState.printer_id == notification.context.get("printer_id")
        )
    )
    cartridge = session.get(Cartridge, notification.context.get("cartridge_id", ""))
    device = session.get(PrinterDevice, notification.context.get("printer_id", ""))
    return bool(
        state
        and cartridge
        and device
        and not device.config.get("retired")
        and state.active_cartridge_id == cartridge.id
        and cartridge.remaining_mm <= 0
    )


def queued_count(session: Session, profile: TapeProfile, destination_id: str | None = None) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(LabelCopy)
            .join(PrintJob)
            .where(
                PrintJob.profile_id == profile.id,
                true() if destination_id is None else PrintJob.destination_id == destination_id,
                PrintJob.width_mm == profile.width_mm,
                LabelCopy.state == State.QUEUED,
                ~select(JobAccessHold.job_id)
                .where(JobAccessHold.job_id == PrintJob.id, JobAccessHold.status != "released")
                .exists(),
            )
        )
        or 0
    )


def threshold_destinations(session: Session, profile: TapeProfile) -> list[tuple[str, str, int]]:
    result = []
    destinations = session.scalars(
        select(PrintJob.destination_id).where(PrintJob.profile_id == profile.id).distinct()
    )
    for identifier in destinations:
        count = queued_count(session, profile, identifier)
        if count < profile.auto_print_threshold:
            continue
        destination = session.get(PrinterGroup, identifier) or session.get(
            PrinterDevice, identifier
        )
        if (
            destination is None
            or isinstance(destination, PrinterDevice)
            and destination.config.get("retired")
        ):
            continue
        result.append((identifier, destination.name, count))
    return result


def waiting_destinations(session: Session, profile: TapeProfile) -> list[tuple[str, str, int]]:
    result = []
    for identifier, name, count in threshold_destinations(session, profile):
        group = session.get(PrinterGroup, identifier)
        identifiers = group.printer_ids if group else [identifier]
        operational = [
            pid
            for pid in identifiers
            if (device := session.get(PrinterDevice, pid)) and not device.config.get("retired")
        ]
        if operational and not any(
            installed_profile(session, pid) == profile.id for pid in operational
        ):
            result.append((identifier, name, count))
    return result


def waiting_condition(session: Session, profile: TapeProfile) -> bool:
    return bool(waiting_destinations(session, profile))


def reminder_valid(session: Session, notification: Notification, now: float) -> bool:
    if not notification.profile_id:
        return True
    profile = session.get(TapeProfile, notification.profile_id)
    return bool(
        profile
        and profile.waiting_notification_enabled
        and profile.reminder_episode == notification.episode
        and not profile.reminder_silenced
        and (profile.reminder_snoozed_until is None or profile.reminder_snoozed_until <= now)
        and waiting_condition(session, profile)
    )


def schedule_reminders(session: Session, now: float) -> None:
    for profile in session.scalars(select(TapeProfile)):
        if not threshold_destinations(session, profile):
            if profile.reminder_active:
                profile.reminder_episode += 1
            profile.reminder_active = False
            profile.reminder_silenced = False
            profile.reminder_snoozed_until = None
            profile.reminder_last_at = None
            continue
        profile.reminder_active = True
        if not profile.waiting_notification_enabled or not waiting_condition(session, profile):
            continue
        if profile.reminder_silenced or (profile.reminder_snoozed_until or 0) > now:
            continue
        if (
            profile.reminder_last_at is not None
            and now - profile.reminder_last_at < profile.waiting_notification_interval_seconds
        ):
            continue
        pending = list(
            session.scalars(
                select(Notification).where(
                    Notification.profile_id == profile.id,
                    Notification.episode == profile.reminder_episode,
                    Notification.delivered_at.is_(None),
                    Notification.cancelled.is_(False),
                )
            )
        )
        waiting = waiting_destinations(session, profile)
        covered = {
            identifier
            for notice in pending
            for identifier in notice.context.get("destination_ids", [])
        }
        waiting = [item for item in waiting if item[0] not in covered]
        if not waiting:
            continue
        enqueue(
            session,
            "Tape swap needed",
            f"{profile.name} is needed: "
            + "; ".join(f"{count} queued copies at {name}" for _, name, count in waiting),
            "/#/printers",
            profile,
            now,
            kind="tape_waiting",
            context={"destination_ids": [identifier for identifier, _, _ in waiting]},
        )
        profile.reminder_last_at = now


class NotificationSender(Protocol):
    def send(self, notification: Notification) -> None: ...


class RoutedNotificationSender:
    """Resolve stable recipients before delivery; transports do not know users/roles."""

    def __init__(self, recipients: dict[str, NotificationSender]) -> None:
        self.recipients = recipients

    def send(self, notification: Notification) -> None:
        sender = self.recipients.get(notification.recipient_id)
        if sender is None:
            raise ValueError("No notification destination configured for this recipient")
        sender.send(notification)


class NtfySender:
    def __init__(self, settings: Settings, endpoint: NotificationEndpoint) -> None:
        self.settings = settings
        self.endpoint = endpoint

    def send(self, notification: Notification) -> None:
        headers = {}
        if self.endpoint.token:
            headers["Authorization"] = f"Bearer {self.endpoint.token}"
        response = httpx.post(
            self.endpoint.url.rstrip("/"),
            headers=headers,
            json={
                "topic": self.endpoint.topic,
                "title": notification.title,
                "message": notification.message,
                "priority": (self.endpoint.priorities or {}).get(
                    notification.kind, DEFAULT_NOTIFICATION_PRIORITIES.get(notification.kind, 3)
                ),
                "click": self.settings.public_url.rstrip("/") + notification.path,
            },
            timeout=10,
        )
        response.raise_for_status()


def notification_valid(session: Session, notification: Notification, now: float) -> bool:
    if notification.kind == "tape_waiting":
        profile = session.get(TapeProfile, notification.profile_id or "")
        recorded = set(notification.context.get("destination_ids", []))
        if profile is None or not any(
            identifier in recorded for identifier, _, _ in waiting_destinations(session, profile)
        ):
            return False
    if notification.kind == "empty_tape":
        return empty_tape_alert_valid(session, notification)
    if notification.kind == "batch_review":
        batch = session.get(Batch, notification.context.get("batch_id", ""))
        return batch is not None and batch.state == State.NEEDS_REVIEW
    if notification.kind == "printer_blocked":
        state = session.scalar(
            select(PrinterState).where(
                PrinterState.printer_id == notification.context.get("printer_id")
            )
        )
        return state is not None and state.blocker == notification.context.get("reason")
    if notification.kind == "approval_digest":
        from app.auth import active_administrators
        from app.models import AuthSettings
        from app.request_models import PrintRequest

        settings = session.get(AuthSettings, 1)
        count = (
            session.scalar(
                select(func.count())
                .select_from(PrintRequest)
                .where(PrintRequest.status == "pending")
            )
            or 0
        )
        if (
            not settings
            or not settings.approval_notifications_enabled
            or not active_administrators(session)
            or not count
        ):
            return False
        notification.message = f"{count} print request(s) await administrator review."
    return reminder_valid(session, notification, now)


def deliver_pending(factory: sessionmaker[Session], sender: NotificationSender, now: float) -> None:
    with factory() as session:
        ids = list(
            session.scalars(
                select(Notification.id)
                .where(
                    Notification.delivered_at.is_(None),
                    Notification.cancelled.is_(False),
                    Notification.next_attempt_at <= now,
                )
                .order_by(Notification.created_at)
                .limit(20)
            )
        )
    for identifier in ids:
        with factory.begin() as session:
            notification = session.get(Notification, identifier)
            if (
                notification is None
                or notification.cancelled
                or notification.delivered_at is not None
                or notification.next_attempt_at > now
            ):
                continue
            if notification.kind == "empty_tape" and not empty_tape_alert_valid(
                session, notification
            ):
                notification.cancelled = True
                continue
            if notification.kind == "approval_digest":
                from app.auth import active_administrators
                from app.models import AuthSettings

                settings = session.get(AuthSettings, 1)
                active_admin = active_administrators(session)
                from app.request_models import PrintRequest

                pending_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(PrintRequest)
                        .where(PrintRequest.status == "pending")
                    )
                    or 0
                )
                if (
                    not settings
                    or not settings.approval_notifications_enabled
                    or not active_admin
                    or not pending_count
                ):
                    notification.cancelled = True
                    continue
                notification.message = (
                    f"{pending_count} print request(s) await administrator review."
                )
                session.flush()
            elif notification.recipient_id == "administrators":
                from app.auth import active_administrators

                if not active_administrators(session):
                    # Retain operational alerts until an administrator can receive them.
                    continue
            if not reminder_valid(session, notification, now):
                # Snoozed reminders can be recreated when the snooze expires.
                notification.cancelled = True
                continue
            session.expunge(notification)
        try:
            sender.send(notification)
        except Exception:
            # Do not persist exception strings which may contain credentials or URLs.
            with factory.begin() as session:
                stored = session.get(Notification, identifier)
                assert stored is not None
                stored.attempts += 1
                stored.last_error = "Delivery failed; will retry"
                stored.next_attempt_at = now + min(3600, 30 * 2 ** min(stored.attempts - 1, 7))
        else:
            with factory.begin() as session:
                stored = session.get(Notification, identifier)
                assert stored is not None
                stored.attempts += 1
                stored.delivered_at = now
                stored.last_error = None
                if stored.profile_id:
                    profile = session.get(TapeProfile, stored.profile_id)
                    if profile:
                        profile.reminder_last_at = now
