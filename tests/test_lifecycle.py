import time
from pathlib import Path
from threading import Event

import pytest
from alembic import command
from alembic.config import Config
from conftest import create_test_app as create_app
from conftest import install, job, profile, seed_test_printer
from fastapi.testclient import TestClient
from mock_backend import MockPrinterBackend

from app.config import Settings


@pytest.mark.parametrize("resume", [False, True])
def test_update_validation_blocks_requests_and_external_effects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, resume: bool
) -> None:
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    queued = job(client, tape["id"])
    settings = client.app.state.settings.model_copy(update={"worker_interval_seconds": 0.02})
    marker = client.app.state.fonts.root.parent.parent / ".update-in-progress"
    client.__exit__(None, None, None)
    marker.touch()
    notifications = Event()
    monkeypatch.setattr("app.main.deliver_routed_pending", lambda *_: notifications.set())
    backend = MockPrinterBackend()
    with TestClient(create_app(settings, {"main": backend})) as validating:
        assert validating.get("/api/health").json()["healthy"]
        assert not validating.app.state.fleet.running
        assert not notifications.wait(0.3)
        for method, path in (("GET", "/api/status"), ("POST", "/api/jobs"), ("GET", "/")):
            response = validating.request(method, path)
            assert response.status_code == 503
            assert response.headers["cache-control"] == "no-store"
        assert not backend.batches
        if resume:
            marker.unlink()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if validating.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed":
                    break
                time.sleep(0.01)
            assert validating.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"
            assert notifications.wait(1)
    assert len(backend.batches) == (1 if resume else 0)
    assert notifications.is_set() is resume


def test_queue_and_silence_survive_app_restart(client: TestClient) -> None:
    tape = profile(client, threshold=1, reminders=True)
    queued = job(client, tape["id"])
    client.put(f"/api/tape-profiles/{tape['id']}/reminder", json={"action": "silence"})
    client.put("/api/printer/automatic-printing", json={"held": True})
    settings = client.app.state.settings
    # Exit the first lifespan to release its exclusive process lock.
    client.__exit__(None, None, None)
    with TestClient(create_app(settings, start_worker=False)) as restarted:
        assert restarted.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"
        assert restarted.get("/api/tape-profiles").json()[0]["reminder_silenced"]
        install(restarted, tape["id"])
        assert restarted.get("/api/status").json()["automatic_printing_held"]
        restarted.app.state.fleet.workers["main"].tick()
        assert restarted.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"
        restarted.put("/api/printer/automatic-printing", json={"held": False})
        restarted.app.state.fleet.workers["main"].tick()
        assert restarted.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"


def test_second_server_rejected(client: TestClient) -> None:
    settings = client.app.state.settings
    with pytest.raises(RuntimeError, match="Another server"):
        with TestClient(create_app(settings, start_worker=False)):
            pass


def test_background_worker_wakes_and_migrations_roundtrip(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'live.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)
    seed_test_printer(url)
    backend = MockPrinterBackend()
    settings = Settings(database_url=url, worker_interval_seconds=0.02)
    with TestClient(create_app(settings, {"main": backend})) as client:
        tape = profile(client, threshold=2)
        install(client, tape["id"])
        queued = job(client, tape["id"], 2)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if client.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed":
                break
            time.sleep(0.01)
        assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"
        assert len(backend.batches) == 1
