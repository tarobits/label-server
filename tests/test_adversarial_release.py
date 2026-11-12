"""Adversarial release probes. Failures remain failures; no implementation patches.

All databases, credentials and printers are isolated test fixtures. Barriers force
interleavings; bounded waits and finally blocks release every test worker.
"""

import asyncio
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import anyio
import httpx
import pytest
from app_client import TestClient
from fastapi import Depends, FastAPI, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access_security import accounts as accounts
from test_auth import auth_client as auth_client
from test_auth import change, setup_admin
from test_companion_station import local_station, unlock
from test_profile_availability import availability
from test_runs import run_body

from app.authn.auth import token_hash
from app.http import db
from app.http_security import HttpSecurity
from app.models import CompanionSession, StoredAsset, TapeProfile, UserGroup
from app.printing import submissions  # noqa: F401
from app.transaction_routes import TransactionRouter
from companion.journal import Journal
from companion.web import create_app


def test_cancelled_request_keeps_capacity_reserved_until_sync_worker_exits():
    """Cancel the ASGI task while actual synchronous work is still executing.

    This models server/task cancellation, not merely a client closing its socket:
    Uvicorn does not necessarily cancel an executing task on socket disconnect.
    """
    entered, release, exited = Event(), Event(), Event()
    guard = Lock()
    counts = {"calls": 0, "active": 0, "peak": 0}
    api = FastAPI()

    @api.post("/api/preview")
    def render():
        with guard:
            counts["calls"] += 1
            first = counts["calls"] == 1
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        try:
            if first:
                entered.set()
                assert release.wait(5), "Probe failed to release the sync worker"
            return {"ok": True}
        finally:
            with guard:
                counts["active"] -= 1
            if first:
                exited.set()

    api.add_middleware(HttpSecurity, expensive_limit=1)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url="http://test"
        ) as browser:
            first = asyncio.create_task(browser.post("/api/preview", json={}))
            try:
                with anyio.fail_after(2):
                    while not entered.is_set():
                        await anyio.sleep(0.001)
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
                assert not exited.is_set(), "The worker must still be running at the probe"
                second = await browser.post("/api/preview", json={})
            finally:
                release.set()
                with anyio.fail_after(2):
                    while not exited.is_set():
                        await anyio.sleep(0.001)
            assert second.status_code == 503, (
                f"limit=1; cancelled worker still active; next response={second.status_code}; "
                f"peak concurrent workers={counts['peak']}"
            )
            assert counts["peak"] == 1
            assert (await browser.post("/api/preview", json={})).status_code == 200

    anyio.run(exercise)


def test_real_preview_route_cancellation_cannot_exceed_two_render_workers(client, monkeypatch):
    """Repeat the cancellation probe through the real route and middleware stack."""
    from app import api

    assert client.app.state.settings.expensive_request_limit == 2
    body = {"template_id": "text", "data": {"text": "Capacity probe"}}
    baseline = client.post("/api/preview", json=body)
    assert baseline.status_code == 200, baseline.text
    guard, release = Lock(), Event()
    counts = {"calls": 0, "active": 0, "peak": 0}
    original = api.render_document

    def blocked(*args, **kwargs):
        with guard:
            counts["calls"] += 1
            number = counts["calls"]
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        try:
            if number <= 2:
                assert release.wait(5)
            return original(*args, **kwargs)
        finally:
            with guard:
                counts["active"] -= 1

    monkeypatch.setattr(api, "render_document", blocked)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as browser:
            pending = [
                asyncio.create_task(browser.post("/api/preview", json=body)) for _ in range(2)
            ]
            try:
                with anyio.fail_after(2):
                    while counts["active"] < 2:
                        await anyio.sleep(0.001)
                pending[0].cancel()
                # The complete stack may shield cancellation until its worker exits.
                # Do not wait for that exit before probing admission; keep both
                # workers blocked while allowing cancellation cleanup to run.
                await anyio.sleep(0.02)
                assert counts["active"] == 2
                with anyio.fail_after(2):
                    response = await browser.post("/api/preview", json=body)
            finally:
                release.set()
                await asyncio.gather(*pending, return_exceptions=True)
                with anyio.fail_after(2):
                    while counts["active"]:
                        await anyio.sleep(0.001)
            assert response.status_code == 503, (
                f"real /api/preview; limit=2; third response={response.status_code}; "
                f"peak concurrent renders={counts['peak']}"
            )
            assert counts["peak"] <= 2

    anyio.run(exercise)


