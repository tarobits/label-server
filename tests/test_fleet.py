from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from conftest import create_test_app as create_app
from conftest import profile
from fastapi.testclient import TestClient

from app.models import PrintRun
from app.printer.base import PrintNotStarted


def device(client, name="Second"):
    response = client.post("/api/printers", json={"name": name, "driver": "mock"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def group(client, ids, name="Station"):
    response = client.post("/api/printer-groups", json={"name": name, "printer_ids": ids})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def fit(client, identifier, tape):
    cartridge = client.post(
        "/api/cartridges",
        json={"profile_id": tape["id"], "name": identifier, "nominal_length_mm": 8000},
    ).json()
    response = client.put(
        f"/api/printer/active-tape?printer_id={identifier}", json={"cartridge_id": cartridge["id"]}
    )
    assert response.status_code == 200, response.text
    client.put(
        f"/api/printer/mock?printer_id={identifier}",
        json={"connected": True, "tape_width_mm": tape["width_mm"]},
    )
    return cartridge


def submit(client, dest, tape, copies=1):
    response = client.post(
        "/api/jobs",
        json={
            "destination_id": dest,
            "tape_profile": tape["id"],
            "data": {"text": dest},
            "copies": copies,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def job_state(client, job):
    return client.get(f"/api/jobs/{job['id']}").json()["status"]


@pytest.mark.parametrize("manual", [False, True])
def test_no_start_failure_holds_group_without_automatic_failover(client, monkeypatch, manual):
    tape = profile(client, threshold=1)
    second = device(client)
    dest = group(client, ["main", second])
    fit(client, "main", tape)
    fit(client, second, tape)
    workers = client.app.state.fleet.workers
    for worker in workers.values():
        worker.tick()
    submitted = submit(client, dest, tape, copies=2)
    if manual:
        assert client.post(f"/api/destinations/{dest}/print").status_code == 202

    def fail(labels):
        raise PrintNotStarted("Rejected before transmission")

    monkeypatch.setattr(workers["main"].backend, "print_batch", fail)
    workers["main"].tick()
    workers["main"].backend.connected = False
    for _ in range(3):
        for worker in workers.values():
            worker.tick()
    assert job_state(client, submitted) == "queued"
    assert len(client.get("/api/batches").json()) == 1
    destination = next(
        item for item in client.get("/api/destinations").json() if item["id"] == dest
    )
    assert destination["automatic_printing_held"]
    assert not workers[second].backend.batches
    # Only this logical destination is paused; unrelated work can still print.
    other = submit(client, second, tape)
    workers[second].tick()
    assert job_state(client, other) == "printed"
    assert job_state(client, submitted) == "queued"
    assert client.post(f"/api/destinations/{dest}/print").status_code == 202
    workers[second].tick()
    assert job_state(client, submitted) == "printed"


def test_group_matches_exact_profile_and_missing_tape_waits(client):
    a, b, missing = [
        profile(client, name=name, threshold=1) for name in ("White", "Yellow", "Blue")
    ]
    second = device(client)
    dest = group(client, ["main", second])
    fit(client, "main", a)
    fit(client, second, b)
    jobs = [submit(client, dest, tape) for tape in (a, b, missing)]
    fleet = client.app.state.fleet
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda worker: worker.tick(), fleet.workers.values()))
    assert [job_state(client, job) for job in jobs] == ["printed", "printed", "queued"]
    batches = client.get("/api/batches").json()
    assert {batch["printer_id"] for batch in batches} == {"main", second}
    assert all(len(worker.backend.batches) == 1 for worker in fleet.workers.values())


def test_same_profile_reserves_once_with_stable_preference_and_per_destination_threshold(client):
    tape = profile(client, threshold=2)
    second = device(client)
    dest = group(client, ["main", second])
    fit(client, "main", tape)
    fit(client, second, tape)
    direct = submit(client, second, tape)
    first = submit(client, dest, tape)
    workers = client.app.state.fleet.workers
    for worker in workers.values():
        worker.tick()
    assert job_state(client, direct) == job_state(client, first) == "queued"
    another = submit(client, dest, tape)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda worker: worker.tick(), reversed(list(workers.values()))))
    assert job_state(client, first) == job_state(client, another) == "printed"
    assert job_state(client, direct) == "queued"
    assert len(workers["main"].backend.batches) == 1
    assert len(workers[second].backend.batches) == 0


