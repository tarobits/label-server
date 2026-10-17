import time
from threading import Event

import pytest
from alembic import command
from alembic.config import Config
from conftest import create_test_app, profile, seed_test_printer
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_fleet import device, fit, submit

from app.config import Settings
from app.identity import LOCAL_OWNER_ID
from app.models import (
    Notification,
    NotificationDelivery,
    NotificationEndpoint,
    PrinterDevice,
    PrinterGroup,
    Role,
    TapeProfile,
    User,
)
from app.notification_routing import deliver_routed_pending, endpoint_message, scope_matches
from app.notifications import NtfySender, enqueue, schedule_reminders, waiting_destinations
from app.request_models import PrintRequest


def endpoint(session, identifier, **filters):
    values = dict(
        id=identifier,
        name=identifier,
        url="https://ntfy.invalid",
        topic=identifier,
        destination_ids=[],
        all_printers=not bool(filters.get("destination_ids")),
        kinds=[
            "general",
            "empty_tape",
            "printer_blocked",
            "batch_review",
            "tape_waiting",
            "approval_digest",
        ],
    )
    values.update(filters)
    result = NotificationEndpoint(**values)
    session.add(result)
    session.flush()
    return result


def test_independent_delivery_retry_restart_and_no_replay(client):
    factory = client.app.state.factory
    now = time.time()
    with factory.begin() as session:
        endpoint(session, "healthy")
        endpoint(session, "retry")
        enqueue(session, "Alert", "Message", "/", now=now)
    sent = []

    def send(channel, notice):
        sent.append(channel.id)
        if channel.id == "retry":
            raise OSError("secret-token must not enter persistent errors")

    deliver_routed_pending(factory, Settings(), now, send)
    assert sorted(sent) == ["healthy", "retry"]
    with factory.begin() as session:
        notice = session.scalar(select(Notification))
        assert notice.delivered_at is None
        assert "secret" not in notice.last_error
        endpoint(session, "added-later")
    deliver_routed_pending(factory, Settings(), now + 29, send)
    assert len(sent) == 2
    # A new invocation reads persisted delivery rows, just like a worker restart.
    deliver_routed_pending(
        factory, Settings(), now + 30, lambda channel, notice: sent.append(channel.id)
    )
    assert sent.count("healthy") == 1
    assert sent.count("retry") == 2
    assert "added-later" not in sent
    deliver_routed_pending(factory, Settings(), now + 3600, send)
    assert len(sent) == 3
    with factory() as session:
        assert session.scalar(select(Notification)).delivered_at == now + 30
        assert len(list(session.scalars(select(NotificationDelivery)))) == 2
    assert client.get("/api/batches").json() == []


def test_unmatched_backlog_does_not_starve_new_alerts(client):
    factory = client.app.state.factory
    now = time.time()
    with factory.begin() as session:
        endpoint(session, "main-only", destination_ids=["main"])
        for index in range(101):
            enqueue(
                session,
                str(index),
                "Unmatched",
                "/",
                now=now - 10,
                context={"printer_id": "unselected-printer"},
            )
        enqueue(
            session, "New matching alert", "Message", "/", now=now, context={"printer_id": "main"}
        )
    sent = []
    for tick in (now, now + 1, now + 2):
        deliver_routed_pending(
            factory, Settings(), tick, lambda channel, notice: sent.append(notice.title)
        )
    assert sent == ["New matching alert"]


def test_explicit_group_includes_member_operational_alerts_but_not_member_approvals(client):
    with client.app.state.factory.begin() as session:
        session.add(PrinterGroup(id="station", name="Station", printer_ids=["main"]))
        session.flush()
        channel = endpoint(
            session,
            "station-topic",
            destination_ids=["station"],
        )
        assert scope_matches(session, channel, "main")
        assert not scope_matches(session, channel, "other")
        assert not scope_matches(session, channel, "main", include_members=False)
        notice = Notification(
            kind="printer_blocked",
            context={"printer_id": "main"},
            title="Printing blocked",
            message="Out of tape",
            path="/",
        )
        message = endpoint_message(session, notice, channel)
        assert message.message == "Mock printer: Out of tape"


