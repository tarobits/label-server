"""Security boundaries and deterministic scheduling regressions from the audits."""

import asyncio
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

import anyio
import httpx
import pytest
from app_client import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from test_access_security import accounts as accounts
from test_auth import PASSWORD, change, setup_admin
from test_auth import auth_client as auth_client
from test_companion_station import local_station, unlock

from app import auth_api
from app.billing_models import BillingAccount, BillingGrant
from app.http_security import HttpSecurity
from app.models import Role, StoredAsset, User
from app.template_previews import TemplatePreviews
from companion.config import Settings
from companion.journal import Journal
from companion.web import create_app


@pytest.mark.parametrize("path,limit", [("/api/preview", 8), ("/api/csv/parse", 16)])
def test_body_budget_counts_chunks_before_calling_application(path, limit):
    called = []

    async def endpoint(scope, receive, send):
        called.append((await receive())["body"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def exercise(size):
        messages = iter(
            [
                {"type": "http.request", "body": b"x" * (size - 1), "more_body": True},
                {"type": "http.request", "body": b"x", "more_body": False},
            ]
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        middleware = HttpSecurity(endpoint, json_limit=8, bulk_limit=16)
        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": [(b"content-length", b"1")],
            },
            receive,
            send,
        )
        return sent[0]["status"]

    assert anyio.run(exercise, limit + 1) == 413
    assert not called
    assert anyio.run(exercise, limit) == 200
    assert called == [b"x" * limit]


@pytest.mark.parametrize(
    "path",
    ["/api/preview", "/api/image-jobs/preview", "/api/requests", "/api/batches/one/review"],
)
def test_render_admission_does_not_queue_workers_and_releases_slot(path):
    async def exercise():
        entered, resume = anyio.Event(), anyio.Event()

        async def endpoint(scope, receive, send):
            entered.set()
            await resume.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = HttpSecurity(endpoint, expensive_limit=1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            pending = asyncio.create_task(client.post(path, json={}))
            await entered.wait()
            busy = await client.post(path, json={})
            assert busy.status_code == 503
            assert busy.headers["retry-after"] == "1"
            resume.set()
            assert (await pending).status_code == 200
            assert (await client.post(path, json={})).status_code == 200

    anyio.run(exercise)


@pytest.mark.parametrize("changed", ["password", "disabled"])
def test_login_verification_releases_lock_and_rechecks_account(
    auth_client, tmp_path, monkeypatch, changed
):
    setup_admin(auth_client, tmp_path)

    def verify(password, encoded):
        lock = auth_client.app.state.fleet.lock
        assert lock.acquire(blocking=False)
        try:
            with auth_client.app.state.factory.begin() as session:
                user = session.scalar(select(User).where(User.username == "admin"))
                assert user is not None
                if changed == "password":
                    user.password_hash = "reset-while-verifying"
                else:
                    user.disabled = True
        finally:
            lock.release()
        return True

    monkeypatch.setattr(auth_api, "verify_password", verify)
    response = auth_client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 401


def test_role_deletion_removes_billing_grants(auth_client, tmp_path):
    setup_admin(auth_client, tmp_path)
    role = change(auth_client, "roles", "POST", {"name": "Billing team", "permissions": []}).json()
    with auth_client.app.state.factory.begin() as session:
        session.add(BillingAccount(id="audit-account", name="Audit"))
        session.flush()
        session.add(
            BillingGrant(
                account_id="audit-account",
                principal_kind="role",
                principal_id=role["id"],
                permission="billing.view",
                effect="allow",
            )
        )
    change(auth_client, "roles", "DELETE", identifier=role["id"])
    with auth_client.app.state.factory() as session:
        assert session.get(Role, role["id"]) is None
        assert (
            session.scalar(select(BillingGrant).where(BillingGrant.principal_id == role["id"]))
            is None
        )


@pytest.mark.parametrize("kind", ["image", "font"])
def test_group_with_asset_ownership_cannot_be_deleted(auth_client, tmp_path, kind):
    setup_admin(auth_client, tmp_path)
    group = change(auth_client, "groups", "POST", {"name": "Asset team"}).json()
    with auth_client.app.state.factory.begin() as session:
        session.add(
            StoredAsset(
                kind=kind,
                id="a" * 64,
                checksum="b" * 64,
                content=b"fixture",
                details={"group_id": group["id"]},
            )
        )
    response = auth_client.post(
        "/api/admin/access-preview",
        json={"resource": "groups", "method": "DELETE", "identifier": group["id"]},
    )
    assert response.status_code == 409
    assert "images and fonts" in response.json()["detail"]


def test_preview_instances_coordinate_publication_and_purge(tmp_path):
    first, other = TemplatePreviews(tmp_path), TemplatePreviews(tmp_path / ".")
    assert first.lock is other.lock
    started, finished = Event(), Event()

    def purge():
        started.set()
        other.invalidate("template")
        finished.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with first.lock:
            future = executor.submit(purge)
            assert started.wait(1)
            assert not finished.wait(0.05)
            (tmp_path / f"{first.prefix('template')}-render.webp").write_bytes(b"derived")
        future.result(timeout=1)
    assert not list(tmp_path.glob("*.webp"))


def test_journal_readers_do_not_reserve_the_write_lock(tmp_path):
    journal = Journal(tmp_path / "journal.db")
    with journal.transaction() as writer:
        writer.execute("INSERT INTO blocked_printers VALUES ('pending')")
        # BEGIN IMMEDIATE in the old read path blocked behind this writer.
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(journal.blocked, "pending").result(timeout=1) is False
    assert journal.blocked("pending") is True
    with journal.transaction(readonly=True) as reader:
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("DELETE FROM blocked_printers")


def test_shutdown_deadline_forces_exit_before_releasing_ownership(monkeypatch):
    from companion import shutdown

    class Stuck(Thread):
        def join(self, timeout=None):
            assert timeout is not None
            assert 0 <= timeout <= 0.02

        def is_alive(self):
            return True

    class ForcedExit(BaseException):
        pass

    def exit_process(code):
        assert code == 1
        raise ForcedExit()

    monkeypatch.setattr(shutdown.os, "_exit", exit_process)
    with pytest.raises(ForcedExit):
        shutdown.join_workers([Stuck()], time.monotonic() + 0.01)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "https://example.com/path",
        "https://example.com;script-src *",
        "https://user:pass@example.com",
        "https://@example.com",
        'https://example.com"',
        "https://example.com:99999",
    ],
)
def test_frame_origins_reject_patterns_and_injection(origin):
    with pytest.raises(ValidationError):
        Settings(
            server_url="http://testserver", api_key=SecretStr("fixture"), frame_ancestors=[origin]
        )


