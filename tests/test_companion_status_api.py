import time

import pytest
from app_client import TestClient
from pydantic import SecretStr, ValidationError
from test_access_security import accounts as accounts
from test_companion_station import local_station, unlock

from companion.web import create_app

KEY = "status-test-only-credential-1234567890"
HEADERS = {"Authorization": f"Bearer {KEY}"}


def test_status_api_disabled_and_requires_its_own_bearer_key(accounts, tmp_path):
    settings, agent = local_station(accounts[0], tmp_path)
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        assert client.get("/api/status", headers=HEADERS).status_code == 404
        settings.status_api_key = SecretStr(KEY)
        for headers in (
            {},
            {"Authorization": "Basic invalid"},
            {"Authorization": "Bearer invalid"},
            {"Authorization": f"Bearer {settings.api_key.get_secret_value()}"},
        ):
            for path in ("/api/status", "/api/status/printers/usb-one"):
                result = client.get(path, headers=headers)
                assert result.status_code == 401
                assert result.headers["WWW-Authenticate"] == "Bearer"
                assert result.headers["Cache-Control"] == "no-store"
        assert client.get(f"/api/status?api_key={KEY}").status_code == 401
        assert client.get("/api/status", headers=HEADERS).status_code == 200
        # This credential neither unlocks the station nor authorizes private proxy reads.
        assert client.get("/api/station", headers=HEADERS).json()["locked"]
        assert client.get("/api/proxy/cartridges", headers=HEADERS).status_code == 401
        assert client.post("/api/status", headers=HEADERS).status_code == 405
        unlock(client)
        assert client.get("/api/status").status_code == 401


def test_status_api_allowlists_payload_and_handles_cached_or_missing_data(accounts, tmp_path):
    settings, agent = local_station(accounts[0], tmp_path)
    settings.status_api_key = SecretStr(KEY)
    settings.show_locked_dashboard_details = False
    agent.users["users"] = [{"id": "private-user", "username": "private-user"}]
    agent.statuses["usb-one"] = {
        "connected": True,
        "error": "private hardware diagnostic",
        "diagnostics": {"serial": "private serial"},
    }
    agent.dashboards["usb-one"] = {
        "held": False,
        "cartridge_check_pending": False,
        "queued_labels": 7,
        "shared_queued_labels": 3,
        "preview": "private artwork",
        "requester": "private-user",
        "active_batch": {"id": "private-batch"},
        "cartridge": {
            "name": "White tape",
            "profile_name": "Black on white",
            "foreground": "#000000",
            "background": "#ffffff",
            "width_mm": 24,
            "remaining_mm": 4900,
            "nominal_length_mm": 8000,
            "uncertain": True,
            "notes": "private notes",
            "price_minor": 123,
            "owner_id": "private-user",
        },
    }
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        result = client.get("/api/status", headers=HEADERS)
        assert result.status_code == 200
        assert "private" not in result.text
        data = result.json()
        assert set(data) == {"schema_version", "name", "online", "printers"}
        assert data["name"] == "Workshop station" and data["online"]
        printer = data["printers"][0]
        assert set(printer) == {
            "local_id",
            "name",
            "status",
            "connected",
            "printing",
            "blocked",
            "held",
            "cartridge_check_pending",
            "queued_labels",
            "shared_queued_labels",
            "cartridge",
            "snapshot_age_seconds",
            "stale",
        }
        assert printer["status"] == "error" and not printer["stale"]
        assert printer["queued_labels"] == 7 and printer["shared_queued_labels"] == 3
        assert set(printer["cartridge"]) == {
            "name",
            "profile_name",
            "foreground",
            "background",
            "width_mm",
            "remaining_mm",
            "nominal_length_mm",
            "uncertain",
        }
        assert printer["cartridge"]["remaining_mm"] == 4900
        assert (
            client.get("/api/status/printers/usb-one", headers=HEADERS).json()["printers"][0][
                "name"
            ]
            == printer["name"]
        )
        assert client.get("/api/status/printers/unknown", headers=HEADERS).status_code == 404
        agent.dashboard_received["usb-one"] = time.monotonic() - 90
        stale = client.get("/api/status", headers=HEADERS).json()["printers"][0]
        assert stale["stale"] and stale["status"] == "unknown" and stale["connected"] is None
        assert stale["queued_labels"] == 7 and stale["snapshot_age_seconds"] >= 90
        agent.last_contact = 0
        agent.dashboard_received.clear()
        agent.dashboards.clear()
        missing = client.get("/api/status", headers=HEADERS).json()
        assert not missing["online"]
        assert missing["printers"][0]["queued_labels"] is None
        assert missing["printers"][0]["cartridge"] is None
        agent.journal.set_printer_enabled("usb-one", False)
        assert client.get("/api/status", headers=HEADERS).json()["printers"] == []
        assert client.get("/api/status/printers/usb-one", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("key", ["short", "a" * 32 + " ", "é" * 32, "a" * 513])
def test_status_key_deployment_validation(monkeypatch, key):
    from companion.config import Settings

    monkeypatch.setenv("LABEL_COMPANION_STATUS_API_KEY", key)
    with pytest.raises(ValidationError, match="Status API key"):
        Settings(server_url="http://testserver", api_key=SecretStr("main-key"))
    monkeypatch.setenv("LABEL_COMPANION_STATUS_API_KEY", KEY)
    with pytest.raises(ValidationError, match="Status API key"):
        Settings(server_url="http://testserver", api_key=SecretStr(KEY))


@pytest.mark.parametrize(
    "connected,held,pending,blocked,expected",
    [
        (True, False, False, False, "ready"),
        (False, False, False, False, "disconnected"),
        (True, True, False, False, "held"),
        (True, True, True, False, "awaiting_cartridge_confirmation"),
        (True, True, True, True, "error"),
    ],
)
def test_status_api_operational_states(
    accounts, tmp_path, connected, held, pending, blocked, expected
):
    settings, agent = local_station(accounts[0], tmp_path)
    settings.status_api_key = SecretStr(KEY)
    agent.statuses["usb-one"] = {"connected": connected}
    agent.dashboards["usb-one"].update(held=held, cartridge_check_pending=pending)
    agent.server_blocked["usb-one"] = blocked
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        assert (
            client.get("/api/status", headers=HEADERS).json()["printers"][0]["status"] == expected
        )
        marker = settings.data_dir / ".update-in-progress"
        marker.touch()
        assert client.get("/api/status", headers=HEADERS).status_code == 503


def test_status_api_shows_local_printing_while_main_server_is_offline(accounts, tmp_path):
    from threading import Event, Thread

    settings, agent = local_station(accounts[0], tmp_path)
    settings.status_api_key = SecretStr(KEY)
    agent.last_contact = 0
    stop = Event()
    thread = Thread(target=stop.wait)
    agent.threads["usb-one"] = thread
    thread.start()
    try:
        with TestClient(create_app(settings, agent, start_agent=False)) as client:
            data = client.get("/api/status", headers=HEADERS).json()
            assert not data["online"]
            assert data["printers"][0]["status"] == "printing"
            assert data["printers"][0]["stale"]
            stop.set()
            thread.join()
    finally:
        stop.set()
        thread.join()
