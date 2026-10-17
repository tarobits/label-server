"""Stop intents cross the API/worker boundary without racing physical I/O."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from conftest import install, job, profile
from mock_backend import MockPrinterBackend
from sqlalchemy import select
from test_auth import PASSWORD, change, login, permission, setup_admin
from test_auth import auth_client as auth_client

from app.models import Batch, FlushRequest, PrinterState
from app.printer.base import PrintInterrupted, PrintNotStarted


class ControlledPrinter(MockPrinterBackend):
    def __init__(self):
        super().__init__()
        self.started, self.release = Event(), Event()

    def print_batch_controlled(self, labels, control):
        if control.stop.is_set():
            raise PrintNotStarted("Stopped before transmission")
        self.started.set()
        assert self.release.wait(5)
        if control.stop.is_set():
            raise PrintInterrupted("Operator stopped printing", 1)
        return self.print_batch(labels)


def controlled(client, identifier="main"):
    fleet = client.app.state.fleet
    backend = ControlledPrinter()
    worker = fleet.workers[identifier]
    worker.backend = backend
    definition = fleet.registry.definition(identifier)
    fleet.registry.replace(
        replace(
            definition,
            capabilities=replace(
                definition.capabilities,
                supports_stop_after_current=True,
                supports_emergency_stop=True,
            ),
        ),
        backend,
    )
    return worker, backend


@pytest.mark.parametrize("mode", ["after_current", "emergency"])
def test_active_stop_holds_printer_and_keeps_uncertain_output_for_review(client, mode):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    submitted = job(client, tape["id"], 4)
    worker, backend = controlled(client)
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(worker.tick)
        try:
            assert backend.started.wait(5)
            response = client.post("/api/printers/main/stop", json={"mode": mode})
            assert response.status_code == 202, response.text
            assert worker.control.mode == mode
            status = client.get("/api/printers/status").json()[0]
            assert status["automatic_printing_held"]
            assert status["stop_requested"] == mode
        finally:
            backend.release.set()
        running.result()
    batch = client.get("/api/batches").json()[0]
    detail = client.get(f"/api/batches/{batch['id']}").json()
    assert detail["state"] == "needs_review"
    assert [item["outcome"] for item in detail["items"]] == ["printed"] + ["needs_review"] * 3
    assert detail["trigger"]["stop_request"]["mode"] == mode
    assert client.get("/api/cartridges").json()[0]["consumption_uncertain"]
    decisions = {item["copy_id"]: "queued" for item in detail["items"][1:]}
    assert (
        client.post(
            f"/api/batches/{batch['id']}/review",
            json={"decisions": decisions, "consumed_mm": 65},
        ).status_code
        == 200
    )
    worker.tick()
    assert client.get(f"/api/jobs/{submitted['id']}").json()["status"] == "queued"
    assert not backend.batches  # Saving review must not clear the operator's hold.


def test_stop_cancels_pending_manual_intent_and_cannot_downgrade_emergency(client):
    tape = profile(client)
    install(client, tape["id"])
    job(client, tape["id"], 3)
    worker, backend = controlled(client)
    assert client.post("/api/queue/print").status_code == 202
    assert client.post("/api/printers/main/stop", json={"mode": "after_current"}).status_code == 202
    with client.app.state.factory() as session:
        assert all(item.completed for item in session.scalars(select(FlushRequest)))
        assert session.scalar(select(PrinterState)).automatic_printing_held
    worker.tick()
    assert not backend.started.is_set()
    # Explicit manual printing remains possible while automatic printing is held.
    assert client.post("/api/queue/print").status_code == 202
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(worker.tick)
        try:
            assert backend.started.wait(5)
            for mode in ["after_current", "emergency", "after_current"]:
                response = client.post("/api/printers/main/stop", json={"mode": mode})
                assert response.status_code == 202
            assert worker.control.mode == "emergency"
            with client.app.state.factory() as session:
                assert session.scalar(select(Batch)).trigger["stop_request"]["mode"] == "emergency"
        finally:
            backend.release.set()
        running.result()


def test_stop_refuses_unsupported_driver_and_invalid_mode_without_holding(client):
    assert client.post("/api/printers/main/stop", json={"mode": "after_current"}).status_code == 409
    assert client.post("/api/printers/main/stop", json={"mode": "invalid"}).status_code == 422
    with client.app.state.factory() as session:
        assert not session.scalar(select(PrinterState)).automatic_printing_held


def test_stop_during_render_does_not_restore_cancelled_flush_or_retry(client, monkeypatch):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    submitted = job(client, tape["id"], 3)
    worker, backend = controlled(client)
    entered, release = Event(), Event()
    original = worker._render_reserved

    def slow_render(identifier):
        entered.set()
        assert release.wait(5)
        return original(identifier)

    monkeypatch.setattr(worker, "_render_reserved", slow_render)
    assert client.post("/api/queue/print").status_code == 202
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(worker.tick)
        try:
            assert entered.wait(5)
            assert (
                client.post("/api/printers/main/stop", json={"mode": "emergency"}).status_code
                == 202
            )
        finally:
            release.set()
        running.result()
    assert not backend.started.is_set()
    with client.app.state.factory() as session:
        assert all(item.completed for item in session.scalars(select(FlushRequest)))
    worker.tick()
    assert client.get(f"/api/jobs/{submitted['id']}").json()["status"] == "queued"
    assert not backend.batches


def test_failed_stop_transaction_never_signals_hardware(client, monkeypatch):
    from sqlalchemy.orm import Session

    tape = profile(client, threshold=1)
    install(client, tape["id"])
    job(client, tape["id"], 3)
    worker, backend = controlled(client)

    def fail_commit(self):
        raise RuntimeError("Simulated failed commit")

    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(worker.tick)
        try:
            assert backend.started.wait(5)
            with monkeypatch.context() as patch:
                patch.setattr(Session, "commit", fail_commit)
                with pytest.raises(RuntimeError, match="failed commit"):
                    client.post("/api/printers/main/stop", json={"mode": "emergency"})
            assert worker.control.mode is None
            with client.app.state.factory() as session:
                assert not session.scalar(select(PrinterState)).automatic_printing_held
                assert "stop_request" not in session.scalar(select(Batch)).trigger
        finally:
            backend.release.set()
        running.result()


def test_stopping_one_printer_does_not_block_another(client):
    from test_fleet import device, fit, submit

    tape = profile(client, threshold=1)
    install(client, tape["id"])
    job(client, tape["id"], 3)
    other = device(client)
    fit(client, other, tape)
    submitted = submit(client, other, tape)
    worker, backend = controlled(client)
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(worker.tick)
        try:
            assert backend.started.wait(5)
            assert (
                client.post("/api/printers/main/stop", json={"mode": "emergency"}).status_code
                == 202
            )
            client.app.state.fleet.workers[other].tick()
            assert client.get(f"/api/jobs/{submitted['id']}").json()["status"] == "printed"
            with client.app.state.factory() as session:
                assert not session.scalar(
                    select(PrinterState).where(PrinterState.printer_id == other)
                ).automatic_printing_held
        finally:
            backend.release.set()
        running.result()


@pytest.mark.parametrize(
    "level,mode,expected",
    [
        ("print", "after_current", 403),
        ("moderator", "after_current", 202),
        ("moderator", "emergency", 403),
        ("full", "emergency", 202),
    ],
)
def test_physical_stop_levels_are_enforced(auth_client, tmp_path, level, mode, expected):
    client = auth_client
    setup_admin(client, tmp_path)
    device = client.post("/api/printers", json={"name": "Physical"}).json()["id"]
    worker, backend = controlled(client, device)
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    job(client, tape["id"], 3)
    role = change(
        client,
        "roles",
        "POST",
        {
            "name": "Operator",
            "permissions": [permission(device, level)],
        },
    ).json()
    change(
        client,
        "users",
        "POST",
        {
            "username": "operator",
            "password": PASSWORD,
            "role_ids": [role["id"]],
        },
    )
    login(client, "operator")
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(worker.tick)
        try:
            assert backend.started.wait(5)
            response = client.post(f"/api/printers/{device}/stop", json={"mode": mode})
            assert response.status_code == expected, response.text
            with client.app.state.factory() as session:
                trigger = session.scalar(select(Batch)).trigger
                if expected == 202:
                    assert trigger["stop_request"]["actor"]["name"] == "operator"
                else:
                    assert "stop_request" not in trigger
        finally:
            backend.release.set()
        running.result()
    with client.app.state.factory() as session:
        assert session.scalar(select(PrinterState)).automatic_printing_held == (expected == 202)


def test_group_full_does_not_authorize_physical_stop(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    device = client.post("/api/printers", json={"name": "Physical"}).json()["id"]
    controlled(client, device)
    group = client.post(
        "/api/printer-groups", json={"name": "Station", "printer_ids": [device]}
    ).json()["id"]
    role = change(
        client,
        "roles",
        "POST",
        {
            "name": "Group only",
            "permissions": [permission(group, "full")],
        },
    ).json()
    change(
        client,
        "users",
        "POST",
        {
            "username": "operator",
            "password": PASSWORD,
            "role_ids": [role["id"]],
        },
    )
    login(client, "operator")
    for mode in ("after_current", "emergency"):
        assert client.post(f"/api/printers/{device}/stop", json={"mode": mode}).status_code == 403
