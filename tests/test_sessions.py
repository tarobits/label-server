"""Session inventory, privacy boundaries, activity and remote sign-out."""

import time
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app_client import TestClient
from sqlalchemy import select, text
from test_auth import PASSWORD, auth_client, invite, register_member, setup_admin

from app.auth import COOKIE_NAME, token_hash
from app.db import make_engine
from app.models import AuthSession, NotificationEndpoint
from app.session_details import client_description

__all__ = ["auth_client"]
UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/140.0.0.0 Mobile Safari/537.36"


def other_login(client):
    other = TestClient(client.app)
    result = other.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert result.status_code == 200
    other.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return other


def test_inventory_is_private_and_never_exposes_credentials(auth_client, tmp_path):
    client = auth_client
    assert client.get("/api/auth/sessions").status_code == 401
    client.headers["user-agent"] = UA
    setup_admin(client, tmp_path)
    with closing(other_login(client)) as other:
        response = client.get("/api/auth/sessions")
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        rows = response.json()
        assert len(rows) == 2
        current = next(row for row in rows if row["current"])
        assert current["device"] == "Android phone"
        assert current["browser"] == "Chrome 140.0.0.0"
        assert current["os"] == "Android 10"
        assert current["user_agent"] == UA
        assert current["created_at"] <= current["last_seen_at"] + 1
        for browser in (client, other):
            token = browser.cookies[COOKIE_NAME]
            assert token not in response.text
            assert token_hash(token) not in response.text
            assert browser.headers["X-CSRF-Token"] not in response.text
        code = invite(client)
        with closing(TestClient(client.app)) as member:
            register_member(member, code)
            assert len(member.get("/api/auth/sessions").json()) == 1
            foreign_id = member.get("/api/auth/sessions").json()[0]["id"]
            # Administrator status does not grant access to this personal API.
            assert client.delete(f"/api/auth/sessions/{foreign_id}").status_code == 404
            assert member.delete(f"/api/auth/sessions/{current['id']}").status_code == 404