@pytest.mark.parametrize(
    "headers",
    [[], [(b"content-length", b"0")], [(b"content-length", b"1"), (b"content-length", b"999999")]],
)
@pytest.mark.parametrize("path,budget", [("/api/preview", 32), ("/api/runs/prepare", 64)])
def test_fragmented_body_cannot_bypass_budget_with_false_lengths(headers, path, budget):
    """One-byte fragments exceed the budget even with misleading length headers."""
    called = []

    async def endpoint(scope, receive, send):
        called.append(True)

    async def exercise():
        sent = []
        remaining = budget + 1

        async def receive():
            nonlocal remaining
            remaining -= 1
            return {"type": "http.request", "body": b"x", "more_body": remaining > 0}

        async def send(message):
            sent.append(message)

        await HttpSecurity(endpoint, json_limit=32, bulk_limit=64)(
            {"type": "http", "method": "POST", "path": path, "headers": headers},
            receive,
            send,
        )
        assert sent[0]["status"] == 413
        assert not called, "Oversized input reached parsing/endpoint execution"

    anyio.run(exercise)


@pytest.mark.parametrize("route", ["csv", "approval_request"])
def test_retiring_profile_during_preparation_cannot_persist_new_work(client, monkeypatch, route):
    body = run_body(client)
    path = "/api/runs/prepare"
    if route == "approval_request":
        path = "/api/requests"
        body = {
            "kind": "job",
            "input": {"tape_profile": body["tape_profile"], "data": {"text": "Race"}},
        }
    profile_id = (
        body["input"]["tape_profile"] if route == "approval_request" else body["tape_profile"]
    )
    entered, resume = Event(), Event()
    original = submissions.render_document

    def slow_render(*args, **kwargs):
        entered.set()
        assert resume.wait(5), "Preparation held its lock or the probe did not resume"
        return original(*args, **kwargs)

    monkeypatch.setattr(submissions, "render_document", slow_render)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(client.post, path, json=body)
        try:
            assert entered.wait(3), "Preparation did not reach rendering"
            pool.submit(availability, client, profile_id, False).result(timeout=3)
        finally:
            resume.set()
        response = pending.result(timeout=3)
    assert response.status_code == 409, response.text
    assert client.get("/api/jobs").json() == []
    assert client.get("/api/runs").json() == []


@pytest.mark.parametrize("kind", ["image", "font"])
def test_new_asset_invalidates_already_confirmed_group_deletion(auth_client, tmp_path, kind):
    setup_admin(auth_client, tmp_path)
    group = change(auth_client, "groups", "POST", {"name": "Late asset owner"}).json()
    reviewed = auth_client.post(
        "/api/admin/access-preview",
        json={"resource": "groups", "method": "DELETE", "identifier": group["id"]},
    )
    assert reviewed.status_code == 200, reviewed.text
    with auth_client.app.state.factory.begin() as session:
        session.add(
            StoredAsset(
                kind=kind,
                id="a" * 64,
                checksum="b" * 64,
                content=b"test-only asset",
                details={"group_id": group["id"]},
            )
        )
    result = auth_client.delete(
        f"/api/admin/groups/{group['id']}",
        headers={"X-Access-Confirmation": reviewed.json()["confirmation_token"]},
    )
    assert result.status_code == 409, result.text
    with auth_client.app.state.factory() as session:
        assert session.get(UserGroup, group["id"]) is not None


