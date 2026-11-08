"""Per-printer choices refine routing without broadening subscription access."""

from types import SimpleNamespace

import pytest
from conftest import profile
from test_access_security import accounts as account_fixture
from test_email_notifications import make_subscriber
from test_notification_endpoints import configuration, create, pending_delivery
from test_notification_routing import endpoint

from app.config import Settings
from app.models import (
    Notification,
    NotificationDelivery,
    NotificationEndpoint,
    PrinterDevice,
    PrinterGroup,
    Role,
)
from app.notification_routing import endpoint_message
from app.notifications import NtfySender

accounts = account_fixture


def capture_ntfy(monkeypatch):
    payloads = []

    def post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr("app.notifications.httpx.post", post)
    return payloads


def test_ntfy_uses_printer_priority_and_falls_back_to_endpoint_default(client, monkeypatch):
    payloads = capture_ntfy(monkeypatch)
    with client.app.state.factory.begin() as session:
        session.add(PrinterDevice(id="other", name="Other", driver="mock", config={}))
        channel = endpoint(
            session,
            "priority",
            priorities={"empty_tape": 5, "batch_review": 3},
            printer_kinds={"main": ["empty_tape", "batch_review"]},
            printer_priorities={"main": {"empty_tape": 1}},
        )
        sender = NtfySender(Settings(), channel)
        for printer, kind, expected in [
            ("main", "empty_tape", 1),
            ("main", "batch_review", 3),
            ("other", "empty_tape", 5),
        ]:
            message = endpoint_message(
                session,
                Notification(
                    kind=kind,
                    title="Alert",
                    message="Body",
                    path="/",
                    context={"printer_id": printer},
                ),
                channel,
            )
            assert message is not None
            sender.send(message)
            assert payloads[-1]["priority"] == expected


def test_combined_reminder_priority_uses_only_included_printers(client, monkeypatch):
    payloads = capture_ntfy(monkeypatch)
    tape = profile(client)
    monkeypatch.setattr(
        "app.notification_routing.waiting_destinations",
        lambda *args: [
            ("main", "Main", 3),
            ("other", "Other", 4),
            ("muted", "Muted", 5),
        ],
    )
    with client.app.state.factory.begin() as session:
        for identifier in ["other", "muted"]:
            session.add(PrinterDevice(id=identifier, name=identifier, driver="mock", config={}))
        channel = endpoint(
            session,
            "combined",
            kinds=["tape_waiting"],
            priorities={"tape_waiting": 3},
            printer_kinds={"main": ["tape_waiting"], "other": ["tape_waiting"], "muted": []},
            printer_priorities={
                "main": {"tape_waiting": 1},
                "other": {"tape_waiting": 2},
                "muted": {"tape_waiting": 5},
            },
        )
        notice = Notification(
            kind="tape_waiting",
            title="Waiting",
            message="Body",
            path="/",
            profile_id=tape["id"],
            context={"destination_ids": ["main", "other", "muted"]},
        )
        message = endpoint_message(session, notice, channel)
        assert message is not None
        assert message.context["destination_ids"] == ["main", "other"]
        assert notice.context["destination_ids"] == ["main", "other", "muted"]
        NtfySender(Settings(), channel).send(message)
        assert payloads[-1]["priority"] == 2
        channel.printer_priorities = {"main": {"tape_waiting": 1}, "muted": {"tape_waiting": 5}}
        NtfySender(Settings(), channel).send(message)
        assert payloads[-1]["priority"] == 3


@pytest.mark.parametrize(
    "priorities",
    [
        {"main": {"empty_tape": 0}},
        {"main": {"empty_tape": 6}},
        {"main": {"empty_tape": True}},
        {"main": {"general": 3}},
        {"other": {"empty_tape": 4}},
    ],
)
def test_invalid_custom_priorities_are_rejected(accounts, priorities):
    admin, _, _ = accounts
    assert (
        admin.post(
            "/api/admin/notification-endpoints",
            json=configuration(
                printer_kinds={"main": ["empty_tape"]},
                printer_priorities=priorities,
            ),
        ).status_code
        == 422
    )