def test_companion_embedding_defaults_and_configured_origin(accounts, tmp_path):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        response = client.get("/api/health")
        assert response.headers["content-security-policy"] == "frame-ancestors 'self'"
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
    settings.frame_ancestors = ["http://dashboard.example.internal"]
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        response = client.get("/api/health")
        assert (
            response.headers["content-security-policy"]
            == "frame-ancestors 'self' http://dashboard.example.internal"
        )
        assert "x-frame-options" not in response.headers


@pytest.mark.parametrize("failure", [False, True])
def test_stale_dashboard_cannot_change_new_session(accounts, tmp_path, monkeypatch, failure):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    app = create_app(settings, agent, start_agent=False)
    with TestClient(app) as client:
        unlock(client)
        old = app.state.station.remote_token
        original = agent.request

        def delayed(method, path, **kwargs):
            if path == "/api/companion/operator":
                with app.state.station.lock:
                    app.state.station.clear()
                    app.state.station.remote_token = "new-session"
                    app.state.station.operator = {"id": "new-operator"}
                if failure:
                    raise httpx.ConnectError("offline")
                return httpx.Response(200, json={"id": "old-operator"})
            return original(method, path, **kwargs)

        monkeypatch.setattr(agent, "request", delayed)
        response = client.get("/api/station")
        assert response.status_code == 200
        assert app.state.station.remote_token == "new-session"
        assert app.state.station.operator == {"id": "new-operator"}
        assert old != app.state.station.remote_token


def test_lock_during_pending_unlock_revokes_late_remote_session(accounts, tmp_path, monkeypatch):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    app = create_app(settings, agent, start_agent=False)
    with TestClient(app) as client:
        csrf = client.get("/api/station").json()["csrf_token"]
        client.headers["X-CSRF-Token"] = csrf
        original = agent.request
        remote = []

        def delayed(method, path, **kwargs):
            result = original(method, path, **kwargs)
            if path == "/api/companion/unlock":
                remote.append(result.json()["session_token"])
                assert client.post("/api/station/lock").status_code == 200
            return result

        monkeypatch.setattr(agent, "request", delayed)
        response = client.post(
            "/api/station/unlock", json={"user_id": "administrator", "pin": "246810"}
        )
        assert response.status_code == 409
        assert not app.state.station.remote_token
        from app.auth import token_hash
        from app.models import CompanionSession

        with admin.app.state.factory() as session:
            assert session.get(CompanionSession, token_hash(remote[0])) is None


def test_session_revocation_survives_offline_journal_reopen(accounts, tmp_path, monkeypatch):
    from app.auth import token_hash
    from app.models import CompanionSession

    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    app = create_app(settings, agent, start_agent=False)
    with TestClient(app) as client:
        unlock(client)
        token = app.state.station.remote_token
        original = agent.request

        def offline(*args, **kwargs):
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(agent, "request", offline)
        assert client.post("/api/station/lock").status_code == 200
        assert not app.state.station.remote_token
        agent.journal = Journal(settings.data_dir / "journal.db")
        assert agent.journal.pending_revocations() == [token]
        monkeypatch.setattr(agent, "request", original)
        agent.flush_revocations()
        assert not agent.journal.pending_revocations()
        with admin.app.state.factory() as session:
            assert session.get(CompanionSession, token_hash(token)) is None