def test_remote_signout_requires_csrf_and_revokes_push(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    with closing(other_login(client)) as other:
        target = next(row for row in client.get("/api/auth/sessions").json() if not row["current"])
        with client.app.state.factory.begin() as session:
            record = session.scalar(select(AuthSession).where(AuthSession.id == target["id"]))
            endpoint = NotificationEndpoint(
                name="Remote browser",
                transport="push",
                url="",
                topic="",
                kinds=["general"],
                owner_id=record.user_id,
                push_session_hash=record.token_hash,
                push_subscription={"endpoint": "test"},
                enabled=True,
            )
            session.add(endpoint)
            session.flush()
            endpoint_id = endpoint.id
        url = f"/api/auth/sessions/{target['id']}"
        assert client.delete(url, headers={"X-CSRF-Token": "wrong"}).status_code == 403
        assert client.delete(url, headers={"Origin": "https://other.example"}).status_code == 403
        assert client.delete(url).status_code == 204
        assert other.get("/api/auth/sessions").status_code == 401
        assert client.get("/api/auth/sessions").status_code == 200
        with client.app.state.factory() as session:
            endpoint = session.get(NotificationEndpoint, endpoint_id)
            assert not endpoint.enabled
            assert endpoint.deleted_at is not None
            assert endpoint.push_subscription == {}
            assert endpoint.push_session_hash is None


def test_sign_out_others_preserves_current_and_other_accounts(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    code = invite(client)
    with closing(other_login(client)) as other, closing(TestClient(client.app)) as member:
        register_member(member, code)
        assert (
            client.delete("/api/auth/sessions/others", headers={"X-CSRF-Token": ""}).status_code
            == 403
        )
        assert client.delete("/api/auth/sessions/others").status_code == 204
        assert other.get("/api/auth/sessions").status_code == 401
        assert member.get("/api/auth/sessions").status_code == 200
        current = client.get("/api/auth/sessions").json()
        assert len(current) == 1 and current[0]["current"]
        assert client.delete(f"/api/auth/sessions/{current[0]['id']}").status_code == 204
        assert COOKIE_NAME not in client.cookies
        assert client.get("/api/auth/sessions").status_code == 401


def test_activity_throttled_and_not_recorded_for_rejected_requests(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    with client.app.state.factory.begin() as session:
        record = session.scalar(select(AuthSession))
        created = record.created_at
        record.last_seen_at = created - 120
        original = record.last_seen_at
    assert (
        client.delete("/api/auth/sessions/others", headers={"X-CSRF-Token": ""}).status_code == 403
    )
    with client.app.state.factory() as session:
        assert session.scalar(select(AuthSession)).last_seen_at == original
    assert client.get("/api/auth/session", headers={"User-Agent": UA}).status_code == 200
    with client.app.state.factory() as session:
        record = session.scalar(select(AuthSession))
        assert record.last_seen_at > original
        assert record.created_at == created
        assert record.user_agent == UA
        seen = record.last_seen_at
    client.get("/api/auth/session", headers={"User-Agent": "Different"})
    with client.app.state.factory() as session:
        record = session.scalar(select(AuthSession))
        assert record.last_seen_at == seen
        assert record.user_agent == UA


def test_activity_never_waits_for_a_busy_application_lock(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    with client.app.state.factory.begin() as session:
        session.scalar(select(AuthSession)).last_seen_at = None
    with client.app.state.fleet.lock:
        assert client.get("/api/auth/session").status_code == 200
    with client.app.state.factory() as session:
        assert session.scalar(select(AuthSession)).last_seen_at is None
    client.get("/api/auth/session")
    with client.app.state.factory() as session:
        assert session.scalar(select(AuthSession)).last_seen_at is not None


@pytest.mark.parametrize("trusted", [False, True])
def test_cloudflare_headers_require_explicit_trust(auth_client, tmp_path, trusted):
    client = auth_client
    client.app.state.settings.trust_cloudflare_headers = trusted
    client.headers.update(
        {
            "cf-connecting-ip": "2001:db8::1",
            "cf-ipcountry": "DE",
            "cf-ipcity": "M%C3%BCnchen",
            "cf-region": "Bavaria",
            "X-Forwarded-For": "198.51.100.9",
        }
    )
    setup_admin(client, tmp_path)
    row = client.get("/api/auth/sessions").json()[0]
    assert row["ip_address"] == ("2001:db8::1" if trusted else None)
    assert row["location"] == ("München, Bavaria, DE" if trusted else None)


def test_invalid_forwarded_address_does_not_supply_location(auth_client, tmp_path):
    client = auth_client
    client.app.state.settings.trust_cloudflare_headers = True
    client.headers.update({"cf-connecting-ip": "not an IP", "cf-ipcountry": "DE"})
    setup_admin(client, tmp_path)
    row = client.get("/api/auth/sessions").json()[0]
    assert row["ip_address"] is None and row["location"] is None


def test_expired_sessions_hidden_and_legacy_details_populate(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    with closing(other_login(client)) as other:
        with client.app.state.factory.begin() as session:
            session.get(AuthSession, token_hash(other.cookies[COOKIE_NAME])).expires_at = (
                time.time() - 1
            )
            session.get(AuthSession, token_hash(client.cookies[COOKIE_NAME])).last_seen_at = None
        assert other.get("/api/auth/sessions").status_code == 401
        assert len(client.get("/api/auth/sessions").json()) == 1
        assert client.get("/api/auth/sessions").json()[0]["last_seen_at"] is not None


@pytest.mark.parametrize(
    "ua, device, os_name, browser",
    [
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Mobile/15E148 Safari/604.1",
            "iPhone",
            "iOS 18.0",
            "Safari 18.0",
        ),
        (
            "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) CriOS/140.0 Mobile/15E148 Safari/604.1",
            "iPad",
            "iPadOS 18.0",
            "Chrome 140.0",
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0) Chrome/140.0 Safari/537.36 Edg/140.1",
            "PC",
            "Windows",
            "Edge 140.1",
        ),
        (None, "Unknown device", "Unknown OS", "Unknown browser"),
    ],
)
def test_device_labels(ua, device, os_name, browser):
    assert client_description(ua) == {"device": device, "os": os_name, "browser": browser}


def test_migration_keeps_existing_session_credentials(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "b83e5a710d24")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role_ids, disabled, created_at) VALUES ('u', 'user', 'test', '[]', 0, 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO auth_sessions (token_hash, user_id, csrf_token, created_at, expires_at) VALUES ('hash', 'u', 'csrf', 1, 9999999999)"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM auth_sessions")).mappings().one()
        assert row["token_hash"] == "hash" and row["csrf_token"] == "csrf"
        assert row["created_at"] == 1 and row["last_seen_at"] is None
        assert row["id"] and row["id"] != "hash"
    command.downgrade(config, "b83e5a710d24")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT token_hash FROM auth_sessions")) == "hash"
    engine.dispose()