def test_interrupted_printer_does_not_block_others_or_retry_uncertain_copies(client):
    tape = profile(client, threshold=1)
    second = device(client)
    dest = group(client, ["main", second])
    fit(client, "main", tape)
    fit(client, second, tape)
    workers = client.app.state.fleet.workers
    workers["main"].backend.fail_after = 0
    first = submit(client, dest, tape)
    workers["main"].tick()
    second_job = submit(client, dest, tape)
    workers[second].tick()
    assert job_state(client, first) == "needs_review"
    assert job_state(client, second_job) == "printed"
    assert not client.get(f"/api/status?printer_id={second}").json()["needs_review"]
    assert (
        client.put(
            f"/api/printer/active-tape?printer_id={second}", json={"cartridge_id": None}
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/printer/active-tape?printer_id=main", json={"cartridge_id": None}
        ).status_code
        == 409
    )


def test_cartridge_exclusivity_and_group_manual_flush(client):
    tape = profile(client, threshold=20)
    second = device(client)
    dest = group(client, ["main", second])
    cartridge = fit(client, "main", tape)
    assert (
        client.put(
            f"/api/printer/active-tape?printer_id={second}", json={"cartridge_id": cartridge["id"]}
        ).status_code
        == 409
    )
    fit(client, second, tape)
    selected, other = [submit(client, dest, tape) for _ in range(2)]
    response = client.post(
        f"/api/destinations/{dest}/print", json={"copy_ids": [selected["labels"][0]["id"]]}
    )
    assert response.status_code == 202, response.text
    # The other worker cannot steal copies reserved for the requested printer.
    client.app.state.fleet.workers[second].tick()
    client.app.state.fleet.workers["main"].tick()
    assert job_state(client, selected) == "printed"
    assert job_state(client, other) == "queued"
    assert next(d for d in client.get("/api/destinations").json() if d["id"] == dest)[
        "automatic_printing_held"
    ]


def test_csv_run_stays_on_assigned_printer_after_review(client):
    tape = profile(client, threshold=1)
    second = device(client)
    dest = group(client, ["main", second])
    fit(client, "main", tape)
    fit(client, second, tape)
    response = client.post(
        "/api/runs/prepare",
        json={
            "destination_id": dest,
            "request_key": "group-run",
            "name": "Run",
            "template": "text",
            "expected_revision": 2,
            "tape_profile": tape["id"],
            "csv_text": "Text\nOne\nTwo",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2}, {"source_row": 3}],
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    jobs = client.post(f"/api/runs/{run['id']}/submit").json()["jobs"]
    client.app.state.fleet.workers["main"].backend.fail_after = 1
    client.app.state.fleet.workers["main"].tick()
    batch = client.get("/api/batches").json()[0]
    detail = client.get(f"/api/batches/{batch['id']}").json()
    pending = {
        item["copy_id"]: "queued" for item in detail["items"] if item["outcome"] == "needs_review"
    }
    assert (
        client.post(
            f"/api/batches/{batch['id']}/review", json={"decisions": pending, "consumed_mm": 65}
        ).status_code
        == 200
    )
    client.app.state.fleet.workers[second].tick()
    assert job_state(client, jobs[1]) == "queued"
    assert (
        client.post(
            f"/api/queue/print?printer_id={second}&destination_id={dest}",
            json={"copy_ids": list(pending)},
        ).status_code
        == 409
    )
    client.app.state.fleet.workers["main"].tick()
    assert job_state(client, jobs[1]) == "printed"
    with client.app.state.factory() as session:
        assert session.get(PrintRun, run["id"]).assigned_printer_id == "main"