def test_priority_updates_persist_and_cancel_only_changed_pending_deliveries(accounts):
    admin, _, _ = accounts
    body = configuration(
        printer_kinds={"main": ["empty_tape"]}, printer_priorities={"main": {"empty_tape": 5}}
    )
    saved = create(admin, **body)
    delivery_id = pending_delivery(admin, saved)
    url = f"/api/admin/notification-endpoints/{saved['id']}"
    unchanged = admin.put(url, json=body)
    assert unchanged.status_code == 200
    assert unchanged.json()["revision"] == saved["revision"]
    assert (
        admin.get("/api/admin/notification-endpoints").json()[0]["printer_priorities"]
        == body["printer_priorities"]
    )
    with admin.app.state.factory() as session:
        assert not session.get(NotificationDelivery, delivery_id).cancelled
    body["printer_priorities"] = {}
    assert admin.put(url, json=body).status_code == 200
    with admin.app.state.factory() as session:
        assert session.get(NotificationDelivery, delivery_id).cancelled
    body.update(
        transport="email",
        email="operations@example.invalid",
        printer_priorities={"main": {"empty_tape": 5}},
    )
    changed = admin.put(url, json=body)
    assert changed.status_code == 200
    assert changed.json()["printer_priorities"] == {}


@pytest.mark.parametrize("transport", ["ntfy", "email"])
def test_per_printer_choices_replace_defaults_and_follow_current_scope(client, transport):
    with client.app.state.factory.begin() as session:
        session.add(PrinterDevice(id="other", name="Other", driver="mock", config={}))
        group = PrinterGroup(id="group", name="Group", printer_ids=["main", "other"])
        session.add(group)
        channel = endpoint(
            session,
            "custom",
            transport=transport,
            kinds=["empty_tape"],
            destination_ids=["group"],
            printer_kinds={"main": ["batch_review"]},
        )

        def message(printer, kind):
            return endpoint_message(
                session,
                Notification(
                    kind=kind,
                    title="Alert",
                    message="Body",
                    path="/",
                    context={"printer_id": printer},
                ),
                channel,
            )

        assert message("main", "empty_tape") is None
        assert message("main", "batch_review") is not None
        assert message("other", "empty_tape") is not None
        assert message("other", "batch_review") is None
        channel.printer_kinds = {"main": []}
        assert message("main", "empty_tape") is None
        channel.printer_kinds = {"main": ["empty_tape"]}
        group.printer_ids = ["other"]
        assert message("main", "empty_tape") is None
        channel.all_printers = True
        session.add(PrinterDevice(id="future", name="Future", driver="mock", config={}))
        session.flush()
        assert message("future", "empty_tape") is not None


def test_waiting_reminder_includes_only_printers_with_the_event_enabled(client, monkeypatch):
    tape = profile(client)
    monkeypatch.setattr(
        "app.notification_routing.waiting_destinations",
        lambda *args: [
            ("main", "Main", 3),
            ("other", "Other", 5),
            ("group", "Group", 7),
        ],
    )
    with client.app.state.factory.begin() as session:
        session.add(PrinterDevice(id="other", name="Other", driver="mock", config={}))
        session.add(PrinterGroup(id="group", name="Group", printer_ids=["main", "other"]))
        channel = endpoint(session, "waiting", kinds=[], printer_kinds={"main": ["tape_waiting"]})
        notice = Notification(
            kind="tape_waiting",
            title="Waiting",
            message="Original",
            path="/",
            profile_id=tape["id"],
            context={"destination_ids": ["main", "other", "group"]},
        )
        message = endpoint_message(session, notice, channel)
        assert message is not None
        assert "3 queued copies at Main" in message.message
        assert "Other" not in message.message and "Group" not in message.message
        channel.kinds = ["tape_waiting"]
        channel.printer_kinds = {"main": []}
        message = endpoint_message(session, notice, channel)
        assert message is not None
        assert "Main" not in message.message
        assert "5 queued copies at Other" in message.message
        assert "7 queued copies at Group" in message.message


