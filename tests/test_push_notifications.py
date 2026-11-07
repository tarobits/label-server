"""Web Push ownership, revocation, encryption, and independent outbox delivery."""

import base64
import json
import time

import http_ece
import pytest
import requests
from conftest import install, job, profile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pywebpush import WebPushException
from sqlalchemy import select
from test_access_security import accounts as account_fixture

from app.models import (
    AuthSession,
    Notification,
    NotificationDelivery,
    NotificationEndpoint,
    Role,
    User,
)
from app.notification_routing import deliver_routed_pending, endpoint_message
from app.notifications import enqueue
from app.push_delivery import (
    ExpiredSubscription,
    PushSession,
    generate_key,
    public_key,
    send_push,
    validate_push_url,
)

accounts = account_fixture


def browser_subscription(suffix="one"):
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {
        "endpoint": f"https://fcm.googleapis.com/fcm/send/{suffix}",
        "keys": {
            "p256dh": base64.urlsafe_b64encode(point).rstrip(b"=").decode(),
            "auth": base64.urlsafe_b64encode(b"test-only-key-12").rstrip(b"=").decode(),
        },
    }, key


@pytest.fixture
def push_accounts(accounts, tmp_path):
    settings = accounts[0].app.state.settings
    settings.vapid_private_key_file = tmp_path / "vapid.pem"
    settings.vapid_subject = "mailto:labels@example.invalid"
    generate_key(settings.vapid_private_key_file)
    return accounts


def register(client, suffix="one"):
    subscription, _ = browser_subscription(suffix)
    response = client.post("/api/auth/push", json={"name": suffix, "subscription": subscription})
    assert response.status_code == 201, response.text
    return response.json(), subscription


@pytest.mark.parametrize("change", ["new_device", "preferences", "reenable", "legacy_backlog"])
def test_enabling_completions_only_delivers_future_prints(push_accounts, change):
    admin, _, _ = push_accounts
    factory = admin.app.state.factory
    preferences = {
        "enabled": True,
        "all_printers": False,
        "destination_ids": ["main"],
        "kinds": ["job_printed"],
        "printer_kinds": {"main": ["batch_printed"]},
    }
    device = None
    if change != "new_device":
        device, _ = register(admin)
        if change == "reenable":
            assert (
                admin.put(
                    "/api/auth/push/" + device["id"], json={**preferences, "enabled": False}
                ).status_code
                == 204
            )
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    job(admin, tape["id"])
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    with factory.begin() as session:
        historical = list(session.scalars(select(Notification)))
        assert sorted(notice.kind for notice in historical) == ["batch_printed", "job_printed"]
        if change == "legacy_backlog":
            # Previously, unmatched completions stayed pending without recipients.
            for notice in historical:
                notice.routed_at = None
                notice.cancelled = False
        old_ids = {notice.id for notice in historical}
    if device is None:
        device, _ = register(admin)
    path = "/api/auth/push/" + device["id"]
    assert admin.put(path, json=preferences).status_code == 204
    sent = []

    def send(channel, notice):
        sent.append((channel.id, notice.id, notice.kind))

    # Deliberately do not run delivery between printing and enabling preferences.
    deliver_routed_pending(factory, admin.app.state.settings, time.time() + 1, send)
    assert sent == []
    job(admin, tape["id"])
    worker.tick()
    deliver_routed_pending(factory, admin.app.state.settings, time.time() + 1, send)
    assert sorted(kind for _, _, kind in sent) == ["batch_printed", "job_printed"]
    assert all(identifier not in old_ids for _, identifier, _ in sent)
    with factory() as session:
        assert all(session.get(Notification, identifier).cancelled for identifier in old_ids)


