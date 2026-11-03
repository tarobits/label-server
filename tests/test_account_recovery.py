"""Email possession, reset lifetimes, replay protection, and existing session boundaries."""

import re
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_auth import PASSWORD, login, setup_admin
from test_auth import auth_client as auth_client_fixture

from app.auth import token_hash
from app.models import AuthSession, RecoveryToken, User

auth_client = auth_client_fixture


@pytest.fixture
def mailbox(auth_client, monkeypatch):
    settings = auth_client.app.state.settings
    settings.smtp_host = "smtp.example.invalid"
    settings.smtp_from = "labels@example.invalid"
    settings.public_url = "https://labels.example.invalid"
    auth_client.base_url = "https://testserver"
    messages = []
    monkeypatch.setattr(
        "app.recovery_api.send_email",
        lambda settings, to, subject, body: messages.append((to, subject, body)),
    )
    return messages


def email_token(mailbox):
    return re.search(r"token=([A-Za-z0-9_-]+)", mailbox[-1][2]).group(1)


def verify_address(client, mailbox, address="admin@example.invalid"):
    response = client.put("/api/auth/email", json={"email": address, "current_password": PASSWORD})
    assert response.status_code == 202, response.text
    token = email_token(mailbox)
    response = client.post("/api/auth/email/verify", json={"token": token})
    assert response.status_code == 204, response.text
    return token


def reset_link(client, mailbox):
    response = client.post("/api/auth/password/forgot", json={"username": "ADMIN"})
    assert response.status_code == 202, response.text
    return email_token(mailbox)


