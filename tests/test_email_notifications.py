"""SMTP transport and personal subscriptions preserve access and independent retries."""

import smtplib
import time
from email import policy
from email.parser import BytesParser

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from test_access_security import accounts as account_fixture

from app.config import Settings
from app.models import Notification, NotificationDelivery, NotificationEndpoint, Role, User
from app.notifications.email_delivery import normalize_email, send_email
from app.notifications.notification_routing import deliver_routed_pending, endpoint_message
from app.notifications.notifications import enqueue

accounts = account_fixture


@pytest.mark.parametrize("security", ["starttls", "ssl", "plain"])
@pytest.mark.parametrize("from_name", ["", "Taro's Label Room", "Étiquettes, atelier"])
def test_smtp_modes_validate_tls_and_use_envelope_recipient(monkeypatch, security, from_name):
    calls = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            calls.append(("connect", args, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append(("close",))

        def starttls(self, **kwargs):
            assert kwargs["context"].check_hostname
            calls.append(("tls",))

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message):
            calls.append(("message", message))

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTP)
    settings = Settings(
        smtp_host="smtp.invalid",
        smtp_from="labels@example.invalid",
        smtp_from_name=from_name,
        smtp_security=security,
        smtp_username="sender",
        smtp_password=SecretStr("test-only-password"),
    )
    send_email(
        settings, "User@example.invalid", "Tape needs attention", "Open the printer settings."
    )
    assert ("tls",) in calls if security == "starttls" else ("tls",) not in calls
    if security == "ssl":
        assert calls[0][2]["context"].check_hostname
    assert calls[-3] == ("login", "sender", "test-only-password")
    message = calls[-2][1]
    assert message["To"] == "user@example.invalid"
    parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
    sender = parsed["From"].addresses
    assert len(sender) == 1
    assert sender[0].addr_spec == "labels@example.invalid"
    assert sender[0].display_name == from_name
    if not from_name:
        assert message["From"] == "labels@example.invalid"
    assert message.get_content().strip() == "Open the printer settings."


def test_sender_name_rejects_header_injection_before_connecting(monkeypatch):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("Invalid sender must not connect to SMTP")

    monkeypatch.setattr(smtplib, "SMTP", unexpected_connection)
    with pytest.raises(ValueError):
        send_email(
            Settings(
                smtp_host="smtp.invalid",
                smtp_from="labels@example.invalid",
                smtp_from_name="Labels\r\nBcc: other@example.invalid",
            ),
            "user@example.invalid",
            "Test",
            "Body",
        )


def test_starttls_failure_never_falls_back_or_sends_credentials(monkeypatch):
    class SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, **kwargs):
            raise smtplib.SMTPNotSupportedError("No STARTTLS")

        def login(self, *args):
            pytest.fail("Must not authenticate without TLS")

        def send_message(self, *args):
            pytest.fail("Must not send without TLS")

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    with pytest.raises(smtplib.SMTPNotSupportedError):
        send_email(
            Settings(
                smtp_host="smtp.invalid", smtp_from="sender@example.invalid", smtp_username="sender"
            ),
            "user@example.invalid",
            "Test",
            "Body",
        )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "invalid",
        "a@",
        "@example.invalid",
        "a@localhost",
        "a@example.invalid\r\nBcc: b@example.invalid",
        "Name <a@example.invalid>",
        "a@example.invalid,b@example.invalid",
    ],
)
def test_email_address_rejects_invalid_or_multiple_recipients(value):
    with pytest.raises(ValueError):
        normalize_email(value)


def test_admin_email_endpoint_uses_existing_routing_and_retries(accounts, monkeypatch):
    admin, _, _ = accounts
    settings = admin.app.state.settings
    settings.smtp_host = "smtp.invalid"
    settings.smtp_from = "sender@example.invalid"
    payload = {
        "name": "Email alerts",
        "transport": "email",
        "email": "ops@example.invalid",
        "kinds": ["general"],
    }
    response = admin.post("/api/admin/notification-endpoints", json=payload)
    assert response.status_code == 201, response.text
    endpoint = response.json()
    assert endpoint["transport"] == "email" and not endpoint["has_token"]
    sent = []

    def email(settings, recipient, title, body):
        sent.append((recipient, title, body))
        if len(sent) == 1:
            raise OSError("smtp-private-secret")

    monkeypatch.setattr("app.notifications.notification_routing.send_email", email)
    now = time.time()
    with admin.app.state.factory.begin() as session:
        enqueue(session, "Alert", "Message", "/#/printers", now=now)
    deliver_routed_pending(admin.app.state.factory, settings, now)
    with admin.app.state.factory() as session:
        delivery = session.scalar(select(NotificationDelivery))
        assert delivery.last_error == "Delivery failed; will retry"
        assert delivery.delivered_at is None
    deliver_routed_pending(admin.app.state.factory, settings, now + 30)
    assert len(sent) == 2 and sent[-1][0] == "ops@example.invalid"
    assert sent[-1][2].endswith(settings.public_url + "/#/printers")
    with admin.app.state.factory() as session:
        assert session.scalar(select(NotificationDelivery)).delivered_at == now + 30