def test_completion_retry_keeps_original_device_and_excludes_later_subscribers(push_accounts):
    admin, _, _ = push_accounts
    factory = admin.app.state.factory
    preferences = {
        "enabled": True,
        "destination_ids": ["main"],
        "kinds": ["job_printed", "batch_printed"],
    }
    first, _ = register(admin, "first")
    assert admin.put("/api/auth/push/" + first["id"], json=preferences).status_code == 204
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    job(admin, tape["id"])
    admin.app.state.fleet.workers["main"].tick()
    # A second device subscribes before even the first delivery attempt.
    second, _ = register(admin, "second")
    assert admin.put("/api/auth/push/" + second["id"], json=preferences).status_code == 204
    sent = []

    def fail(channel, notice):
        sent.append((channel.id, notice.kind))
        raise OSError("Temporary delivery failure")

    now = time.time() + 1
    deliver_routed_pending(factory, admin.app.state.settings, now, fail)
    assert sorted(sent) == [(first["id"], "batch_printed"), (first["id"], "job_printed")]
    deliver_routed_pending(
        factory,
        admin.app.state.settings,
        now + 60,
        lambda channel, notice: sent.append((channel.id, notice.kind)),
    )
    assert len(sent) == 4
    assert all(identifier == first["id"] for identifier, _ in sent)
    with factory() as session:
        assert all(notice.delivered_at for notice in session.scalars(select(Notification)))


@pytest.mark.parametrize(
    "url",
    [
        "http://fcm.googleapis.com/x",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://fcm.googleapis.com.attacker.invalid/x",
        "https://push.apple.com.attacker.invalid/x",
        "https://fcm.googleapis.com:444/x",
        "https://x@fcm.googleapis.com/x",
        "https://fcm.googleapis.com/x#secret",
        "https://fcm.googleapis.com\\@localhost/x",
        "https://fcm.googleapis.com/\nx",
        "https://example.invalid/x",
    ],
)
def test_untrusted_push_urls_cannot_target_arbitrary_servers(url):
    with pytest.raises(ValueError):
        validate_push_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://fcm.googleapis.com/fcm/send/device",
        "https://web.push.apple.com/device",
        "https://updates.push.services.mozilla.com/wpush/v2/device",
    ],
)
def test_supported_mobile_and_firefox_providers(url):
    assert validate_push_url(url) == url


def test_subscriptions_are_private_owned_csrf_protected_and_idempotent(push_accounts):
    admin, alice, bob = push_accounts
    first, subscription = register(alice)
    assert "endpoint" not in json.dumps(first) and "p256dh" not in json.dumps(first)
    assert bob.get("/api/auth/push").json()["devices"] == []
    assert admin.get("/api/admin/notification-endpoints").json() == []
    body = {"name": "renamed", "subscription": subscription}
    assert alice.post("/api/auth/push", json=body).json()["id"] == first["id"]
    assert len(alice.get("/api/auth/push").json()["devices"]) == 1
    assert bob.post("/api/auth/push", json=body).status_code == 409
    for method, path, data in [
        ("put", first["id"], {"enabled": True}),
        ("delete", first["id"], None),
        ("post", first["id"] + "/test", {}),
    ]:
        assert bob.request(method, "/api/auth/push/" + path, json=data).status_code == 404
    csrf = alice.headers.pop("X-CSRF-Token")
    assert alice.post("/api/auth/push", json=body).status_code == 403
    alice.headers["X-CSRF-Token"] = csrf
    anonymous = TestClient(alice.app)
    assert anonymous.get("/api/auth/push").status_code == 401
    anonymous.close()
    invalid = {**subscription, "endpoint": "https://private-server.invalid/private-capability"}
    response = alice.post("/api/auth/push", json={"name": "bad", "subscription": invalid})
    assert response.status_code == 422 and "private-capability" not in response.text
    assert subscription["keys"]["auth"] not in response.text


