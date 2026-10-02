"""Durable outbox and profile reminder episodes, independent of print outcomes."""

import time
from typing import Protocol

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.identity import DEFAULT_PRINTER_ID, LOCAL_OWNER_ID
from app.models import (
    Cartridge,
    LabelCopy,
    Notification,
    PrinterState,
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


def queued_count(session: Session, profile: TapeProfile) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(LabelCopy)
            .join(PrintJob)
            .where(
                PrintJob.profile_id == profile.id,
                PrintJob.destination_id == DEFAULT_PRINTER_ID,
                PrintJob.width_mm == profile.width_mm,
                LabelCopy.state == State.QUEUED,
            )
        )
        or 0
    )


def waiting_condition(session: Session, profile: TapeProfile) -> bool:
    state = session.get(PrinterState, 1)
    cartridge = (
        session.get(Cartridge, state.active_cartridge_id)
        if state and state.active_cartridge_id
        else None
    )
    return (cartridge is None or cartridge.profile_id != profile.id) and queued_count(
        session, profile
    ) >= profile.auto_print_threshold


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
        if queued_count(session, profile) < profile.auto_print_threshold:
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
            f"{queued_count(session, profile)} queued copies are waiting for {profile.name}.",
            "/",
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