def test_all_printers_includes_future_devices_but_explicit_selection_is_a_snapshot(client):
    with client.app.state.factory.begin() as session:
        endpoint(session, "all")
        endpoint(session, "snapshot", destination_ids=["main"])
    future = device(client, "Future printer")
    with client.app.state.factory.begin() as session:
        all_channel = session.get(NotificationEndpoint, "all")
        snapshot = session.get(NotificationEndpoint, "snapshot")
        for destination, expected in (("main", True), (future, False)):
            notice = Notification(
                kind="general",
                title="Scoped",
                message="Scoped",
                path="/",
                context={"printer_id": destination},
            )
            assert endpoint_message(session, notice, all_channel) is not None
            assert (endpoint_message(session, notice, snapshot) is not None) is expected
        session.add(PrinterGroup(id="future-group", name="Future group", printer_ids=[future]))
        session.flush()
        assert scope_matches(session, all_channel, "future-group", include_members=False)
        assert not scope_matches(session, snapshot, "future-group", include_members=False)


@pytest.mark.parametrize("kind", ["empty_tape", "printer_blocked", "batch_review", "tape_waiting"])
def test_zero_scope_never_routes_operational_alerts_even_for_existing_legacy_rows(client, kind):
    tape = profile(client, threshold=1, reminders=True)
    submit(client, "main", tape)
    with client.app.state.factory.begin() as session:
        channel = endpoint(session, "zero-scope", all_printers=False)
        notice = Notification(
            kind=kind,
            title="Operational",
            message="Do something",
            path="/",
            profile_id=tape["id"] if kind == "tape_waiting" else None,
            context={"printer_id": "main", "destination_ids": ["main"]},
        )
        assert not scope_matches(session, channel, "main")
        assert endpoint_message(session, notice, channel) is None


def test_endpoint_kind_filter_is_applied_before_destination_match(client):
    with client.app.state.factory.begin() as session:
        channel = endpoint(session, "only-general", destination_ids=["main"], kinds=["general"])
        notice = Notification(
            kind="printer_blocked",
            title="Blocked",
            message="Out of tape",
            path="/",
            context={"printer_id": "main"},
        )
        assert endpoint_message(session, notice, channel) is None


def test_scoped_digest_counts_only_exact_logical_destinations(client):
    with client.app.state.factory.begin() as session:
        session.add(PrinterGroup(id="station", name="Station", printer_ids=["main"]))
        session.add(PrinterDevice(id="elsewhere", name="Other", driver="mock", config={}))
        for identifier, destination in (
            ("physical", "main"),
            ("group", "station"),
            ("other", "elsewhere"),
        ):
            session.add(
                PrintRequest(
                    id=identifier,
                    owner_id="owner",
                    destination_id=destination,
                    kind="label",
                    request_hash="hash",
                    labels=[],
                )
            )
        session.flush()
        notice = Notification(
            kind="approval_digest",
            context={},
            title="Pending",
            message="3 pending",
            path="/#/requests",
        )
        channel = endpoint(
            session,
            "station-topic",
            destination_ids=["station"],
        )
        assert (
            endpoint_message(session, notice, channel).message == "1 print request(s) await review."
        )
        global_channel = endpoint(session, "global", all_printers=False)
        assert (
            endpoint_message(session, notice, global_channel).message
            == "3 print request(s) await review."
        )


def test_unscoped_general_messages_route_by_kind_without_printer_filters(client):
    with client.app.state.factory.begin() as session:
        notice = Notification(kind="general", context={}, title="Old", message="Private", path="/")
        for channel in (
            endpoint(session, "global", all_printers=False),
            endpoint(session, "scoped", destination_ids=["main"]),
            endpoint(session, "all"),
        ):
            assert endpoint_message(session, notice, channel).message == "Private"
        excluded = endpoint(session, "excluded", kinds=["approval_digest"], all_printers=False)
        assert endpoint_message(session, notice, excluded) is None