def test_physical_prints_can_overlap_without_holding_database_lock(client):
    tape = profile(client, threshold=1)
    second = device(client)
    fit(client, "main", tape)
    fit(client, second, tape)
    first, other = submit(client, "main", tape), submit(client, second, tape)
    started, release = Event(), Event()
    backend = client.app.state.fleet.workers["main"].backend
    original = backend.print_batch

    def slow(labels):
        started.set()
        assert release.wait(5)
        return original(labels)

    backend.print_batch = slow
    with ThreadPoolExecutor(2) as pool:
        task = pool.submit(client.app.state.fleet.workers["main"].tick)
        try:
            assert started.wait(5)
            client.app.state.fleet.workers[second].tick()
            assert job_state(client, other) == "printed"
            assert job_state(client, first) == "printing"
        finally:
            release.set()
        task.result()


def test_missing_tape_reminders_consider_every_group_member(client):
    tape = profile(client, threshold=1, reminders=True)
    second = device(client)
    dest = group(client, ["main", second])
    fit(client, second, tape)
    submit(client, dest, tape)
    assert client.get("/api/notifications").json() == []
    client.put(f"/api/printer/active-tape?printer_id={second}", json={"cartridge_id": None})
    notices = client.get("/api/notifications").json()
    assert len(notices) == 1 and "Station" in notices[0]["message"]


def test_registrations_groups_and_installed_cartridges_survive_restart(client):
    tape = profile(client)
    second = device(client)
    dest = group(client, ["main", second])
    cartridge = fit(client, second, tape)
    client.put(f"/api/destinations/{dest}/automatic-printing", json={"held": True})
    settings = client.app.state.settings
    client.__exit__(None, None, None)
    with TestClient(create_app(settings, start_worker=False)) as restarted:
        assert second in restarted.app.state.fleet.workers
        assert (
            restarted.get(f"/api/status?printer_id={second}").json()["active_cartridge_id"]
            == cartridge["id"]
        )
        assert next(d for d in restarted.get("/api/destinations").json() if d["id"] == dest)[
            "automatic_printing_held"
        ]


def test_reserved_group_flush_waits_for_its_printer_and_cannot_move_to_new_preference(client):
    tape = profile(client, threshold=10)
    second = device(client)
    dest = group(client, ["main", second])
    fit(client, "main", tape)
    fit(client, second, tape)
    client.put("/api/printer/mock?printer_id=main", json={"connected": False, "tape_width_mm": 24})
    job = submit(client, dest, tape)
    assert client.post(f"/api/destinations/{dest}/print").status_code == 202
    client.put("/api/printer/mock?printer_id=main", json={"connected": True, "tape_width_mm": 24})
    client.app.state.fleet.workers["main"].tick()
    assert job_state(client, job) == "queued"
    client.app.state.fleet.workers[second].tick()
    assert job_state(client, job) == "printed"
    assert not client.app.state.fleet.workers["main"].backend.batches


