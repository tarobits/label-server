from copy import deepcopy

import pytest
from conftest import profile
from mock_backend import MockPrinterBackend
from test_access_security import accounts as accounts
from test_companion_auth import station

from app.companion_protocol import ExecutionResult
from app.models import Batch, CompanionPrinter, State
from companion.executor import Executor
from companion.journal import Journal


def queued_remote(admin):
    companion, headers, _ = station(admin)
    response = admin.post(
        "/api/companion/printers",
        headers=headers,
        json={"local_id": "usb-one", "name": "Remote printer", "driver": "mock"},
    )
    assert response.status_code == 201, response.text
    identifier = response.json()["printer_id"]
    tape = profile(admin, threshold=1)
    cart = admin.post(
        "/api/cartridges",
        json={"profile_id": tape["id"], "name": "Remote cartridge", "nominal_length_mm": 8000},
    ).json()
    assert (
        admin.put(
            f"/api/printer/active-tape?printer_id={identifier}",
            json={"cartridge_id": cart["id"], "move_location": False},
        ).status_code
        == 200
    )
    assert (
        admin.put(
            f"/api/companion/printers/{identifier}/status",
            headers=headers,
            json={"connected": True, "tape_width_mm": 24},
        ).status_code
        == 200
    )
    worker = admin.app.state.fleet.workers[identifier]
    worker.tick()
    response = admin.post(
        "/api/jobs",
        json={
            "destination_id": identifier,
            "tape_profile": tape["id"],
            "data": {"text": "Remote batch"},
            "copies": 3,
        },
    )
    assert response.status_code == 201, response.text
    worker.tick()
    work = admin.get("/api/companion/work", headers=headers).json()
    assert len(work) == 1, work
    return companion, headers, identifier, worker, work[0]


def authorize(admin, headers, work, journal):
    envelope = journal.receive(work["payload"], work["digest"])
    path = f"/api/companion/batches/{envelope.batch_id}/ready"
    response = admin.post(path, headers=headers, json={"digest": work["digest"]})
    assert response.status_code == 200, response.text
    assert (
        response.json() == admin.post(path, headers=headers, json={"digest": work["digest"]}).json()
    )
    journal.authorize(envelope.batch_id, work["digest"], response.json()["go_token"])
    return envelope


def test_complete_authorized_batch_finishes_offline_and_result_replays_never_reprint(
    accounts, tmp_path
):
    admin, _, _ = accounts
    _, headers, identifier, worker, work = queued_remote(admin)
    journal = Journal(tmp_path / "journal.db")
    backend = MockPrinterBackend()
    executor = Executor(journal, "usb-one", backend)
    envelope = authorize(admin, headers, work, journal)
    altered = deepcopy(work["payload"])
    altered["labels"].pop()
    with pytest.raises(ValueError, match="differs from the authorized batch"):
        executor.execute(altered)
    assert journal.row(envelope.batch_id)["phase"] == "authorized"
    assert not backend.batches
    # Main-server recovery cannot reinterpret an outstanding remote go as failure.
    worker.recover()
    worker.tick()
    with admin.app.state.factory() as session:
        assert session.get(Batch, envelope.batch_id).state == State.PRINTING
    # No HTTP requests occur while the hardware owner executes this batch.
    executor.execute(work["payload"])
    assert len(backend.batches) == 1
    executor.execute(work["payload"])
    assert len(backend.batches) == 1
    journal = Journal(tmp_path / "journal.db")
    journal.recover()
    [(batch_id, result)] = journal.pending_results()
    path = f"/api/companion/batches/{batch_id}/result"
    for _ in range(2):
        response = admin.post(path, headers=headers, json=result.model_dump())
        assert response.status_code == 200, response.text
    worker.tick()
    with admin.app.state.factory() as session:
        assert session.get(Batch, batch_id).state == State.PRINTED
        assert not session.get(CompanionPrinter, identifier).blocked
    journal.acknowledge(batch_id)
    journal.receive(work["payload"], work["digest"])
    journal.authorize(batch_id, work["digest"], result.go_token)
    Executor(journal, "usb-one", backend).execute(work["payload"])
    assert len(backend.batches) == 1
    changed = {**result.model_dump(), "consumed_mm": (result.consumed_mm or 0) + 1}
    assert admin.post(path, headers=headers, json=changed).status_code == 409


