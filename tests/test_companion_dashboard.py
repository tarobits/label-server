import time

import pytest
from app_client import TestClient
from sqlalchemy import select
from test_access_security import accounts as accounts
from test_companion_execution import queued_remote
from test_companion_station import local_station, unlock

from app.companion_dashboard import printer_dashboard
from app.models import Batch, BatchItem, LabelCopy, PrinterGroup, PrintJob, ResourceGrant, State
from companion.web import create_app


@pytest.mark.parametrize("enabled", [True, False])
def test_manual_only_mode_reaches_locked_station_and_survives_sync(
    accounts, tmp_path, monkeypatch, enabled
):
    from app.destinations import printer_state
    from app.models import PrinterDevice

    monkeypatch.setenv("LABEL_COMPANION_SHOW_LOCKED_DASHBOARD_DETAILS", str(enabled).lower())
    admin = accounts[0]
    settings, agent = local_station(admin, tmp_path)
    identifier = agent.identifiers["usb-one"]
    with admin.app.state.factory.begin() as session:
        session.get_one(PrinterDevice, identifier).no_automatic_printing = True
        printer_state(session, identifier).automatic_printing_held = True
    agent.sync()
    agent.sync()
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        data = client.get("/api/station").json()["printers"][0]
        assert data["no_automatic_printing"]
        if enabled:
            assert not data["dashboard"]["held"]
        unlock(client)
        assert (
            client.put(
                f"/api/proxy/printer/automatic-printing?printer_id={identifier}",
                json={"held": False},
            ).status_code
            == 409
        )


@pytest.mark.parametrize("enabled", [True, False])
def test_locked_dashboard_deployment_setting(accounts, tmp_path, monkeypatch, enabled):
    monkeypatch.setenv("LABEL_COMPANION_SHOW_LOCKED_DASHBOARD_DETAILS", str(enabled).lower())
    settings, agent = local_station(accounts[0], tmp_path)
    assert settings.show_locked_dashboard_details is enabled
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        data = client.get("/api/station").json()["printers"][0]
        assert ("dashboard" in data) is enabled
        if enabled:
            assert data["dashboard"]["queued_labels"] == 0
            assert data["snapshot_age_seconds"] >= 0
        # The switch does not remove a permitted operator's dashboard.
        data = unlock(client)["printers"][0]
        assert data["dashboard"]["queued_labels"] == 0
        assert client.post("/api/station/lock").status_code == 200
        assert ("dashboard" in client.get("/api/station").json()["printers"][0]) is enabled


def test_private_dashboard_requires_printer_view(accounts, tmp_path, monkeypatch):
    monkeypatch.setenv("LABEL_COMPANION_SHOW_LOCKED_DASHBOARD_DETAILS", "false")
    admin = accounts[0]
    settings, agent = local_station(admin, tmp_path, user="alice")
    identifier = agent.identifiers["usb-one"]
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        assert "dashboard" not in unlock(client)["printers"][0]
        with admin.app.state.factory.begin() as session:
            session.add(
                ResourceGrant(
                    principal_kind="user",
                    principal_id="alice",
                    scope_kind="printer",
                    scope_id=identifier,
                    permission="printer.view",
                )
            )
        assert client.get("/api/station").json()["printers"][0]["dashboard"]


def test_offline_dashboard_preserves_aged_snapshot(accounts, tmp_path):
    settings, agent = local_station(accounts[0], tmp_path)
    agent.last_contact = 0
    agent.dashboard_received["usb-one"] -= 90
    with TestClient(create_app(settings, agent, start_agent=False)) as client:
        data = client.get("/api/station").json()
        assert not data["online"]
        assert data["printers"][0]["dashboard"]["queued_labels"] == 0
        assert data["printers"][0]["snapshot_age_seconds"] >= 90


def test_dashboard_counts_actual_copies_and_confirmed_outcomes(accounts):
    admin = accounts[0]
    _, headers, identifier, _, work = queued_remote(admin)
    with admin.app.state.factory.begin() as session:
        batch = session.get(Batch, work["payload"]["batch_id"])
        assert batch is not None
        summary = printer_dashboard(session, identifier)
        assert summary["active_batch"]["total_labels"] == 3
        assert summary["active_batch"]["confirmed_labels"] == 0
        assert summary["printed_last_24h"] == 0
        batch.state = State.NEEDS_REVIEW
        batch.finished_at = time.time()
        items = list(session.scalars(select(BatchItem).where(BatchItem.batch_id == batch.id)))
        items[0].outcome = State.PRINTED
        items[1].outcome = State.NEEDS_REVIEW
        items[2].outcome = State.NEEDS_REVIEW
        original = session.get(LabelCopy, items[0].copy_id)
        assert original is not None
        job = session.get(PrintJob, original.job_id)
        assert job is not None
        for destination, count in [(identifier, 2), ("shared", 4), ("elsewhere", 9)]:
            queued = PrintJob(
                destination_id=destination,
                profile_id=job.profile_id,
                template_id=job.template_id,
                template_snapshot=job.template_snapshot,
                payload={"text": "private label"},
                width_mm=24,
                length_mm=20,
                copies=count,
                owner_id="alice",
            )
            session.add(queued)
            session.flush()
            session.add_all(LabelCopy(job_id=queued.id, ordinal=n) for n in range(count))
        session.add(PrinterGroup(id="shared", name="Shared", printer_ids=[identifier, "other"]))
    response = admin.put(
        f"/api/companion/printers/{identifier}/status",
        headers=headers,
        json={"connected": True, "tape_width_mm": 24},
    )
    assert response.status_code == 200
    summary = response.json()["dashboard"]
    assert summary["queued_labels"] == 2
    assert summary["shared_queued_labels"] == 4
    assert summary["printed_last_24h"] == 1
    assert summary["active_batch"] is None
    assert summary["last_batch"]["confirmed_labels"] == 1
    assert summary["last_batch"]["total_labels"] == 3
    assert summary["cartridge"]["name"] == "Remote cartridge"
    assert "alice" not in str(summary) and "private label" not in str(summary)
    assert set(summary["cartridge"]) == {
        "name",
        "remaining_mm",
        "nominal_length_mm",
        "uncertain",
        "profile_name",
        "width_mm",
        "foreground",
        "background",
    }
    with admin.app.state.factory.begin() as session:
        batch = session.get(Batch, work["payload"]["batch_id"])
        assert batch is not None
        batch.finished_at = time.time() - 90000
        session.flush()
        assert printer_dashboard(session, identifier)["printed_last_24h"] == 0
        assert printer_dashboard(session, "other")["last_batch"] is None