def test_preferences_permissions_and_delivery_recheck(push_accounts):
    _, alice, _ = push_accounts
    device, _ = register(alice)
    path = "/api/auth/push/" + device["id"]
    assert alice.put(path, json={"enabled": True, "kinds": ["approval_digest"]}).status_code == 403
    scoped = {"enabled": True, "destination_ids": ["main"], "kinds": ["printer_blocked"]}
    assert alice.put(path, json=scoped).status_code == 403
    factory = alice.app.state.factory
    with factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "moderator"}
        ]
    assert alice.put(path, json=scoped).status_code == 204
    with factory.begin() as session:
        endpoint = session.get(NotificationEndpoint, device["id"])
        notice = Notification(
            id="notice",
            kind="printer_blocked",
            context={"printer_id": "main"},
            title="Blocked",
            message="Needs attention",
            path="/#/printers",
        )
        assert endpoint_message(session, notice, endpoint) is not None
        session.get(Role, "alice-access").permissions = []
        session.flush()
        assert endpoint_message(session, notice, endpoint) is None
        endpoint.kinds = ["general"]
        notice.kind, notice.context, notice.recipient_id = "general", {}, "alice"
        assert endpoint_message(session, notice, endpoint) is not None  # No email required.
        notice.recipient_id = "bob"
        assert endpoint_message(session, notice, endpoint) is None
        notice.recipient_id = "alice"
        session.get(User, "alice").disabled = True
        assert endpoint_message(session, notice, endpoint) is None


@pytest.mark.parametrize("action", ["logout", "remove", "expire_session", "revoke_session"])
def test_revocation_prevents_pending_delivery(push_accounts, action):
    _, alice, _ = push_accounts
    device, _ = register(alice)
    factory, settings = alice.app.state.factory, alice.app.state.settings
    now = time.time()
    with factory.begin() as session:
        enqueue(session, "Alert", "Private", "/#/", recipient_id="alice", now=now)

    def fail(*args):
        raise OSError("secret-endpoint")

    deliver_routed_pending(factory, settings, now, send=fail)
    if action == "logout":
        assert alice.post("/api/auth/logout", json={}).status_code == 204
    elif action == "remove":
        assert alice.delete("/api/auth/push/" + device["id"]).status_code == 204
    else:
        with factory.begin() as session:
            login = session.scalar(select(AuthSession).where(AuthSession.user_id == "alice"))
            if action == "expire_session":
                login.expires_at = 0
            else:
                session.delete(login)
    sent = []
    deliver_routed_pending(factory, settings, now + 31, send=lambda *args: sent.append(args))
    assert not sent
    with factory() as session:
        delivery = session.scalar(select(NotificationDelivery))
        assert delivery.cancelled and "secret" not in (delivery.last_error or "")
        if action in ("logout", "remove"):
            assert session.get(NotificationEndpoint, device["id"]).push_subscription == {}


def test_multiple_devices_retry_independently_and_expired_endpoints_are_disabled(
    push_accounts, monkeypatch
):
    _, alice, _ = push_accounts
    first, _ = register(alice, "phone")
    second, _ = register(alice, "tablet")
    factory, settings = alice.app.state.factory, alice.app.state.settings
    now, sent = time.time(), []
    with factory.begin() as session:
        enqueue(session, "Alert", "Private", "/#/", recipient_id="alice", now=now)

    def send(settings, endpoint, notice):
        sent.append(endpoint.id)
        if endpoint.id == first["id"]:
            raise OSError("private-subscription-url")

    monkeypatch.setattr("app.notification_routing.send_push", send)
    deliver_routed_pending(factory, settings, now)
    assert sorted(sent) == sorted([first["id"], second["id"]])

    def expired(*args):
        raise ExpiredSubscription()

    monkeypatch.setattr("app.notification_routing.send_push", expired)
    deliver_routed_pending(factory, settings, now + 31)
    with factory() as session:
        assert not session.get(NotificationEndpoint, first["id"]).enabled
        assert session.get(NotificationEndpoint, second["id"]).enabled
        deliveries = list(session.scalars(select(NotificationDelivery)))
        assert sorted(item.attempts for item in deliveries) == [1, 2]
        assert sum(item.cancelled for item in deliveries) == 1
        assert all("private-subscription" not in (item.last_error or "") for item in deliveries)


