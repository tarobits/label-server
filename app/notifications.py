"""Durable outbox and profile reminder episodes, independent of print outcomes."""

import time
from typing import Protocol

import httpx
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.destinations import installed_profile
from app.identity import LOCAL_OWNER_ID
from app.job_access_models import JobAccessHold
from app.models import (
    LabelCopy,
    Notification,
    PrinterDevice,
    PrinterGroup,
    PrintJob,
    State,
    TapeProfile,
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
) -> None:
    stamp = time.time() if now is None else now
    session.add(
        Notification(
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
        pending = session.scalar(
            select(Notification.id)
            .where(
                Notification.profile_id == profile.id,
                Notification.episode == profile.reminder_episode,
                Notification.delivered_at.is_(None),
                Notification.cancelled.is_(False),
            )
            .limit(1)
        )
        if pending:
            continue
        enqueue(
            session,
            "Tape swap needed",
            f"{profile.name} is needed: "
            + "; ".join(
                f"{count} queued copies at {name}"
                for _, name, count in waiting_destinations(session, profile)
            ),
            "/#/printers",
            profile,
            now,
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
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, notification: Notification) -> None:
        headers = {}
        if self.settings.ntfy_token.get_secret_value():
            headers["Authorization"] = f"Bearer {self.settings.ntfy_token.get_secret_value()}"
        # JSON publishing safely supports Unicode titles and profile names.
        response = httpx.post(
            self.settings.ntfy_url.rstrip("/"),
            headers=headers,
            json={
                "topic": self.settings.ntfy_topic,
                "title": notification.title,
                "message": notification.message,
                "click": self.settings.public_url.rstrip("/") + notification.path,
            },
            timeout=10,
        )
        response.raise_for_status()


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
            assert notification is not None
            if notification.recipient_id == "administrators":
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