@pytest.mark.parametrize(
    "overrides",
    [
        {"printer_kinds": {"missing": ["empty_tape"]}},
        {"destination_ids": [], "printer_kinds": {"main": ["empty_tape"]}, "kinds": ["general"]},
        {"printer_kinds": {"main": ["general"]}},
        {"printer_kinds": {"main": ["approval_digest"]}},
        {"printer_kinds": {"main": ["empty_tape", "empty_tape"]}},
        {"printer_kinds": {"main": []}, "kinds": []},
    ],
)
def test_invalid_printer_choices_are_rejected(accounts, overrides):
    admin, _, _ = accounts
    response = admin.post("/api/admin/notification-endpoints", json=configuration(**overrides))
    assert response.status_code == 422


def test_override_only_endpoint_and_unchanged_save_preserve_pending_deliveries(accounts):
    admin, _, _ = accounts
    rules = {"main": ["empty_tape", "batch_review"]}
    saved = create(admin, kinds=[], printer_kinds=rules)
    delivery_id = pending_delivery(admin, saved)
    body = configuration(kinds=[], printer_kinds={"main": list(reversed(rules["main"]))})
    result = admin.put(f"/api/admin/notification-endpoints/{saved['id']}", json=body)
    assert result.status_code == 200
    assert result.json()["revision"] == saved["revision"]
    assert result.json()["printer_kinds"] == {"main": ["batch_review", "empty_tape"]}
    with admin.app.state.factory() as session:
        assert not session.get(NotificationDelivery, delivery_id).cancelled
    body["printer_kinds"] = {"main": ["batch_review"]}
    assert (
        admin.put(f"/api/admin/notification-endpoints/{saved['id']}", json=body).status_code == 200
    )
    with admin.app.state.factory() as session:
        assert session.get(NotificationDelivery, delivery_id).cancelled


def test_personal_printer_choices_require_direct_permission_and_recheck_it(accounts):
    admin, alice, _ = accounts
    make_subscriber(alice, "alice")
    body = {
        "enabled": True,
        "all_printers": True,
        "kinds": [],
        "printer_kinds": {"main": ["empty_tape"]},
    }
    assert alice.put("/api/auth/email/subscription", json=body).status_code == 204
    assert (
        alice.get("/api/auth/email").json()["subscription"]["printer_kinds"]
        == body["printer_kinds"]
    )
    with admin.app.state.factory.begin() as session:
        session.add(PrinterGroup(id="group", name="Group", printer_ids=["main"]))
        channel = session.get(NotificationEndpoint, "personal-email:alice")
        notice = Notification(
            kind="empty_tape",
            title="Empty",
            message="Body",
            path="/",
            context={"printer_id": "main"},
        )
        assert endpoint_message(session, notice, channel) is not None
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "group", "level": "full"}
        ]
        session.flush()
        assert endpoint_message(session, notice, channel) is None
    # Selecting the group never grants direct access to its physical printer overrides.
    body.update(all_printers=False, destination_ids=["group"])
    assert alice.put("/api/auth/email/subscription", json=body).status_code == 403


def test_group_member_overrides_are_allowed_but_group_ids_are_not_printers(accounts):
    admin, _, _ = accounts
    with admin.app.state.factory.begin() as session:
        session.add(PrinterGroup(id="group", name="Group", printer_ids=["main"]))
    result = create(admin, destination_ids=["group"], printer_kinds={"main": []})
    assert result["printer_kinds"] == {"main": []}
    assert (
        admin.post(
            "/api/admin/notification-endpoints",
            json=configuration(
                destination_ids=["group"],
                printer_kinds={"group": ["empty_tape"]},
            ),
        ).status_code
        == 422
    )