def test_real_webpush_encryption_vapid_and_redirect_policy(push_accounts, monkeypatch):
    settings = push_accounts[0].app.state.settings
    subscription, private_key = browser_subscription()
    captured = []

    def transport(self, method, url, **kwargs):
        captured.append(kwargs)
        assert not kwargs["allow_redirects"] and kwargs["timeout"] == 10
        response = requests.Response()
        response.status_code = 201
        return response

    monkeypatch.setattr(requests.Session, "request", transport)
    endpoint = NotificationEndpoint(push_subscription=subscription)
    send_push(
        settings,
        endpoint,
        Notification(id="notice", title="Test", message="Encrypted body", path="/#/account"),
    )
    request = captured[0]
    assert request["headers"]["authorization"].startswith("vapid ")
    assert request["headers"]["ttl"] == "300"
    decrypted = http_ece.decrypt(
        request["data"],
        private_key=private_key,
        auth_secret=b"test-only-key-12",
        version="aes128gcm",
    )
    assert json.loads(decrypted) == {
        "title": "Test",
        "body": "Encrypted body",
        "path": "/#/account",
        "tag": "notice",
    }
    assert public_key(settings) and settings.vapid_private_key_file.stat().st_mode & 0o777 == 0o600
    original = settings.vapid_private_key_file.read_bytes()
    with pytest.raises(FileExistsError):
        generate_key(settings.vapid_private_key_file)
    assert settings.vapid_private_key_file.read_bytes() == original
    with pytest.raises(ValueError):
        PushSession().post("https://127.0.0.1/private")


@pytest.mark.parametrize("status", [404, 410, 429, 500])
def test_permanent_vs_transient_delivery_errors(push_accounts, monkeypatch, status):
    settings = push_accounts[0].app.state.settings
    subscription, _ = browser_subscription()

    def reject(*args, **kwargs):
        response = requests.Response()
        response.status_code = status
        raise WebPushException("secret-endpoint", response=response)

    monkeypatch.setattr("app.push_delivery.webpush", reject)
    with pytest.raises(ExpiredSubscription if status in (404, 410) else ValueError) as error:
        send_push(
            settings,
            NotificationEndpoint(push_subscription=subscription),
            Notification(id="n", title="T", message="B", path="/#/"),
        )
    assert "secret" not in str(error.value)


def test_test_notification_only_targets_selected_owned_device(push_accounts, monkeypatch):
    _, alice, bob = push_accounts
    device, _ = register(alice)
    sent = []
    monkeypatch.setattr(
        "app.push_api.send_push",
        lambda settings, endpoint, notice: sent.append((endpoint.id, notice.path)),
    )
    path = "/api/auth/push/" + device["id"] + "/test"
    assert bob.post(path, json={}).status_code == 404
    assert alice.post(path, json={}).status_code == 204
    assert sent == [(device["id"], "/#/account")]


def test_renewal_preserves_preferences_and_cannot_replace_another_users_device(push_accounts):
    _, alice, bob = push_accounts
    old, _ = register(alice)
    path = "/api/auth/push/" + old["id"]
    assert (
        alice.put(
            path, json={"enabled": True, "all_printers": True, "kinds": ["general", "empty_tape"]}
        ).status_code
        == 204
    )
    subscription, _ = browser_subscription("replacement")
    body = {"name": "Phone", "subscription": subscription, "replace_id": old["id"]}
    assert bob.post("/api/auth/push", json=body).status_code == 404
    response = alice.post("/api/auth/push", json=body)
    assert response.status_code == 201
    assert response.json()["kinds"] == ["general", "empty_tape"]
    assert response.json()["all_printers"]
    assert len(alice.get("/api/auth/push").json()["devices"]) == 1
    with alice.app.state.factory() as session:
        previous = session.get(NotificationEndpoint, old["id"])
        assert previous.deleted_at and not previous.push_subscription and not previous.enabled


def test_unconfigured_server_reports_unavailable_and_rejects_subscription(accounts):
    _, alice, _ = accounts
    alice.app.state.settings.vapid_private_key_file = None
    assert alice.get("/api/auth/push").json()["public_key"] is None
    subscription, _ = browser_subscription()
    assert (
        alice.post(
            "/api/auth/push", json={"name": "Phone", "subscription": subscription}
        ).status_code
        == 409
    )
