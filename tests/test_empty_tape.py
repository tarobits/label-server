import pytest
from conftest import install, job, profile
from sqlalchemy import select
from test_fleet import device, fit, group, job_state, submit

from app.models import Batch, Cartridge, LabelCopy, Notification, PrinterState, PrintRun, State
from app.queue import EMPTY_TAPE_BLOCKER, QueueWorker


def notices(client):
    with client.app.state.factory() as session:
        return list(session.scalars(select(Notification).where(Notification.kind == "empty_tape")))


def correct(client, cartridge, remaining):
    response = client.put(
        f"/api/cartridges/{cartridge['id']}/remaining", json={"remaining_mm": remaining}
    )
    assert response.status_code == 200, response.text


def test_empty_tape_blocks_automatic_before_rendering_and_survives_worker_restart(
    client, monkeypatch
):
    tape = profile(client, threshold=1)
    cartridge = install(client, tape["id"], remaining=0)
    queued = job(client, tape["id"], copies=3)

    def no_render(*args, **kwargs):
        pytest.fail("Empty tape must prevent automatic raster preparation")

    monkeypatch.setattr("app.queue.render_job", no_render)
    worker = client.app.state.fleet.workers["main"]
    worker.tick()
    worker.tick()
    restarted = QueueWorker(
        worker.factory,
        worker.backend,
        worker.fonts,
        worker.images,
        printer_id="main",
        lock=worker.lock,
        choose=worker.choose,
        enforce_job_access=worker.enforce_job_access,
    )
    restarted.tick()
    assert not worker.backend.batches
    assert job_state(client, queued) == "queued"
    with worker.factory() as session:
        assert not list(session.scalars(select(Batch)))
        assert all(copy.state == State.QUEUED for copy in session.scalars(select(LabelCopy)))
        assert session.get(Cartridge, cartridge["id"]).remaining_mm == 0
        state = session.scalar(select(PrinterState))
        assert state.blocker == EMPTY_TAPE_BLOCKER
        assert not state.automatic_printing_held
    alerts = notices(client)
    assert len(alerts) == 1
    assert alerts[0].recipient_id == "administrators"


@pytest.mark.parametrize("replace", [False, True])
def test_refill_or_replacement_resumes_automatic_printing_without_manual_hold(client, replace):
    tape = profile(client, threshold=1)
    cartridge = install(client, tape["id"], remaining=0)
    queued = job(client, tape["id"])
    worker = client.app.state.fleet.workers["main"]
    worker.tick()
    assert len(notices(client)) == 1
    if replace:
        cartridge = install(client, tape["id"])
    else:
        correct(client, cartridge, 8000)
    worker.tick()
    assert job_state(client, queued) == "printed"
    status = client.get("/api/status").json()
    assert status["blocker"] is None
    assert not status["automatic_printing_held"]
    with worker.factory() as session:
        assert session.get(Cartridge, cartridge["id"]).remaining_mm == 7920
        assert session.scalar(select(PrinterState)).empty_alert_cartridge_id is None
    assert len(notices(client)) == 1
    # A later depletion creates one new episode, not an alert on every tick.
    correct(client, cartridge, 0)
    worker.tick()
    worker.tick()
    assert len(notices(client)) == 2


def test_automatic_group_uses_nonempty_matching_member(client):
    tape = profile(client, threshold=1)
    second = device(client)
    destination = group(client, ["main", second])
    empty = fit(client, "main", tape)
    correct(client, empty, 0)
    fit(client, second, tape)
    workers = client.app.state.fleet.workers
    # Refresh readiness before group routing considers either printer.
    for worker in workers.values():
        worker.tick()
    queued = submit(client, destination, tape)
    for worker in workers.values():
        worker.tick()
    assert job_state(client, queued) == "printed"
    assert not workers["main"].backend.batches
    assert len(workers[second].backend.batches) == 1
    assert client.get("/api/batches").json()[0]["printer_id"] == second
    with client.app.state.factory() as session:
        assert session.get(Cartridge, empty["id"]).remaining_mm == 0
    assert len(notices(client)) == 1


def test_pinned_csv_run_waits_for_its_empty_printer_instead_of_moving(client):
    tape = profile(client, threshold=1)
    second = device(client)
    destination = group(client, ["main", second])
    empty = fit(client, "main", tape)
    correct(client, empty, 0)
    fit(client, second, tape)
    response = client.post(
        "/api/runs/prepare",
        json={
            "destination_id": destination,
            "request_key": "empty-pinned-run",
            "name": "Pinned run",
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
    submitted = client.post(f"/api/runs/{run['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    with client.app.state.factory.begin() as session:
        session.get(PrintRun, run["id"]).assigned_printer_id = "main"
    workers = client.app.state.fleet.workers
    for worker in workers.values():
        worker.tick()
    assert all(not worker.backend.batches for worker in workers.values())
    with client.app.state.factory() as session:
        assert session.get(PrintRun, run["id"]).assigned_printer_id == "main"
        assert all(copy.state == State.QUEUED for copy in session.scalars(select(LabelCopy)))
    correct(client, empty, 8000)
    workers["main"].tick()
    assert len(workers["main"].backend.batches) == 1
    assert not workers[second].backend.batches


@pytest.mark.parametrize("path", ["/api/queue/print", "/api/destinations/main/print"])
def test_manual_acknowledgment_can_print_empty_estimated_tape_without_repeating_alert(client, path):
    tape = profile(client, threshold=1)
    install(client, tape["id"], remaining=0)
    queued = job(client, tape["id"])
    worker = client.app.state.fleet.workers["main"]
    worker.tick()
    warning = client.post(path)
    assert warning.status_code == 409, warning.text
    detail = warning.json()["detail"]
    assert detail["code"] == "tape_shortage"
    response = client.post(path, headers={"X-Tape-Shortage-Confirmation": detail["confirmation"]})
    assert response.status_code == 202, response.text
    worker.tick()
    assert job_state(client, queued) == "printed"
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert len(notices(client)) == 1
    assert client.get("/api/status").json()["blocker"] == EMPTY_TAPE_BLOCKER


def test_successful_consumption_to_zero_alerts_and_blocks_the_next_automatic_batch(client):
    tape = profile(client, threshold=1)
    install(client, tape["id"], remaining=80)
    printed = job(client, tape["id"])
    worker = client.app.state.fleet.workers["main"]
    worker.tick()
    assert job_state(client, printed) == "printed"
    assert len(notices(client)) == 1
    queued = job(client, tape["id"])
    worker.tick()
    assert job_state(client, queued) == "queued"
    assert len(worker.backend.batches) == 1
    assert len(notices(client)) == 1


def test_review_consumption_to_zero_alerts_before_the_next_worker_tick(client):
    tape = profile(client, threshold=1)
    install(client, tape["id"], remaining=80)
    queued = job(client, tape["id"])
    worker = client.app.state.fleet.workers["main"]
    worker.backend.fail_after = 0
    worker.tick()
    assert not notices(client)
    batch = client.get("/api/batches").json()[0]
    response = client.post(
        f"/api/batches/{batch['id']}/review",
        json={
            "decisions": {label["id"]: "queued" for label in queued["labels"]},
            "consumed_mm": 80,
        },
    )
    assert response.status_code == 200, response.text
    assert len(notices(client)) == 1
    worker.tick()
    assert job_state(client, queued) == "queued"
    assert len(worker.backend.batches) == 1
    assert len(notices(client)) == 1