def test_companion_embedding_env_and_cookie_policy(accounts, tmp_path, monkeypatch):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    monkeypatch.setenv("LABEL_COMPANION_FRAME_ANCESTORS", '["http://dashboard.example.internal"]')
    configured = Settings(
        server_url=settings.server_url,
        api_key=settings.api_key,
        public_url="https://station.example.com",
    )
    assert configured.frame_ancestors == ["http://dashboard.example.internal"]
    settings.frame_ancestors = configured.frame_ancestors
    settings.public_url = configured.public_url
    with TestClient(
        create_app(settings, agent, start_agent=False), base_url=settings.public_url
    ) as client:
        csrf = client.get("/api/station").json()["csrf_token"]
        client.headers["X-CSRF-Token"] = csrf
        response = client.post(
            "/api/station/unlock", json={"user_id": "administrator", "pin": "246810"}
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "samesite=none" in cookie and "secure" in cookie and "httponly" in cookie
        # Allowing a parent to frame the UI does not authorize cross-origin API writes.
        response = client.post(
            "/api/station/lock", headers={"Origin": "http://dashboard.example.internal"}
        )
        assert response.status_code == 403


@pytest.mark.parametrize("value", [None, "", "[]"])
def test_empty_embedding_configuration_is_same_origin_only(monkeypatch, value):
    monkeypatch.delenv("LABEL_COMPANION_FRAME_ANCESTORS", raising=False)
    if value is not None:
        monkeypatch.setenv("LABEL_COMPANION_FRAME_ANCESTORS", value)
    settings = Settings(server_url="http://testserver", api_key=SecretStr("fixture"))
    assert settings.frame_ancestors == []


def test_companion_cannot_revoke_another_installations_session(accounts):
    from test_companion_auth import station

    admin, _, _ = accounts
    _, first, _ = station(admin, bound="alice")
    _, other, _ = station(admin, bound="alice")
    result = admin.post("/api/companion/unlock", headers=first, json={"user_id": "alice"})
    assert result.status_code == 200
    token = result.json()["session_token"]
    assert (
        admin.post(
            "/api/companion/sessions/revoke", headers={**other, "X-Companion-Session": token}
        ).status_code
        == 403
    )
    headers = {**first, "X-Companion-Session": token}
    assert admin.get("/api/companion/operator", headers=headers).status_code == 200
    assert admin.post("/api/companion/sessions/revoke", headers=headers).status_code == 200
    assert admin.post("/api/companion/sessions/revoke", headers=headers).status_code == 200


@pytest.mark.parametrize("failure", ["error", "cancel"])
def test_expensive_slot_is_released_after_failure(failure):
    async def exercise():
        called = False

        async def endpoint(scope, receive, send):
            nonlocal called
            if not called:
                called = True
                if failure == "cancel":
                    raise asyncio.CancelledError()
                raise ValueError("render failed")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = HttpSecurity(endpoint, expensive_limit=1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
                await client.post("/api/preview", json={})
            assert (await client.post("/api/preview", json={})).status_code == 200

    anyio.run(exercise)


def test_incomplete_body_does_not_monopolize_render_slot():
    async def exercise():
        waiting, finish_body = anyio.Event(), anyio.Event()

        async def endpoint(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def slow_body():
            yield b"{"
            waiting.set()
            await finish_body.wait()
            yield b"}"

        app = HttpSecurity(endpoint, expensive_limit=1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            pending = asyncio.create_task(client.post("/api/preview", content=slow_body()))
            await waiting.wait()
            assert (await client.post("/api/preview", json={})).status_code == 200
            finish_body.set()
            assert (await pending).status_code == 200

    anyio.run(exercise)


def test_fencing_failure_before_hardware_preserves_review_without_printing(client):
    from conftest import install, job, profile
    from sqlalchemy import event

    tape = profile(client, threshold=1)
    install(client, tape["id"])
    job(client, tape["id"])
    worker = client.app.state.fleet.workers["main"]
    engine = client.app.state.factory.kw["bind"]

    def lost_owner(conn, cursor, statement, parameters, context, many):
        if statement == "SELECT 1":
            raise RuntimeError("Database ownership was lost")

    event.listen(engine, "before_cursor_execute", lost_owner)
    try:
        worker.tick()
    finally:
        event.remove(engine, "before_cursor_execute", lost_owner)
    assert not worker.backend.batches
    batch = client.get("/api/batches").json()[0]
    assert batch["state"] == "needs_review"
    worker.tick()
    assert not worker.backend.batches
