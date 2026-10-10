from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.access import LocalOwnerPolicy
from app.config import Settings
from app.db import make_engine, session_factory
from app.main import create_app as production_app
from app.models import PrinterDevice, PrinterState


def create_app(*args, **kwargs):
    app = production_app(*args, **kwargs)
    # These tests exercise production driver configuration; auth has its own suite.
    app.state.access_policy = LocalOwnerPolicy()
    return app


def setup(tmp_path):
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'web.db'}")
    config = Config("alembic.ini")
    config.attributes["database_url"] = settings.database_url
    command.upgrade(config, "head")
    return settings, config


def test_empty_installation_and_no_production_mock_driver(tmp_path):
    settings, _ = setup(tmp_path)
    with TestClient(create_app(settings, start_worker=False)) as client:
        assert client.get("/api/printers").json() == []
        assert client.get("/api/destinations").json() == []
        assert client.get("/api/printers/status").json() == []
        assert client.get("/api/workspace").status_code == 200
        assert client.get("/api/status").status_code == 409
        assert client.get("/api/printer/mock").status_code == 404
        assert (
            client.post("/api/printers", json={"name": "Mock", "driver": "mock"}).status_code == 422
        )
        assert (
            client.post(
                "/api/printers", json={"name": "Unsupported", "driver": "missing"}
            ).status_code
            == 422
        )
        assert not client.app.state.fleet.workers


def test_every_printer_is_configurable_and_environment_cannot_override_it(tmp_path, monkeypatch):
    settings, _ = setup(tmp_path)
    with TestClient(create_app(settings, start_worker=False)) as client:
        first = client.post("/api/printers", json={"name": "Desk"}).json()
        identifier = first["id"]
        assert identifier != "main"
        body = {
            "name": "Cable bench",
            "usb_serial": "ONE",
            "resolution": "high",
            "feed_mm": 5,
            "leader_mm": 20,
            "cut_each": False,
            "timeout_seconds": 180,
        }
        response = client.put(f"/api/printers/{identifier}", json=body)
        assert response.status_code == 200, response.text
        client.put(f"/api/destinations/{identifier}/automatic-printing", json={"held": True})
        assert client.get("/api/printers").json()[0]["capabilities"]["dpi_x"] == 360
    monkeypatch.setenv("LABEL_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("LABEL_PRINTER_RESOLUTION", "normal")
    with TestClient(
        create_app(Settings(database_url=settings.database_url), start_worker=False)
    ) as restarted:
        device = restarted.get("/api/printers").json()[0]
        assert device["id"] == identifier and device["name"] == "Cable bench"
        assert device["config"]["feed_mm"] == 5 and not device["config"]["cut_each"]
        assert device["capabilities"]["dpi_x"] == 360
        assert restarted.get("/api/status").json()["automatic_printing_held"]
        assert "main" not in restarted.app.state.fleet.workers


def test_serial_validation_and_ambiguous_defaults(tmp_path):
    settings, _ = setup(tmp_path)
    with TestClient(create_app(settings, start_worker=False)) as client:
        first = client.post("/api/printers", json={"name": "First"}).json()
        assert (
            client.post("/api/printers", json={"name": "Second", "usb_serial": "TWO"}).status_code
            == 422
        )
        assert (
            client.put(
                f"/api/printers/{first['id']}", json={"name": "First", "usb_serial": "ONE"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/printers", json={"name": "Duplicate", "usb_serial": "ONE"}
            ).status_code
            == 409
        )
        second = client.post("/api/printers", json={"name": "Second", "usb_serial": "TWO"}).json()
        assert client.get("/api/status").status_code == 422
        assert client.get(f"/api/status?printer_id={first['id']}").status_code == 200
        assert (
            client.put(
                f"/api/printers/{second['id']}", json={"name": "Second", "usb_serial": "ONE"}
            ).status_code
            == 409
        )
        assert client.get("/api/printers").json()[1]["config"]["usb_serial"] == "TWO"


def test_config_change_preserves_frozen_work_and_group_geometry(tmp_path):
    settings, _ = setup(tmp_path)
    with TestClient(create_app(settings, start_worker=False)) as client:
        first = client.post("/api/printers", json={"name": "First", "usb_serial": "ONE"}).json()
        second = client.post("/api/printers", json={"name": "Second", "usb_serial": "TWO"}).json()
        group = client.post(
            "/api/printer-groups",
            json={"name": "Station", "printer_ids": [first["id"], second["id"]]},
        ).json()
        update = {"name": "First", "usb_serial": "ONE", "resolution": "high"}
        assert client.put(f"/api/printers/{first['id']}", json=update).status_code == 409
        profile = client.post("/api/tape-profiles", json={"name": "White", "width_mm": 24}).json()
        job = client.post(
            "/api/jobs",
            json={
                "destination_id": group["id"],
                "tape_profile": profile["id"],
                "data": {"text": "Frozen"},
            },
        )
        assert job.status_code == 201, job.text
        update["resolution"] = "normal"
        update["feed_mm"] = 3
        assert client.put(f"/api/printers/{first['id']}", json=update).status_code == 409
        update["feed_mm"] = 2
        update["name"] = "Renamed"
        assert client.put(f"/api/printers/{first['id']}", json=update).status_code == 200
        assert (
            client.get(f"/api/jobs/{job.json()['id']}").json()["template_snapshot"]
            == job.json()["template_snapshot"]
        )


def test_legacy_physical_config_import_and_mock_retirement(tmp_path, monkeypatch):
    settings, config = setup(tmp_path)
    command.downgrade(config, "e51f038b02cd")
    engine = make_engine(settings.database_url)
    with session_factory(engine).begin() as session:
        session.add(
            PrinterDevice(
                id="main", name="Brother", driver="brother-pt-p710bt", config={"usb_serial": "OLD"}
            )
        )
        session.add(PrinterState(id=1, printer_id="main"))
        session.add(PrinterDevice(id="simulation", name="Old mock", driver="mock", config={}))
        session.add(PrinterState(printer_id="simulation"))
    engine.dispose()
    monkeypatch.setenv("LABEL_PRINTER_RESOLUTION", "high")
    monkeypatch.setenv("LABEL_PRINTER_FEED_MM", "4")
    command.upgrade(config, "head")
    with TestClient(create_app(settings, start_worker=False)) as client:
        devices = client.get("/api/printers").json()
        assert len(devices) == 1 and devices[0]["id"] == "main"
        assert devices[0]["config"]["feed_mm"] == 4
        assert devices[0]["capabilities"]["dpi_x"] == 360
        assert client.get("/api/status").json()["printer_id"] == "main"
        assert client.get("/api/status?printer_id=simulation").status_code == 409
        # Its history can still reference the retired registration.
        with client.app.state.factory() as session:
            assert session.get(PrinterDevice, "simulation") is not None