def test_group_controls_validate_membership_and_do_not_split_pending_work(client):
    tape = profile(client)
    second = device(client)
    assert (
        client.post(
            "/api/printer-groups", json={"name": "Bad", "printer_ids": ["main", "main"]}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/printer-groups", json={"name": "Missing", "printer_ids": ["missing"]}
        ).status_code
        == 404
    )
    registered = client.post(
        "/api/printers",
        json={"name": "Physical", "driver": "brother-pt-p710bt", "usb_serial": "TEST-SERIAL"},
    )
    assert registered.status_code == 201
    assert (
        client.post(
            "/api/printers",
            json={"name": "Duplicate", "driver": "brother-pt-p710bt", "usb_serial": "TEST-SERIAL"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/printer-groups",
            json={"name": "Mixed geometry", "printer_ids": ["main", registered.json()["id"]]},
        ).status_code
        == 422
    )
    dest = group(client, ["main", second])
    submit(client, dest, tape)
    assert (
        client.put(
            f"/api/printer-groups/{dest}", json={"name": "Station", "printer_ids": [second]}
        ).status_code
        == 409
    )


def test_legacy_idempotency_receipts_still_match_and_other_destination_conflicts(client):
    import hashlib
    import json

    from app.models import JobSubmission

    tape = profile(client)
    body = {
        "template": "text",
        "tape_profile": tape["id"],
        "copies": 1,
        "length_mm": None,
        "data": {"text": "Before upgrade"},
    }
    job = client.post("/api/jobs", json=body).json()
    with client.app.state.factory.begin() as session:
        session.add(
            JobSubmission(
                owner_id=job["owner_id"],
                request_key="legacy",
                request_hash=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
                job_id=job["id"],
            )
        )
    assert (
        client.post("/api/jobs", json=body, headers={"Idempotency-Key": "legacy"}).json()["id"]
        == job["id"]
    )
    second = device(client)
    assert (
        client.post(
            "/api/jobs",
            json={**body, "destination_id": second},
            headers={"Idempotency-Key": "legacy"},
        ).status_code
        == 409
    )


def test_manual_requests_cannot_reserve_same_copy_on_two_printers(client):
    tape = profile(client)
    second = device(client)
    dest = group(client, ["main", second])
    fit(client, "main", tape)
    fit(client, second, tape)
    job = submit(client, dest, tape)
    selection = {"copy_ids": [job["labels"][0]["id"]]}
    assert (
        client.post(
            f"/api/queue/print?printer_id=main&destination_id={dest}", json=selection
        ).status_code
        == 202
    )
    assert (
        client.post(
            f"/api/queue/print?printer_id={second}&destination_id={dest}", json=selection
        ).status_code
        == 409
    )
    client.app.state.fleet.workers[second].tick()
    client.app.state.fleet.workers["main"].tick()
    assert job_state(client, job) == "printed"


def test_upgrade_preserves_populated_single_printer_database(client, monkeypatch):
    monkeypatch.setenv("LABEL_PRINTER_BACKEND", "brother-pt-p710bt")
    from alembic import command
    from alembic.config import Config

    tape = profile(client, threshold=1)
    cartridge = fit(client, "main", tape)
    printed = submit(client, "main", tape)
    client.app.state.fleet.workers["main"].tick()
    client.put("/api/printer/automatic-printing", json={"held": True})
    queued = submit(client, "main", tape)
    flush = client.post("/api/queue/print").json()
    remaining = client.get("/api/cartridges").json()[0]["remaining_mm"]
    settings = client.app.state.settings
    from printer_factory import browser_printer

    from app.models import PrinterDevice

    with client.app.state.factory.begin() as session:
        device = session.get(PrinterDevice, "main")
        device.driver = "brother-pt-p710bt"
    client.__exit__(None, None, None)
    config = Config("alembic.ini")
    config.attributes["database_url"] = settings.database_url
    # Recreate the preceding schema with real jobs, history and a pending flush.
    command.downgrade(config, "d804a91c3044")
    command.upgrade(config, "head")
    with TestClient(
        create_app(settings, start_worker=False, backend_factory=browser_printer)
    ) as upgraded:
        state = upgraded.get("/api/status").json()
        assert state["printer_id"] == "main"
        assert state["active_cartridge_id"] == cartridge["id"]
        assert state["automatic_printing_held"]
        assert state["pending_flush"] == flush["id"]
        assert upgraded.get("/api/cartridges").json()[0]["remaining_mm"] == remaining
        assert job_state(upgraded, printed) == "printed"
        assert job_state(upgraded, queued) == "queued"
        assert upgraded.get("/api/batches").json()[0]["printer_id"] == "main"
        upgraded.app.state.fleet.workers["main"].tick()
        assert job_state(upgraded, queued) == "printed"