def test_waiting_message_is_scoped_and_retry_stops_after_that_destination_recovers(client):
    second = device(client, "Private other printer")
    tape = profile(client, threshold=1, reminders=True)
    submit(client, "main", tape)
    submit(client, second, tape)
    factory = client.app.state.factory
    now = time.time()
    with factory.begin() as session:
        endpoint(session, "main-topic", destination_ids=["main"])
        schedule_reminders(session, now)
    messages = []

    def fail(channel, notice):
        messages.append(notice.message)
        raise OSError("network")

    deliver_routed_pending(factory, Settings(), now, fail)
    assert len(messages) == 1
    assert "Mock printer" in messages[0]
    assert "Private other printer" not in messages[0]
    fit(client, "main", tape)
    deliver_routed_pending(factory, Settings(), now + 30, fail)
    assert len(messages) == 1
    with factory() as session:
        assert session.scalar(select(NotificationDelivery)).cancelled


@pytest.mark.parametrize(
    "change", ["scope", "revision", "disabled", "cancelled", "retired", "kind"]
)
def test_pending_delivery_rechecks_scope_and_configuration(client, change):
    factory = client.app.state.factory
    now = time.time()
    with factory.begin() as session:
        endpoint(
            session,
            "printer-topic",
            destination_ids=["main"],
        )
        enqueue(session, "Alert", "Message", "/", now=now, context={"printer_id": "main"})

    def fail(channel, notice):
        raise OSError("network")

    deliver_routed_pending(factory, Settings(), now, fail)
    with factory.begin() as session:
        if change == "scope":
            session.get(NotificationEndpoint, "printer-topic").destination_ids = []
        elif change == "revision":
            session.get(NotificationEndpoint, "printer-topic").revision += 1
        elif change == "disabled":
            session.get(NotificationEndpoint, "printer-topic").enabled = False
        elif change == "cancelled":
            session.scalar(select(Notification)).cancelled = True
        elif change == "retired":
            session.get(PrinterDevice, "main").config = {"retired": True}
        else:
            session.get(NotificationEndpoint, "printer-topic").kinds = ["approval_digest"]
    sent = []
    deliver_routed_pending(
        factory, Settings(), now + 30, lambda channel, notice: sent.append(notice.id)
    )
    assert not sent
    with factory() as session:
        assert session.scalar(select(NotificationDelivery)).cancelled


def test_role_changes_do_not_change_printer_notification_delivery(client):
    factory = client.app.state.factory
    now = time.time()
    with factory.begin() as session:
        session.add(Role(id="unrelated", name="Unrelated", permissions=[]))
        endpoint(session, "main-topic", destination_ids=["main"])
        enqueue(session, "Scoped", "Message", "/", now=now, context={"printer_id": "main"})

    def fail(channel, notice):
        raise OSError("network")

    deliver_routed_pending(factory, Settings(), now, fail)
    with factory.begin() as session:
        session.delete(session.get(Role, "unrelated"))
    sent = []
    deliver_routed_pending(
        factory, Settings(), now + 30, lambda channel, notice: sent.append(channel.id)
    )
    assert sent == ["main-topic"]


def test_ntfy_priority_uses_each_endpoints_settings_for_the_event_kind(client, monkeypatch):
    sent = []

    class Response:
        def raise_for_status(self):
            pass

    def publish(url, **kwargs):
        sent.append(kwargs["json"])
        return Response()

    monkeypatch.setattr("httpx.post", publish)
    with client.app.state.factory.begin() as session:
        high = endpoint(session, "high", priorities={"empty_tape": 5, "batch_review": 1})
        low = endpoint(session, "low", priorities={"empty_tape": 2})
        for channel in (high, low):
            NtfySender(Settings(), channel).send(
                Notification(kind="empty_tape", title="Empty", message="Empty", path="/")
            )
        NtfySender(Settings(), high).send(
            Notification(kind="batch_review", title="Review", message="Review", path="/")
        )
        NtfySender(Settings(), low).send(
            Notification(kind="tape_waiting", title="Waiting", message="Waiting", path="/")
        )
    assert [(body["topic"], body["priority"]) for body in sent] == [
        ("high", 5),
        ("low", 2),
        ("high", 1),
        ("low", 3),
    ]