def test_companion_crash_after_execution_started_blocks_without_replay(accounts, tmp_path):
    admin, _, _ = accounts
    _, headers, identifier, worker, work = queued_remote(admin)
    journal = Journal(tmp_path / "journal.db")
    envelope = authorize(admin, headers, work, journal)
    assert journal.start(envelope.batch_id)
    # There is no trustworthy result after a process crash, even if the device is ready.
    restarted = Journal(tmp_path / "journal.db")
    restarted.recover()
    assert restarted.blocked("usb-one")
    backend = MockPrinterBackend()
    Executor(restarted, "usb-one", backend).execute(work["payload"])
    assert not backend.batches
    [(batch_id, result)] = restarted.pending_results()
    assert result.outcome == "interrupted" and result.confirmed_labels == 0
    assert (
        admin.post(
            f"/api/companion/batches/{batch_id}/result", headers=headers, json=result.model_dump()
        ).status_code
        == 200
    )
    worker.tick()
    with admin.app.state.factory() as session:
        assert session.get(Batch, batch_id).state == State.NEEDS_REVIEW
        assert session.get(CompanionPrinter, identifier).blocked
    assert admin.put(
        f"/api/companion/printers/{identifier}/status",
        headers=headers,
        json={"connected": True, "tape_width_mm": 24},
    ).json()["blocked"]


def test_partial_transfer_missing_go_and_other_installation_cannot_execute(accounts, tmp_path):
    admin, _, _ = accounts
    _, headers, identifier, worker, work = queued_remote(admin)
    _, other_headers, _ = station(admin)
    batch_id = work["payload"]["batch_id"]
    assert (
        admin.post(
            f"/api/companion/batches/{batch_id}/ready",
            headers=other_headers,
            json={"digest": work["digest"]},
        ).status_code
        == 404
    )
    assert (
        admin.put(
            f"/api/companion/printers/{identifier}/status",
            headers=other_headers,
            json={"connected": False},
        ).status_code
        == 404
    )
    journal = Journal(tmp_path / "journal.db")
    altered = deepcopy(work["payload"])
    altered["labels"].pop()
    with pytest.raises(ValueError, match="altered batch"):
        journal.receive(altered, work["digest"])
    journal.receive(work["payload"], work["digest"])
    backend = MockPrinterBackend()
    Executor(journal, "usb-one", backend).execute(work["payload"])
    assert not backend.batches
    forged = ExecutionResult(
        digest=work["digest"], go_token="unapproved", outcome="printed", confirmed_labels=3
    )
    assert (
        admin.post(
            f"/api/companion/batches/{batch_id}/result", headers=headers, json=forged.model_dump()
        ).status_code
        == 409
    )


def test_idle_disconnect_recovers_but_hardware_error_requires_human_clearance(accounts):
    admin, _, _ = accounts
    _, headers, _ = station(admin)
    identifier = admin.post(
        "/api/companion/printers",
        headers=headers,
        json={"local_id": "desk", "name": "Desk", "driver": "mock"},
    ).json()["printer_id"]
    path = f"/api/companion/printers/{identifier}/status"
    for connected in (True, False, True):
        response = admin.put(path, headers=headers, json={"connected": connected})
        assert response.status_code == 200
        assert not response.json()["blocked"]
    assert admin.put(
        path, headers=headers, json={"connected": True, "error": "Hardware failure"}
    ).json()["blocked"]
    assert admin.put(path, headers=headers, json={"connected": True}).json()["blocked"]
    response = admin.post(f"/api/companions/printers/{identifier}/clear")
    assert response.status_code == 200
    clearance = response.json()["clearance"]
    # An old local block arriving before its clearance acknowledgement cannot undo it.
    assert not admin.put(
        path,
        headers=headers,
        json={"connected": True, "local_blocked": True, "clearance_seen": clearance - 1},
    ).json()["blocked"]
    assert admin.put(
        path,
        headers=headers,
        json={"connected": True, "local_blocked": True, "clearance_seen": clearance},
    ).json()["blocked"]


def test_clearance_is_durable_and_cannot_clear_a_later_failure(tmp_path):
    journal = Journal(tmp_path / "journal.db")
    with journal.transaction() as db:
        db.execute("INSERT INTO blocked_printers VALUES ('desk')")
    journal.clear("desk", 1)
    assert not journal.blocked("desk")
    with journal.transaction() as db:
        db.execute("INSERT INTO blocked_printers VALUES ('desk')")
    restarted = Journal(tmp_path / "journal.db")
    restarted.clear("desk", 1)
    assert restarted.blocked("desk")
    restarted.clear("desk", 2)
    assert not restarted.blocked("desk")
