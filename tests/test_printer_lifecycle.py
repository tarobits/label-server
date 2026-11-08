import pytest
from conftest import profile
from sqlalchemy import select
from test_access_security import accounts as accounts
from test_companion_auth import station
from test_companion_station import local_station

from app.models import (
    CompanionPrinter,
    LabelCopy,
    PrinterDevice,
    PrinterState,
    PrintJob,
    ResourceGrant,
)
from app.printer.remote import RemotePrinterBackend


def remote(admin):
    _, headers, _ = station(admin)
    body = {"local_id": "usb-one", "name": "Duplicate", "driver": "mock"}
    response = admin.post("/api/companion/printers", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()["printer_id"], headers, body


def test_retire_preserves_record_releases_cartridge_and_stops_worker(accounts):
    admin, alice, _ = accounts
    tape = profile(admin)
    cart = admin.post(
        "/api/cartridges",
        json={
            "name": "Installed",
            "profile_id": tape["id"],
            "nominal_length_mm": 8000,
        },
    ).json()
    assert (
        admin.put(
            "/api/printer/active-tape?printer_id=main", json={"cartridge_id": cart["id"]}
        ).status_code
        == 200
    )
    assert alice.delete("/api/printers/main").status_code == 403
    worker = admin.app.state.fleet.workers["main"]
    assert admin.delete("/api/printers/main").status_code == 200
    assert not admin.get("/api/printers").json()
    assert not admin.get("/api/destinations").json()
    assert not admin.get("/api/printers/status").json()
    assert "main" not in admin.app.state.fleet.workers
    assert not admin.app.state.registry.definitions()
    worker.backend.get_status = lambda: pytest.fail("Retired worker contacted hardware")
    worker.tick()
    with admin.app.state.factory() as session:
        assert session.get(PrinterDevice, "main").config["retired"]
        state = session.scalar(select(PrinterState).where(PrinterState.printer_id == "main"))
        assert state.active_cartridge_id is None
    assert (
        admin.put("/api/printers/main", json={"name": "Resurrect", "driver": "mock"}).status_code
        == 409
    )


def test_retirement_rejects_queued_work_and_group_membership(accounts):
    admin, _, _ = accounts
    tape = profile(admin, threshold=100)
    queued = admin.post(
        "/api/jobs",
        json={
            "destination_id": "main",
            "tape_profile": tape["id"],
            "data": {"text": "Keep me"},
            "copies": 1,
        },
    )
    assert queued.status_code == 201, queued.text
    assert admin.delete("/api/printers/main").status_code == 409
    other = admin.post("/api/printers", json={"name": "Group member", "driver": "mock"}).json()
    assert (
        admin.post(
            "/api/printer-groups", json={"name": "Group", "printer_ids": [other["id"]]}
        ).status_code
        == 201
    )
    assert admin.delete(f"/api/printers/{other['id']}").status_code == 409


def test_move_keeps_identity_queue_owner_grants_and_rebinds_connection(accounts):
    admin, alice, _ = accounts
    target, headers, registration = remote(admin)
    tape = profile(admin, threshold=100)
    queued = admin.post(
        "/api/jobs",
        json={
            "destination_id": "main",
            "tape_profile": tape["id"],
            "data": {"text": "Follow me"},
            "copies": 2,
        },
    ).json()
    with admin.app.state.factory.begin() as session:
        source = session.get(PrinterDevice, "main")
        source.owner_id = "alice"
        source.config = {**source.config, "feed_mm": 7, "cut_each": False}
        session.add(
            ResourceGrant(
                scope_kind="printer",
                scope_id="main",
                principal_kind="user",
                principal_id="alice",
                permission="printer.view_audit",
            )
        )
    path = "/api/printers/main/move-to-companion"
    body = {"target_printer_id": target}
    assert alice.post(path, json=body).status_code == 403
    response = admin.post(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["printer_id"] == "main"
    assert [p["id"] for p in admin.get("/api/printers").json()] == ["main"]
    assert isinstance(admin.app.state.fleet.workers["main"].backend, RemotePrinterBackend)
    assert target not in admin.app.state.fleet.workers
    with admin.app.state.factory() as session:
        source = session.get(PrinterDevice, "main")
        assert source.owner_id == "alice"
        assert source.location_id == "workshop"
        assert source.config["feed_mm"] == 7
        assert source.config["cut_each"] is False
        assert session.get(PrinterDevice, target).config["retired"]
        assert session.get(CompanionPrinter, "main").local_id == "usb-one"
        assert session.get(PrintJob, queued["id"]).destination_id == "main"
        assert len(list(session.scalars(select(LabelCopy)))) == 2
        assert session.scalar(select(ResourceGrant).where(ResourceGrant.scope_id == "main"))
        assert session.scalar(
            select(PrinterState).where(PrinterState.printer_id == "main")
        ).automatic_printing_held
    assert (
        admin.post("/api/companion/printers", headers=headers, json=registration).json()[
            "printer_id"
        ]
        == "main"
    )
    # An older running companion must not disable the physical slot when its cached ID changes.
    assert (
        admin.put(
            f"/api/companion/printers/{target}/status", headers=headers, json={"connected": True}
        ).status_code
        == 409
    )
    assert (
        admin.put(
            "/api/companion/printers/main/status", headers=headers, json={"connected": True}
        ).status_code
        == 200
    )


def test_agent_refreshes_moved_identity_without_restart(accounts, tmp_path):
    admin, _, _ = accounts
    _, agent = local_station(admin, tmp_path)
    target = agent.identifiers["usb-one"]
    response = admin.post(
        "/api/printers/main/move-to-companion", json={"target_printer_id": target}
    )
    assert response.status_code == 200, response.text
    agent.sync()
    assert agent.identifiers["usb-one"] == "main"
    assert agent.devices
    with admin.app.state.factory() as session:
        assert session.get(CompanionPrinter, "main").last_seen_at is not None


def test_busy_worker_and_blocked_companion_cannot_be_retired_or_moved(accounts):
    admin, _, _ = accounts
    target, _, _ = remote(admin)
    worker = admin.app.state.fleet.workers["main"]
    with worker.printer_lock:
        assert admin.delete("/api/printers/main").status_code == 409
        assert (
            admin.post(
                "/api/printers/main/move-to-companion", json={"target_printer_id": target}
            ).status_code
            == 409
        )
    with admin.app.state.factory.begin() as session:
        session.get(CompanionPrinter, target).blocked = True
    assert admin.delete(f"/api/printers/{target}").status_code == 409
    assert (
        admin.post(
            "/api/printers/main/move-to-companion", json={"target_printer_id": target}
        ).status_code
        == 409
    )


def test_unsettled_remote_authorization_cannot_be_bypassed_by_retirement(accounts):
    from test_companion_execution import queued_remote

    from app.models import Batch, State

    admin, _, _ = accounts
    _, _, identifier, _, work = queued_remote(admin)
    # Even a manually changed batch state cannot discard a remote authorization.
    with admin.app.state.factory.begin() as session:
        session.get(Batch, work["payload"]["batch_id"]).state = State.FAILED
    response = admin.delete(f"/api/printers/{identifier}")
    assert response.status_code == 409
    assert "outstanding companion batches" in response.json()["detail"]


def test_retired_history_remains_visible_without_operational_access(accounts):
    from app.models import Batch, State

    admin, alice, _ = accounts
    tape = profile(admin)
    cart = admin.post(
        "/api/cartridges",
        json={
            "name": "History",
            "profile_id": tape["id"],
            "nominal_length_mm": 8000,
        },
    ).json()
    with admin.app.state.factory.begin() as session:
        session.add(
            ResourceGrant(
                scope_kind="printer",
                scope_id="main",
                principal_kind="user",
                principal_id="alice",
                permission="printer.view_activity",
            )
        )
        session.add(
            Batch(
                id="old-batch",
                printer_id="main",
                cartridge_id=cart["id"],
                state=State.PRINTED,
                estimated_mm=20,
                consumed_mm=20,
            )
        )
    assert admin.delete("/api/printers/main").status_code == 200
    assert alice.get("/api/batches/old-batch").status_code == 200
    assert alice.get("/api/printers").json() == []
    assert (
        alice.put("/api/destinations/main/automatic-printing", json={"held": False}).status_code
        == 403
    )


def test_move_audit_redacts_other_registration_and_companion(accounts):
    admin, alice, _ = accounts
    target, _, _ = remote(admin)
    with admin.app.state.factory.begin() as session:
        session.add(
            ResourceGrant(
                scope_kind="printer",
                scope_id="main",
                principal_kind="user",
                principal_id="alice",
                permission="printer.view_audit",
            )
        )
    assert (
        admin.post(
            "/api/printers/main/move-to-companion", json={"target_printer_id": target}
        ).status_code
        == 200
    )
    query = {"printer": "main", "action": "printer.moved_to_companion"}
    entry = admin.get("/api/audit", params=query).json()["items"][0]
    assert entry["fields"]["retired_printer_id"] == target
    projected = alice.get("/api/audit", params=query).json()["items"][0]
    assert "retired_printer_id" not in projected["fields"]
    assert "companion_id" not in projected["fields"]
    assert projected["restricted_details"]