def test_captured_delivery_ids_recheck_cancellation(client):
    factory = client.app.state.factory
    now = time.time()
    with factory.begin() as session:
        endpoint(session, "admin")
        for name in ("first", "second"):
            enqueue(session, name, name, "/", now=now)
    sent = []

    def send(channel, notice):
        sent.append(notice.title)
        with factory.begin() as session:
            for other in session.scalars(select(Notification).where(Notification.id != notice.id)):
                other.cancelled = True

    deliver_routed_pending(factory, Settings(), now, send)
    assert len(sent) == 1
    with factory() as session:
        rows = list(session.scalars(select(NotificationDelivery)))
        assert sum(row.cancelled for row in rows) == 1
        assert sum(row.delivered_at is not None for row in rows) == 1


def test_new_waiting_destination_gets_reminder_while_earlier_notice_has_no_channel(client):
    second = device(client, "Second destination")
    tape = profile(client, threshold=1, reminders=True)
    submit(client, "main", tape)
    factory = client.app.state.factory
    now = time.time()
    with factory.begin() as session:
        endpoint(session, "second-topic", destination_ids=[second])
        schedule_reminders(session, now)
    sent = []
    deliver_routed_pending(
        factory, Settings(), now, lambda channel, notice: sent.append(notice.message)
    )
    assert not sent
    submit(client, second, tape)
    with factory.begin() as session:
        schedule_reminders(session, now + 60)
    deliver_routed_pending(
        factory, Settings(), now + 60, lambda channel, notice: sent.append(notice.message)
    )
    assert len(sent) == 1
    assert "Second destination" in sent[0]
    assert "Mock printer" not in sent[0]


@pytest.mark.parametrize("change", ["edit", "delete"])
def test_endpoint_change_settles_canceled_parent_and_allows_next_tape_reminder(client, change):
    tape = profile(client, threshold=1, reminders=True)
    factory = client.app.state.factory
    with factory.begin() as session:
        endpoint(session, "main-topic", destination_ids=["main"])
        # Admin mutations recheck queued job ownership using real account data.
        session.add(
            User(
                id=LOCAL_OWNER_ID,
                username="owner",
                password_hash="unused",
                role_ids=["administrator"],
            )
        )
    submit(client, "main", tape)
    now = time.time() + 1

    def fail(channel, notice):
        raise OSError("network")

    deliver_routed_pending(factory, Settings(), now, fail)
    with factory() as session:
        old_notice = session.scalar(select(Notification).where(Notification.kind == "tape_waiting"))
        old_id = old_notice.id
        assert old_notice.routed_at is not None
    payload = {
        "name": "main-topic",
        "url": "https://ntfy.invalid",
        "topic": "main-topic",
        "destination_ids": ["main"],
        "all_printers": False,
        "kinds": ["tape_waiting"],
        "priorities": {"tape_waiting": 5},
    }
    if change == "edit":
        response = client.put("/api/admin/notification-endpoints/main-topic", json=payload)
        assert response.status_code == 200, response.text
    else:
        assert client.delete("/api/admin/notification-endpoints/main-topic").status_code == 204
        response = client.post("/api/admin/notification-endpoints", json=payload)
        assert response.status_code == 201, response.text
    with factory.begin() as session:
        assert session.get(Notification, old_id).cancelled
        current_profile = session.get(TapeProfile, tape["id"])
        assert waiting_destinations(session, current_profile)
        schedule_reminders(session, now + 60)
    sent = []
    deliver_routed_pending(
        factory, Settings(), now + 60, lambda channel, notice: sent.append(notice.id)
    )
    assert len(sent) == 1 and sent[0] != old_id


def test_endpoint_added_after_startup_delivers_without_restart(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'notifier.db'}"
    migration = Config("alembic.ini")
    migration.attributes["database_url"] = url
    command.upgrade(migration, "head")
    seed_test_printer(url)
    received = Event()
    monkeypatch.setattr(NtfySender, "send", lambda self, notice: received.set())
    settings = Settings(database_url=url, worker_interval_seconds=0.02)
    with TestClient(create_test_app(settings)) as running:
        assert not running.get("/api/workspace").json()["notifications_enabled"]
        with running.app.state.factory.begin() as session:
            endpoint(session, "new-after-start")
            enqueue(session, "Alert", "Message", "/")
        assert received.wait(3), (
            "Notification worker must start without legacy environment settings"
        )
        assert running.get("/api/workspace").json()["notifications_enabled"]
