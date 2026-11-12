"""Request scheduling regressions; subprocess deadlines contain deadlocked workers."""

import asyncio
import os
import subprocess
import sys
from threading import Event, Lock, get_ident

import anyio
import httpx
import pytest
from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import ResponseValidationError
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access
from app.auth import token_hash
from app.http import db
from app.models import Companion, Location, TapeProfile
from app.transaction_routes import TransactionRouter


def test_delayed_authorization_leaves_health_responsive(client, monkeypatch):
    entered, resume = Event(), Event()
    original = access.authorize_current_request
    authorization_threads = []

    def slow_authorization(request):
        if request.url.path == "/api/tape-profiles" and not entered.is_set():
            authorization_threads.append(get_ident())
            entered.set()
            assert resume.wait(2), "Authorization blocked the event loop"
        return original(request)

    monkeypatch.setattr(access, "authorize_current_request", slow_authorization)

    async def exercise():
        loop_thread = get_ident()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as browser:
            pending = asyncio.create_task(browser.get("/api/tape-profiles"))
            try:
                with anyio.fail_after(1):
                    while not entered.is_set():
                        await anyio.sleep(0.001)
                    assert authorization_threads != [loop_thread]
                    assert (await browser.get("/api/health")).status_code == 200
            finally:
                resume.set()
            assert (await pending).status_code == 200

    anyio.run(exercise)


@pytest.mark.parametrize("kind", ["api", "device", "mixed"])
def test_mutations_complete_with_one_worker(client, request, kind):
    if os.environ.get("LABEL_CONCURRENCY_TEST_CHILD") != "1":
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                request.node.nodeid,
                "-q",
                "--tb=short",
                "--log-disable=app.auth",
            ],
            env={**os.environ, "LABEL_CONCURRENCY_TEST_CHILD": "1"},
            capture_output=True,
            text=True,
            timeout=25,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return

    with client.app.state.factory.begin() as session:
        session.add(Location(id="concurrency-location", name="Concurrency test"))
        session.flush()
        session.add(
            Companion(
                id="concurrency-station",
                name="Concurrency test",
                location_id="concurrency-location",
                key_hash=token_hash("concurrency-test-key"),
            )
        )

    async def exercise():
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 1
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
            ) as browser:

                async def mutate(index):
                    if kind == "device" or kind == "mixed" and index % 2:
                        result = await browser.get(
                            "/api/companion/work",
                            headers={"Authorization": "Bearer concurrency-test-key"},
                        )
                        assert result.status_code == 200, result.text
                    else:
                        result = await browser.post(
                            "/api/tape-profiles", json={"name": f"Tape {index}", "width_mm": 24}
                        )
                        assert result.status_code == 201, result.text

                await asyncio.gather(*(mutate(index) for index in range(8)))
                assert (await browser.get("/api/health")).status_code == 200
        finally:
            limiter.total_tokens = previous

    anyio.run(exercise)
    assert client.app.state.fleet.lock.acquire(blocking=False)
    client.app.state.fleet.lock.release()


@pytest.mark.parametrize("invalid_response", [False, True])
def test_endpoint_error_rolls_back_and_releases_held_locks(client, invalid_response):
    router = TransactionRouter()
    hardware = Lock()
    committed = []

    @router.post("/api/transaction-failure-test", response_model=dict[str, int])
    def fail(request: Request, session: Session = Depends(db, scope="function")):
        assert hardware.acquire(blocking=False)
        request.state.held_locks.append(hardware)
        request.state.after_commit.append(lambda: committed.append(True))
        session.add(TapeProfile(name="Rolled back", width_mm=24))
        session.flush()
        if invalid_response:
            return {"value": "not an integer"}
        raise HTTPException(409, "Test rollback")

    client.app.include_router(router)
    if invalid_response:
        with pytest.raises(ResponseValidationError):
            client.post("/api/transaction-failure-test")
    else:
        assert client.post("/api/transaction-failure-test").status_code == 409
    assert not committed
    with client.app.state.factory() as session:
        assert session.scalar(select(TapeProfile).where(TapeProfile.name == "Rolled back")) is None
    assert hardware.acquire(blocking=False)
    hardware.release()
    assert client.app.state.fleet.lock.acquire(blocking=False)
    client.app.state.fleet.lock.release()


def test_authorization_is_rechecked_under_mutation_lock(client, monkeypatch):
    original = access.authorize_current_request

    def revoked(request):
        if request.url.path == "/api/tape-profiles" and request.app.state.fleet.lock.locked():
            raise HTTPException(403, "Access was revoked")
        return original(request)

    monkeypatch.setattr(access, "authorize_current_request", revoked)
    response = client.post("/api/tape-profiles", json={"name": "Denied", "width_mm": 24})
    assert response.status_code == 403
    with client.app.state.factory() as session:
        assert session.scalar(select(TapeProfile).where(TapeProfile.name == "Denied")) is None


def test_cancelled_request_does_not_strand_an_executing_transaction(client):
    router = TransactionRouter()
    entered, resume, committed = Event(), Event(), Event()

    @router.post("/api/transaction-cancellation-test")
    def create(request: Request, session: Session = Depends(db, scope="function")):
        session.add(TapeProfile(name="Completed transaction", width_mm=24))
        session.flush()
        request.state.after_commit.append(committed.set)
        entered.set()
        assert resume.wait(2), "Test did not resume the endpoint"
        return {"ok": True}

    client.app.include_router(router)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as browser:
            pending = asyncio.create_task(browser.post("/api/transaction-cancellation-test"))
            try:
                with anyio.fail_after(1):
                    while not entered.is_set():
                        await anyio.sleep(0.001)
                pending.cancel()
                resume.set()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            finally:
                resume.set()
            # Cancellation cannot stop a running synchronous mutation midway.
            # Its worker must finish commit/cleanup even without a response reader.
            with anyio.fail_after(2):
                while not committed.is_set() or client.app.state.fleet.lock.locked():
                    await anyio.sleep(0.001)
            assert (await browser.get("/api/health")).status_code == 200

    anyio.run(exercise)
    with client.app.state.factory() as session:
        assert (
            session.scalar(select(TapeProfile).where(TapeProfile.name == "Completed transaction"))
            is not None
        )


def test_database_transactions_are_not_fastapi_yield_dependencies(client):
    def check(dependant):
        assert not getattr(dependant.call, "__request_transaction__", False)
        for child in dependant.dependencies:
            check(child)

    def check_routes(routes):
        count = 0
        for route in routes:
            if isinstance(route, APIRoute):
                check(route.dependant)
                count += 1
            elif router := getattr(route, "original_router", None):
                count += check_routes(router.routes)
        return count

    assert check_routes(client.app.routes) > 100
    schema = client.get("/openapi.json").json()
    assert "transaction_request" not in str(schema)