def test_email_requires_password_csrf_origin_and_proof_of_possession(
    auth_client, tmp_path, mailbox
):
    client = auth_client
    assert client.get("/api/auth/email").status_code == 401
    user_id = setup_admin(client, tmp_path)["user"]["id"]
    body = {"email": "Admin@Example.Invalid", "current_password": PASSWORD}
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.put("/api/auth/email", json=body).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert (
        client.put(
            "/api/auth/email", json=body, headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.put("/api/auth/email", json={**body, "current_password": "incorrect"}).status_code
        == 400
    )
    assert mailbox == []
    response = client.put("/api/auth/email", json=body)
    assert response.status_code == 202
    token = email_token(mailbox)
    assert token not in response.text
    assert mailbox[-1][0] == "admin@example.invalid"
    assert "https://labels.example.invalid/#/verify-email?token=" in mailbox[-1][2]
    profile = client.get("/api/auth/email").json()
    assert profile["email"] is None and profile["pending_email"] == "admin@example.invalid"
    with client.app.state.factory() as session:
        stored = session.scalar(select(RecoveryToken))
        assert stored.token_hash == token_hash(token) and stored.token_hash != token
        assert stored.user_id == user_id
        assert session.get(User, user_id).email is None
    assert (
        client.post(
            "/api/auth/password/reset", json={"token": token, "new_password": PASSWORD}
        ).status_code
        == 400
    )
    assert client.post("/api/auth/email/verify", json={"token": token}).status_code == 204
    assert client.post("/api/auth/email/verify", json={"token": token}).status_code == 400
    assert client.get("/api/auth/email").json()["email"] == "admin@example.invalid"


def test_reset_generic_requests_and_atomic_single_use_revoke_sessions(
    auth_client, tmp_path, mailbox
):
    client = auth_client
    user_id = setup_admin(client, tmp_path)["user"]["id"]
    verify_address(client, mailbox)
    other = TestClient(client.app, base_url="https://testserver")
    login(other)
    unknown = client.post("/api/auth/password/forgot", json={"username": "nobody"})
    before = len(mailbox)
    known = client.post("/api/auth/password/forgot", json={"username": "admin"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(mailbox) == before + 1
    token = email_token(mailbox)
    second = reset_link(client, mailbox)
    replacement = "a replacement account password"
    body = {"token": token, "new_password": replacement}
    invalid = client.post("/api/auth/password/reset", json={**body, "new_password": "short"})
    assert invalid.status_code == 422
    assert token not in invalid.text and '"input"' not in invalid.text
    assert (
        client.post(
            "/api/auth/password/reset", json=body, headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(
            executor.map(
                lambda _: (
                    TestClient(client.app).post("/api/auth/password/reset", json=body).status_code
                ),
                range(2),
            )
        )
    assert sorted(statuses) == [204, 400]
    assert client.get("/api/auth/session").json()["user"] is None
    assert other.get("/api/auth/session").json()["user"] is None
    assert (
        client.post("/api/auth/password/reset", json={**body, "token": second}).status_code == 400
    )
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code
        == 401
    )
    login(client, password=replacement)
    assert "all sessions were signed out" in mailbox[-1][2]
    assert replacement not in mailbox[-1][2]
    with client.app.state.factory() as session:
        assert session.scalar(select(RecoveryToken)) is None
        assert (
            len(list(session.scalars(select(AuthSession).where(AuthSession.user_id == user_id))))
            == 1
        )
    other.close()


@pytest.mark.parametrize("invalidate", ["expire", "disable", "password", "email", "remove"])
def test_invalidated_recovery_links_cannot_reset_password(
    auth_client, tmp_path, mailbox, invalidate
):
    client = auth_client
    user_id = setup_admin(client, tmp_path)["user"]["id"]
    verify_address(client, mailbox)
    token = reset_link(client, mailbox)
    with client.app.state.factory.begin() as session:
        user = session.get(User, user_id)
        if invalidate == "expire":
            session.get(RecoveryToken, token_hash(token)).expires_at = time.time() - 1
        elif invalidate == "disable":
            user.disabled = True
        elif invalidate == "password":
            user.password_hash = "changed-by-administrator"
        elif invalidate == "email":
            user.email = "replacement@example.invalid"
        else:
            user.email = None
    response = client.post(
        "/api/auth/password/reset", json={"token": token, "new_password": "a replacement password"}
    )
    assert response.status_code == 400
    assert token not in response.text


def test_failed_mail_is_generic_and_never_logs_credentials(
    auth_client, tmp_path, mailbox, monkeypatch, caplog
):
    client = auth_client
    setup_admin(client, tmp_path)
    verify_address(client, mailbox)

    def fail(*args):
        raise OSError("private-smtp-secret")

    monkeypatch.setattr("app.recovery_api.send_email", fail)
    response = client.post("/api/auth/password/forgot", json={"username": "admin"})
    assert response.status_code == 202
    assert "private-smtp-secret" not in caplog.text + response.text
    assert "Account email delivery failed" in caplog.text


def test_forgot_password_throttles_without_consuming_login_attempts(auth_client, tmp_path, mailbox):
    client = auth_client
    setup_admin(client, tmp_path)
    for _ in range(10):
        assert (
            client.post("/api/auth/password/forgot", json={"username": "admin"}).status_code == 202
        )
    assert client.post("/api/auth/password/forgot", json={"username": "ADMIN"}).status_code == 429
    login(client)
    assert mailbox == []


def test_replacing_and_removing_email_invalidates_recovery_links(auth_client, tmp_path, mailbox):
    client = auth_client
    setup_admin(client, tmp_path)
    verify_address(client, mailbox)
    reset = reset_link(client, mailbox)
    client.put(
        "/api/auth/email", json={"email": "other@example.invalid", "current_password": PASSWORD}
    )
    verification = email_token(mailbox)
    assert client.get("/api/auth/email").json()["email"] == "admin@example.invalid"
    assert (
        client.put(
            "/api/auth/email", json={"email": None, "current_password": PASSWORD}
        ).status_code
        == 202
    )
    assert client.get("/api/auth/email").json()["email"] is None
    assert client.post("/api/auth/email/verify", json={"token": verification}).status_code == 400
    assert (
        client.post(
            "/api/auth/password/reset", json={"token": reset, "new_password": PASSWORD}
        ).status_code
        == 400
    )