def make_subscriber(client, username):
    client.app.state.settings.smtp_host = "smtp.invalid"
    client.app.state.settings.smtp_from = "sender@example.invalid"
    with client.app.state.factory.begin() as session:
        user = session.get(User, username)
        user.email = f"{username}@example.invalid"
        role = session.get(Role, f"{username}-access")
        if role:
            role.permissions = [
                {"kind": "destination", "destination_id": "main", "level": "moderator"}
            ]


def test_personal_email_requires_verification_and_cannot_bypass_access(accounts):
    admin, alice, bob = accounts
    body = {"enabled": True, "all_printers": True, "kinds": ["empty_tape"]}
    alice.app.state.settings.smtp_host = "smtp.invalid"
    alice.app.state.settings.smtp_from = "sender@example.invalid"
    assert alice.put("/api/auth/email/subscription", json=body).status_code == 409
    make_subscriber(alice, "alice")
    assert (
        alice.put(
            "/api/auth/email/subscription", json={**body, "kinds": ["approval_digest"]}
        ).status_code
        == 403
    )
    assert (
        alice.put(
            "/api/auth/email/subscription",
            json={**body, "all_printers": False, "destination_ids": ["other"]},
        ).status_code
        == 403
    )
    assert (
        alice.put("/api/auth/email/subscription", json={**body, "all_printers": False}).status_code
        == 422
    )
    csrf = alice.headers.pop("X-CSRF-Token")
    assert alice.put("/api/auth/email/subscription", json=body).status_code == 403
    alice.headers["X-CSRF-Token"] = csrf
    assert alice.put("/api/auth/email/subscription", json=body).status_code == 204
    assert alice.get("/api/auth/email").json()["subscription"]["enabled"]
    assert not bob.get("/api/auth/email").json()["subscription"]["enabled"]
    assert admin.get("/api/admin/notification-endpoints").json() == []
    assert admin.delete("/api/admin/notification-endpoints/personal-email:alice").status_code == 404
    with admin.app.state.factory.begin() as session:
        endpoint = session.get(NotificationEndpoint, "personal-email:alice")
        notice = Notification(
            title="Empty",
            message="No tape",
            path="/#/printers",
            kind="empty_tape",
            context={"printer_id": "main"},
        )
        assert endpoint_message(session, notice, endpoint) is not None
        role = session.get(Role, "alice-access")
        role.permissions = [{"kind": "destination", "destination_id": "main", "level": "request"}]
        session.flush()
        assert endpoint_message(session, notice, endpoint) is None


@pytest.mark.parametrize("change", ["disable", "remove_email", "replace_email", "disable_account"])
def test_personal_pending_delivery_is_cancelled_when_recipient_becomes_invalid(accounts, change):
    admin, alice, _ = accounts
    make_subscriber(alice, "alice")
    assert (
        alice.put(
            "/api/auth/email/subscription", json={"enabled": True, "kinds": ["general"]}
        ).status_code
        == 204
    )
    now = time.time()
    sent = []

    def fail(endpoint, notice):
        sent.append(endpoint.id)
        raise OSError("offline")

    with admin.app.state.factory.begin() as session:
        enqueue(session, "Account alert", "Only Alice", "/", recipient_id="alice", now=now)
    deliver_routed_pending(admin.app.state.factory, admin.app.state.settings, now, fail)
    assert len(sent) == 1
    # Saving identical preferences does not cancel a delivery waiting for retry.
    assert (
        alice.put(
            "/api/auth/email/subscription", json={"enabled": True, "kinds": ["general"]}
        ).status_code
        == 204
    )
    with admin.app.state.factory() as session:
        assert not session.scalar(select(NotificationDelivery)).cancelled
        assert session.get(NotificationEndpoint, "personal-email:alice").revision == 1
    with admin.app.state.factory.begin() as session:
        user = session.get(User, "alice")
        endpoint = session.get(NotificationEndpoint, "personal-email:alice")
        if change == "disable":
            endpoint.enabled = False
        elif change == "remove_email":
            user.email = None
        elif change == "replace_email":
            user.email = "other@example.invalid"
        else:
            user.disabled = True
    deliver_routed_pending(admin.app.state.factory, admin.app.state.settings, now + 30, fail)
    assert len(sent) == 1
    with admin.app.state.factory() as session:
        assert session.scalar(select(NotificationDelivery)).cancelled


def test_personal_general_alerts_do_not_leak_other_users_or_administrator_messages(accounts):
    admin, alice, bob = accounts
    for user, name in ((alice, "alice"), (bob, "bob")):
        make_subscriber(user, name)
        assert (
            user.put(
                "/api/auth/email/subscription", json={"enabled": True, "kinds": ["general"]}
            ).status_code
            == 204
        )
    now = time.time()
    with admin.app.state.factory.begin() as session:
        enqueue(session, "Private", "Only Alice", "/", recipient_id="alice", now=now)
        enqueue(
            session, "Admin", "Only administrators", "/", recipient_id="administrators", now=now
        )
    sent = []
    deliver_routed_pending(
        admin.app.state.factory,
        admin.app.state.settings,
        now,
        lambda endpoint, notice: sent.append((endpoint.owner_id, notice.message)),
    )
    assert sent == [("alice", "Only Alice")]
