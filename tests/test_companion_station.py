import time
from threading import Event

import pytest
from app_client import TestClient
from mock_backend import MockPrinterBackend
from printer_factory import test_printer as printer_factory
from pydantic import SecretStr, ValidationError
from test_access_security import accounts as accounts
from test_companion_auth import station

from app import __version__
from app.models import ResourceGrant
from app.printer.factory import DeviceConfiguration
from companion.agent import Agent
from companion.config import LocalPrinter, Settings
from companion.journal import Journal
from companion.web import create_app, frontend_build


def local_station(admin, tmp_path, *, user="administrator"):
    item, _, _ = station(admin, bound=user)
    settings = Settings(
        server_url="http://testserver",
        public_url="http://testserver",
        api_key=item["api_key"],
        single_user_id=user,
        shared_pin=SecretStr("246810"),
        data_dir=tmp_path / "station",
        printers=[LocalPrinter(local_id="usb-one", name="Desk printer", driver="mock")],
    )
    journal = Journal(settings.data_dir / "journal.db")
    agent = Agent(settings, journal, client=admin, backend_factory=printer_factory)
    agent.sync()
    return settings, agent


def unlock(client):
    state = client.get("/api/station").json()
    client.headers["X-CSRF-Token"] = state["csrf_token"]
    response = client.post(
        "/api/station/unlock", json={"user_id": state["single_user_id"], "pin": "246810"}
    )
    assert response.status_code == 200, response.text
    return client.get("/api/station").json()


def test_confirmed_cartridge_is_not_rearmed_by_delayed_companion_status(accounts, tmp_path):
    from conftest import profile
    from test_cartridge_confirmation import cartridge

    from app.destinations import printer_state
    from app.models import Cartridge, CompanionPrinter

    admin, _, _ = accounts
    _, agent = local_station(admin, tmp_path)
    identifier = agent.identifiers["usb-one"]
    tape = profile(admin)
    cart = cartridge(admin, tape)
    worker = admin.app.state.fleet.workers[identifier]
    with admin.app.state.factory.begin() as session:
        session.get_one(Cartridge, cart["id"]).location_id = "workshop"
        state = printer_state(session, identifier)
        state.active_cartridge_id = cart["id"]
        state.cartridge_check_pending = True
        link = session.get_one(CompanionPrinter, identifier)
        link.status = {
            "connected": True,
            "tape_width_mm": tape["width_mm"],
            "media_changed": True,
            "media": {
                "width_mm": tape["width_mm"],
                "description": "Installed tape",
                "fingerprint": "same-tape",
                "verification_key": "cover-event-1",
            },
        }
    endpoint = f"/api/printer/active-tape?printer_id={identifier}"
    body = {"cartridge_id": cart["id"]}
    challenge = admin.put(endpoint, json=body)
    assert challenge.status_code == 409, challenge.text
    response = admin.put(
        endpoint,
        json={**body, "media_confirmation": challenge.json()["detail"]["confirmation"]},
    )
    assert response.status_code == 200, response.text
    # Several worker polls can happen before the next companion heartbeat.
    for _ in range(3):
        worker.tick()
        with admin.app.state.factory() as session:
            state = printer_state(session, identifier)
            assert not state.cartridge_check_pending
            assert state.media_verified_fingerprint == "cover-event-1"
        assert worker.backend.media_configuration()["verification_required"] is False
    # A later physical event must still require a fresh confirmation.
    with admin.app.state.factory.begin() as session:
        link = session.get_one(CompanionPrinter, identifier)
        link.status = {
            **link.status,
            "media": {**link.status["media"], "verification_key": "cover-event-2"},
        }
    worker.tick()
    with admin.app.state.factory() as session:
        assert printer_state(session, identifier).cartridge_check_pending