def test_unlock_responses_arriving_in_reverse_order_keep_only_latest_session(
    accounts, tmp_path, monkeypatch
):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    app = create_app(settings, agent, start_agent=False)
    entered, resume = Event(), Event()
    original = agent.request
    tokens = []

    def delayed(method, path, **kwargs):
        response = original(method, path, **kwargs)
        if path == "/api/companion/unlock":
            tokens.append(response.json()["session_token"])
            if len(tokens) == 1:
                entered.set()
                assert resume.wait(5)
        return response

    monkeypatch.setattr(agent, "request", delayed)
    with TestClient(app) as station:
        station.headers["X-CSRF-Token"] = station.get("/api/station").json()["csrf_token"]
        body = {"user_id": "administrator", "pin": "246810"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(station.post, "/api/station/unlock", json=body)
            try:
                assert entered.wait(3)
                second = pool.submit(station.post, "/api/station/unlock", json=body).result(
                    timeout=3
                )
                assert second.status_code == 200, second.text
            finally:
                resume.set()
            assert first.result(timeout=3).status_code == 409
        assert app.state.station.remote_token == tokens[1]
        with admin.app.state.factory() as session:
            assert session.get(CompanionSession, token_hash(tokens[0])) is None
            assert session.get(CompanionSession, token_hash(tokens[1])) is not None


def test_lost_revocation_acknowledgement_is_replayed_after_journal_reopen(
    accounts, tmp_path, monkeypatch
):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    app = create_app(settings, agent, start_agent=False)
    original = agent.request
    with TestClient(app) as station:
        unlock(station)
        token = app.state.station.remote_token

        def lose_ack(method, path, **kwargs):
            response = original(method, path, **kwargs)
            if path == "/api/companion/sessions/revoke":
                raise httpx.ReadError("Injected response loss after the server committed")
            return response

        monkeypatch.setattr(agent, "request", lose_ack)
        assert station.post("/api/station/lock").status_code == 200
        with admin.app.state.factory() as session:
            assert session.get(CompanionSession, token_hash(token)) is None
        agent.journal = Journal(settings.data_dir / "journal.db")
        assert agent.journal.pending_revocations() == [token]
        monkeypatch.setattr(agent, "request", original)
        agent.flush_revocations()
        assert agent.journal.pending_revocations() == []
        with admin.app.state.factory() as session:
            assert (
                session.scalar(
                    select(CompanionSession).where(CompanionSession.token_hash == token_hash(token))
                )
                is None
            )


def test_idle_station_lock_revokes_the_remote_session(accounts, tmp_path):
    """Expired local access must not leave its former remote credential usable."""
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    app = create_app(settings, agent, start_agent=False)
    with TestClient(app) as station:
        unlock(station)
        token = app.state.station.remote_token
        with app.state.station.lock:
            app.state.station.last_activity -= settings.lock_timeout_seconds + 1
        assert station.get("/api/station").json()["locked"] is True
        assert app.state.station.remote_token == ""
        response = agent.client.get(
            "/api/companion/operator",
            headers={
                "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
                "X-Companion-Session": token,
            },
        )
        assert response.status_code in (401, 403), (
            f"Locally expired session still accepted by main server: {response.status_code}; "
            f"pending revocations={len(agent.journal.pending_revocations())}"
        )


def test_baseexception_during_transaction_rolls_back_and_releases_all_locks(client):
    """Cancellation-like BaseExceptions must unwind hardware and database ownership."""
    router = TransactionRouter()
    hardware = Lock()
    callbacks = []

    class Abort(BaseException):
        pass

    @router.post("/api/adversarial-abort")
    def abort(request: Request, session: Session = Depends(db, scope="function")):
        assert hardware.acquire(blocking=False)
        request.state.held_locks.append(hardware)
        request.state.after_commit.append(lambda: callbacks.append("committed"))
        session.add(TapeProfile(id="aborted-probe", name="Must roll back", width_mm=24))
        session.flush()
        raise Abort()

    client.app.include_router(router)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as browser:
            with pytest.raises(Abort):
                await browser.post("/api/adversarial-abort", json={})
            assert (await browser.get("/api/health")).status_code == 200

    anyio.run(exercise)
    assert hardware.acquire(blocking=False), "Hardware lock leaked after BaseException"
    hardware.release()
    assert client.app.state.fleet.lock.acquire(blocking=False), "Fleet lock leaked"
    client.app.state.fleet.lock.release()
    assert not callbacks
    with client.app.state.factory() as session:
        assert session.get(TapeProfile, "aborted-probe") is None


def test_real_stuck_worker_exit_skips_ownership_cleanup():
    """Use a subprocess: os._exit must not terminate pytest or run finally cleanup."""
    source = """
import time
from threading import Event, Thread
from companion.shutdown import join_workers
worker = Thread(target=Event().wait, daemon=True)
worker.start()
try:
    join_workers([worker], time.monotonic() + 0.05)
finally:
    print('OWNERSHIP_RELEASED', flush=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "shutdown deadline exceeded" in result.stderr
    assert "OWNERSHIP_RELEASED" not in result.stdout