def test_cartridge_confirmation_roundtrip_does_not_latch_investigation(accounts, tmp_path):
    from conftest import profile
    from test_cartridge_confirmation import DetectedTapeTransport, cartridge

    from app.destinations import printer_state
    from app.models import Cartridge
    from app.printer.brother import BrotherPTP710BT

    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    identifier = agent.identifiers["usb-one"]
    tape = profile(admin)
    cart = cartridge(admin, tape)
    transport = DetectedTapeTransport(media=1)
    agent.executors["usb-one"].backend = BrotherPTP710BT(transport)
    worker = admin.app.state.fleet.workers[identifier]
    with admin.app.state.factory.begin() as session:
        session.get_one(Cartridge, cart["id"]).location_id = "workshop"
        printer_state(session, identifier).active_cartridge_id = cart["id"]
    worker.tick()
    agent.sync()

    # A completed cover event asks for cartridge verification, not fault clearance.
    transport.pending.append(transport.packet(5, notification=2))
    agent.sync()
    assert "confirm the installed cartridge" in agent.statuses["usb-one"]["error"]
    assert not agent.server_blocked["usb-one"]
    worker.tick()
    with admin.app.state.factory() as session:
        assert printer_state(session, identifier).cartridge_check_pending

    endpoint = f"/api/printer/active-tape?printer_id={identifier}"
    body = {"cartridge_id": cart["id"]}
    challenge = admin.put(endpoint, json=body)
    assert challenge.status_code == 409, challenge.text
    confirmed = admin.put(
        endpoint,
        json={**body, "media_confirmation": challenge.json()["detail"]["confirmation"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    worker.tick()
    # One heartbeat delivers the selection; the next reports its applied status.
    agent.sync()
    agent.sync()
    worker.tick()
    agent.sync()
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        printer = client.get("/api/station").json()["printers"][0]
        assert not printer["blocked"]
        assert printer["status"]["error"] is None
        assert not printer["dashboard"]["cartridge_check_pending"]

        # Real hardware faults still latch, even if subsequent status is healthy.
        transport.errors = (2, 0)
        agent.sync()
        assert agent.server_blocked["usb-one"]
        transport.errors = (0, 0)
        agent.sync()
        assert agent.server_blocked["usb-one"]


def test_frontend_build_identity_handles_missing_and_invalid_shell(tmp_path):
    path = tmp_path / "companion.html"
    assert frontend_build(path) is None
    path.write_text('<html><meta name="app-build" content="invalid"></html>')
    assert frontend_build(path) is None
    path.write_text(f'<html><meta name="app-build" content="{"a" * 64}"></html>')
    assert frontend_build(path) == "a" * 64
    path.write_bytes(b"\xff")
    assert frontend_build(path) is None


def test_locked_offline_station_reports_build_after_update_validation(
    accounts, tmp_path, monkeypatch
):
    settings, agent = local_station(accounts[0], tmp_path)
    monkeypatch.setattr("companion.web.frontend_build", lambda path: "b" * 64)
    agent.last_contact = 0
    marker = settings.data_dir / ".update-in-progress"
    marker.touch()
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        assert client.get("/api/station").status_code == 503
        assert client.get("/api/health").json() == {"healthy": True}
        marker.unlink()
        state = client.get("/api/station").json()
        assert state["frontend_build"] == "b" * 64
        assert state["locked"] and not state["online"]


def test_station_reports_version_without_printers(accounts, tmp_path):
    admin, _, _ = accounts
    item, _, _ = station(admin)
    settings = Settings(
        server_url="http://testserver",
        api_key=item["api_key"],
        data_dir=tmp_path / "station",
        printers=[],
    )
    agent = Agent(settings, Journal(settings.data_dir / "journal.db"), client=admin)
    agent.sync()
    current = admin.get("/api/companions").json()[0]
    assert current["software_version"] == __version__
    assert current["status"] == "online"
    assert current["server_version"] == __version__


def test_station_notifies_about_latest_release_using_its_own_version(
    accounts, tmp_path, monkeypatch
):
    from companion.web import create_app

    admin, _, _ = accounts
    admin.app.state.releases.latest = "v0.15.0"
    monkeypatch.setattr("companion.web.__version__", "0.14.0")
    settings, agent = local_station(admin, tmp_path)
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        state = client.get("/api/station").json()
        assert state["locked"] and state["update"] == {
            "version": "v0.15.0",
            "url": "https://github.com/tarobits/label-server/releases/tag/v0.15.0",
        }
        settings.show_update_notice = False
        assert client.get("/api/station").json()["update"] is None
        settings.show_update_notice = True
        for version in (None, "v0.14.0", "v0.13.0", "v0.16.0-pre1", "javascript:alert(1)"):
            agent.users["latest_release"] = version
            assert client.get("/api/station").json()["update"] is None
        agent.users["latest_release"] = "v0.16.0"
        assert client.get("/api/station").json()["update"]["version"] == "v0.16.0"


@pytest.mark.parametrize("mode", ["none", "once", "each_keypress"])
def test_keypad_deployment_settings_are_available_before_unlock(
    accounts, tmp_path, monkeypatch, mode
):
    monkeypatch.setenv("LABEL_COMPANION_PIN_KEYPAD_ENABLED", "true")
    monkeypatch.setenv("LABEL_COMPANION_PIN_KEYPAD_SHUFFLE", mode)
    settings, agent = local_station(accounts[0], tmp_path)
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        state = client.get("/api/station").json()
        assert state["locked"]
        assert state["pin_keypad"] == {"enabled": True, "shuffle": mode}


def test_keypad_configuration_defaults_and_invalid_mode(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LABEL_COMPANION_PIN_KEYPAD_ENABLED", raising=False)
    monkeypatch.delenv("LABEL_COMPANION_PIN_KEYPAD_SHUFFLE", raising=False)
    settings = Settings(server_url="http://testserver", api_key=SecretStr("test-only"))
    assert not settings.pin_keypad_enabled and settings.pin_keypad_shuffle == "none"
    monkeypatch.setenv("LABEL_COMPANION_PIN_KEYPAD_SHUFFLE", "invalid")
    with pytest.raises(ValidationError, match="pin_keypad_shuffle"):
        Settings(server_url="http://testserver", api_key=SecretStr("test-only"))


def test_update_validation_prevents_all_remote_work_and_controls(accounts, tmp_path, monkeypatch):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    marker = settings.data_dir / ".update-in-progress"
    marker.touch()
    activated = Event()
    monkeypatch.setattr(agent, "run", activated.set)
    with TestClient(create_app(settings, agent)) as local:
        assert local.get("/api/health").json() == {"healthy": True}
        assert local.get("/api/station").status_code == 503
        assert (
            local.post("/api/station/stop/usb-one", json={"mode": "emergency"}).status_code == 503
        )
        assert not activated.wait(0.1)
        marker.unlink()
        assert activated.wait(2)
        assert local.get("/api/station").status_code == 200


def test_stopping_during_update_validation_never_activates(accounts, tmp_path, monkeypatch):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    (settings.data_dir / ".update-in-progress").touch()
    activated = Event()
    monkeypatch.setattr(agent, "run", activated.set)
    with TestClient(create_app(settings, agent)) as local:
        assert local.get("/api/health").status_code == 200
    assert not activated.is_set()


def test_locked_station_exposes_dashboard_but_no_controls_or_secrets(accounts, tmp_path):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    identifier = agent.identifiers["usb-one"]
    app = create_app(settings, agent, start_agent=False)
    with TestClient(app) as local:
        response = local.get("/api/station")
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["locked"] and state["user"] is None and len(state["printers"]) == 1
        assert state["version"] == __version__
        assert state["lock_remaining_seconds"] is None
        assert settings.api_key.get_secret_value() not in response.text
        assert "246810" not in response.text and "session_token" not in response.text
        assert (
            local.post(
                "/api/station/unlock", json={"user_id": "administrator", "pin": "246810"}
            ).status_code
            == 403
        )
        state = unlock(local)
        assert not state["locked"] and state["user"]["id"] == "administrator"
        assert 295 <= state["lock_remaining_seconds"] <= settings.lock_timeout_seconds
        app.state.station.last_activity -= 65
        remaining = local.get("/api/station").json()["lock_remaining_seconds"]
        assert 230 <= remaining <= 235
        # Dashboard polling must not renew the inactivity timeout.
        assert local.get("/api/station").json()["lock_remaining_seconds"] <= remaining
        activity = local.post("/api/station/activity")
        assert activity.json()["lock_remaining_seconds"] == settings.lock_timeout_seconds
        assert local.get("/api/station").json()["lock_remaining_seconds"] > remaining
        assert (
            local.put(
                f"/api/proxy/printer/automatic-printing?printer_id={identifier}",
                json={"held": True},
            ).status_code
            == 200
        )
        # Even a bound administrator is limited to this installation and explicit routes.
        assert local.get("/api/proxy/printers").json()[0]["id"] == identifier
        assert (
            local.put(
                "/api/proxy/printer/automatic-printing?printer_id=main", json={"held": True}
            ).status_code
            == 403
        )
        assert local.post("/api/proxy/companion/printers", json={}).status_code == 403
        assert local.get("/api/proxy/admin/users").status_code == 403
        assert local.post("/api/station/lock").status_code == 200
        assert local.get("/api/station").json()["locked"]
        assert local.get("/api/station").json()["lock_remaining_seconds"] is None
        assert (
            local.put(
                f"/api/proxy/printer/automatic-printing?printer_id={identifier}",
                json={"held": False},
            ).status_code
            == 401
        )


def test_timeout_master_permission_revocation_and_pin_rate_limit(accounts, tmp_path):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path, user="alice")
    identifier = agent.identifiers["usb-one"]
    with admin.app.state.factory.begin() as session:
        for permission in ("printer.view", "printer.hold_resume"):
            session.add(
                ResourceGrant(
                    principal_kind="user",
                    principal_id="alice",
                    scope_kind="printer",
                    scope_id=identifier,
                    permission=permission,
                )
            )
    app = create_app(settings, agent, start_agent=False)
    with TestClient(app) as local:
        unlock(local)
        path = f"/api/proxy/printer/automatic-printing?printer_id={identifier}"
        assert local.put(path, json={"held": True}).status_code == 200
        with admin.app.state.factory.begin() as session:
            from sqlalchemy import delete

            session.execute(
                delete(ResourceGrant).where(
                    ResourceGrant.permission == "printer.hold_resume",
                    ResourceGrant.principal_id == "alice",
                )
            )
        assert local.put(path, json={"held": False}).status_code == 403
        app.state.station.last_activity = time.monotonic() - settings.lock_timeout_seconds - 1
        assert local.get("/api/station").json()["locked"]
        assert local.put(path, json={"held": False}).status_code == 401
        response = local.post("/api/station/unlock", json={"user_id": "alice", "pin": "秘密秘密"})
        assert response.status_code == 401
        for _ in range(11):
            response = local.post("/api/station/unlock", json={"user_id": "alice", "pin": "000000"})
        assert response.status_code == 429


def test_agent_sync_carries_one_remote_attempt_through_to_settlement(accounts, tmp_path):
    from conftest import profile

    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    identifier = agent.identifiers["usb-one"]
    tape = profile(admin, threshold=1)
    cartridge = admin.post(
        "/api/cartridges",
        json={"profile_id": tape["id"], "name": "Station tape", "nominal_length_mm": 8000},
    ).json()
    assert (
        admin.put(
            f"/api/printer/active-tape?printer_id={identifier}",
            json={"cartridge_id": cartridge["id"], "move_location": False},
        ).status_code
        == 200
    )
    job = admin.post(
        "/api/jobs",
        json={
            "destination_id": identifier,
            "tape_profile": tape["id"],
            "data": {"text": "Station"},
        },
    ).json()
    worker = admin.app.state.fleet.workers[identifier]
    worker.tick()
    agent.sync()
    agent.threads["usb-one"].join(timeout=5)
    assert not agent.threads["usb-one"].is_alive()
    agent.sync()
    worker.tick()
    agent.sync()
    worker.tick()
    assert admin.get(f"/api/jobs/{job['id']}").json()["status"] == "printed"
    assert isinstance(agent.executors["usb-one"].backend, MockPrinterBackend)
    assert len(agent.executors["usb-one"].backend.batches) == 1


def test_station_packing_requires_activity_access_and_stays_within_station(accounts, tmp_path):
    from conftest import profile
    from sqlalchemy import delete
    from test_cartridge_confirmation import cartridge

    from app.models import Batch, BatchItem, State

    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path, user="alice")
    identifier = agent.identifiers["usb-one"]
    tape = profile(admin)
    cart = cartridge(admin, tape)
    response = admin.post(
        "/api/jobs",
        json={
            "destination_id": identifier,
            "tape_profile": tape["id"],
            "data": {"text": "Pack me"},
        },
    )
    assert response.status_code == 201, response.text
    copy_id = response.json()["labels"][0]["id"]
    with admin.app.state.factory.begin() as session:
        for batch_id, printer_id in (("local-packing", identifier), ("other-packing", "main")):
            session.add(
                Batch(
                    id=batch_id,
                    printer_id=printer_id,
                    cartridge_id=cart["id"],
                    state=State.PRINTED,
                    estimated_mm=30,
                )
            )
        session.flush()
        session.add(
            BatchItem(batch_id="local-packing", copy_id=copy_id, position=0, outcome=State.PRINTED)
        )
    listing = f"/api/proxy/batches/page?printer_id={identifier}"
    detail = "/api/proxy/batches/local-packing"
    preview = f"{detail}/items/{copy_id}/preview"
    with TestClient(create_app(settings, agent, start_agent=False)) as local:
        assert local.get(listing).status_code == 401
        unlock(local)
        assert local.get(detail).status_code in (403, 404)
        assert local.get(preview).status_code in (403, 404)
        with admin.app.state.factory.begin() as session:
            session.add(
                ResourceGrant(
                    principal_kind="user",
                    principal_id="alice",
                    scope_kind="printer",
                    scope_id=identifier,
                    permission="printer.view_activity",
                )
            )
        assert [item["id"] for item in local.get(listing).json()["items"]] == ["local-packing"]
        assert local.get(detail).json()["items"][0]["text"] == "Pack me"
        assert local.get(preview).headers["content-type"] == "image/png"
        assert local.get("/api/proxy/batches/page?printer_id=main").status_code == 403
        assert local.get("/api/proxy/batches/other-packing").status_code == 403
        assert (
            local.get(f"/api/proxy/batches/other-packing/items/{copy_id}/preview").status_code
            == 403
        )
        assert local.post(detail, json={}).status_code == 403
        assert local.post(f"{detail}/review", json={}).status_code == 403
        with admin.app.state.factory.begin() as session:
            session.execute(
                delete(ResourceGrant).where(
                    ResourceGrant.principal_id == "alice",
                    ResourceGrant.permission == "printer.view_activity",
                )
            )
        assert local.get(preview).status_code in (403, 404)
        local.post("/api/station/lock")
        assert local.get(preview).status_code == 401


def test_offline_locked_stop_policy_and_durable_audit_replay(accounts, tmp_path):
    from sqlalchemy import select

    from app.models import AuditEvent
    from app.printer.base import PrintNotStarted

    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    executor = agent.executors["usb-one"]

    class Controlled(MockPrinterBackend):
        def print_batch_controlled(self, labels, control):
            raise PrintNotStarted("Test stopped before printing")

    executor.backend = Controlled()
    settings.allow_locked_emergency_stop = True
    app = create_app(settings, agent, start_agent=False)
    with TestClient(app) as local:
        state = local.get("/api/station").json()
        local.headers["X-CSRF-Token"] = state["csrf_token"]
        agent.last_contact = 0
        path = "/api/station/printers/usb-one/stop"
        assert local.post(path, json={"mode": "emergency"}).status_code == 403
        settings.allow_offline_emergency_stop = True
        assert local.post(path, json={"mode": "after_current"}).status_code == 403
        assert local.post(path, json={"mode": "emergency"}).status_code == 200
        assert executor.control.mode == "emergency"
        (event,) = agent.journal.pending_events()
        assert event["offline"] and event["locked"] and event["user_id"] is None
        # Lost acknowledgement: repeating one durable event creates only one entry.
        for _ in range(2):
            assert (
                agent.request("POST", "/api/companion/events/stop", json=event).status_code == 200
            )
        with admin.app.state.factory() as session:
            events = list(
                session.scalars(
                    select(AuditEvent).where(AuditEvent.action == "companion.local_stop_requested")
                )
            )
            assert len(events) == 1
            assert events[0].fields["source"]["value"] == "companion"
        response = admin.post(
            "/api/companion/events/stop",
            headers=agent.key_headers,
            json={**event, "mode": "after_current"},
        )
        assert response.status_code == 409
        agent.journal.acknowledge_event(event["id"])
        assert not agent.journal.pending_events()


def test_two_printers_continue_independently_when_one_fails(accounts, tmp_path):
    from conftest import profile

    admin, _, _ = accounts
    item, _, _ = station(admin, bound="administrator")
    settings = Settings(
        server_url="http://testserver",
        public_url="http://testserver",
        api_key=item["api_key"],
        single_user_id="administrator",
        shared_pin=SecretStr("246810"),
        data_dir=tmp_path,
        printers=[
            LocalPrinter(
                local_id=name,
                name=name,
                driver="mock",
                configuration=DeviceConfiguration(usb_serial=name),
            )
            for name in ("left", "right")
        ],
    )
    agent = Agent(
        settings, Journal(tmp_path / "journal.db"), client=admin, backend_factory=printer_factory
    )
    agent.sync()
    assert isinstance(agent.executors["left"].backend, MockPrinterBackend)
    agent.executors["left"].backend.fail_after = 0
    tape = profile(admin, threshold=1)
    jobs = {}
    for name, identifier in agent.identifiers.items():
        cart = admin.post(
            "/api/cartridges",
            json={"name": name, "profile_id": tape["id"], "nominal_length_mm": 8000},
        ).json()
        assert (
            admin.put(
                f"/api/printer/active-tape?printer_id={identifier}",
                json={"cartridge_id": cart["id"], "move_location": False},
            ).status_code
            == 200
        )
        jobs[name] = admin.post(
            "/api/jobs",
            json={"destination_id": identifier, "tape_profile": tape["id"], "data": {"text": name}},
        ).json()["id"]
        admin.app.state.fleet.workers[identifier].tick()
    agent.sync()
    for thread in agent.threads.values():
        thread.join(timeout=5)
        assert not thread.is_alive()
    agent.sync()
    for identifier in agent.identifiers.values():
        admin.app.state.fleet.workers[identifier].tick()
    assert agent.journal.blocked("left") and not agent.journal.blocked("right")
    assert admin.get(f"/api/jobs/{jobs['left']}").json()["status"] == "needs_review"
    assert admin.get(f"/api/jobs/{jobs['right']}").json()["status"] == "printed"


def test_web_printer_registration_persists_and_removal_does_not_reseed(accounts, tmp_path):
    from app.models import CompanionPrinter
    from app.printer.remote import RemotePrinterBackend

    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path)
    app = create_app(settings, agent, start_agent=False)
    with TestClient(app) as local:
        body = {
            "local_id": "web-added",
            "name": "Web printer",
            "driver": "mock",
            "configuration": {"usb_serial": "web-added"},
        }
        assert local.post("/api/station/printers", json=body).status_code == 403
        unlock(local)
        assert local.post("/api/station/printers", json=body).status_code == 201
        assert local.post("/api/station/printers", json=body).status_code == 201
        identifier = agent.identifiers["web-added"]
        assert len(agent.devices) == 2
        assert (
            admin.put(
                f"/api/printers/{identifier}",
                json={"name": "Renamed printer", "driver": "mock", "feed_mm": 3},
            ).status_code
            == 200
        )
        agent.sync()
        restarted = Agent(
            settings,
            Journal(settings.data_dir / "journal.db"),
            client=admin,
            backend_factory=printer_factory,
        )
        restarted.sync()
        assert restarted.identifiers["web-added"] == identifier
        assert restarted.configurations["web-added"][1]["feed_mm"] == 3
        assert (
            next(p for p in restarted.devices if p.local_id == "web-added").name
            == "Renamed printer"
        )
        assert (
            local.put(
                "/api/station/printers/web-added/enabled", json={"enabled": False}
            ).status_code
            == 200
        )
        with admin.app.state.factory() as session:
            assert not session.get(CompanionPrinter, identifier).enabled
        backend = admin.app.state.fleet.workers[identifier].backend
        assert isinstance(backend, RemotePrinterBackend) and not backend.get_status().connected
        # Supplying the original bootstrap again must not undo an explicit removal.
        settings.printers.append(LocalPrinter.model_validate(body))
        restarted = Agent(
            settings,
            Journal(settings.data_dir / "journal.db"),
            client=admin,
            backend_factory=printer_factory,
        )
        assert "web-added" not in {device.local_id for device in restarted.devices}
        assert (
            local.put("/api/station/printers/web-added/enabled", json={"enabled": True}).status_code
            == 200
        )
        agent.sync()
        assert agent.identifiers["web-added"] == identifier
        assert len(agent.devices) == 2
        assert local.get("/api/station").json()["removed_printers"] == []


def test_companion_access_alone_cannot_manage_printer_registration(accounts, tmp_path):
    admin, _, _ = accounts
    settings, agent = local_station(admin, tmp_path, user="alice")
    with TestClient(create_app(settings, agent, start_agent=False)) as local:
        unlock(local)
        body = {"local_id": "forbidden", "name": "Forbidden", "driver": "mock"}
        assert local.post("/api/station/printers", json=body).status_code == 403
        assert (
            local.put("/api/station/printers/usb-one/enabled", json={"enabled": False}).status_code
            == 403
        )
        assert len(agent.devices) == 1
        assert local.get("/api/station").json()["removed_printers"] == []
