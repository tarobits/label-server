from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from conftest import install, job, profile
from fastapi.testclient import TestClient

from app.models import Batch, BatchItem, LabelCopy, State
from app.printer.base import PrintNotStarted, PrintResult
from app.queue import QueueWorker


def test_nine_wait_tenth_prints_one_batch(client: TestClient) -> None:
    tape = profile(client)
    cartridge = install(client, tape["id"])
    worker = client.app.state.worker
    for _ in range(9):
        job(client, tape["id"])
        worker.tick()
    assert worker.backend.batches == []
    job(client, tape["id"])
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert len(worker.backend.batches[0]) == 10
    assert all(j["status"] == "printed" for j in client.get("/api/jobs").json())
    assert (
        client.get("/api/cartridges").json()[0]["remaining_mm"] == cartridge["remaining_mm"] - 620
    )


def test_profiles_copies_and_manual_flush(client: TestClient) -> None:
    white, yellow = profile(client), profile(client, "Yellow")
    install(client, white["id"])
    job(client, white["id"], 10)
    yellow_job = job(client, yellow["id"], 3)
    worker = client.app.state.worker
    worker.tick()
    assert len(worker.backend.batches[0]) == 10
    assert client.get(f"/api/jobs/{yellow_job['id']}").json()["status"] == "queued"
    install(client, yellow["id"])
    assert client.post("/api/queue/print").status_code == 202
    late = job(client, yellow["id"])
    worker.tick()
    assert [len(b) for b in worker.backend.batches] == [10, 3]
    assert client.get(f"/api/jobs/{late['id']}").json()["status"] == "queued"


def test_threshold_edit_is_effective(client: TestClient) -> None:
    tape = profile(client)
    install(client, tape["id"])
    job(client, tape["id"], 3)
    worker = client.app.state.worker
    worker.tick()
    assert not worker.backend.batches
    response = client.put(
        f"/api/tape-profiles/{tape['id']}",
        json={
            "name": tape["name"],
            "width_mm": 24,
            "auto_print_threshold": 3,
        },
    )
    assert response.status_code == 200
    worker.tick()
    assert len(worker.backend.batches[0]) == 3


@pytest.mark.parametrize("width,connected", [(None, True), (12, True), (24, False)])
def test_width_and_connection_gate(client: TestClient, width: int | None, connected: bool) -> None:
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    job(client, tape["id"])
    worker = client.app.state.worker
    worker.backend.width_mm, worker.backend.connected = width, connected
    worker.tick()
    worker.tick()
    assert not worker.backend.batches
    assert len(client.get("/api/notifications").json()) == 1
    worker.backend.width_mm, worker.backend.connected = 24, True
    worker.tick()
    assert len(worker.backend.batches) == 1


def test_interrupted_batch_review_preserves_confirmed_copies(client: TestClient) -> None:
    tape = profile(client, threshold=3)
    install(client, tape["id"])
    item = job(client, tape["id"], 3)
    worker = client.app.state.worker
    worker.backend.fail_after = 1
    worker.tick()
    batch = client.get("/api/batches").json()[0]
    assert batch["state"] == "needs_review"
    assert client.get("/api/cartridges").json()[0]["consumption_uncertain"]
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert client.post("/api/queue/print").status_code == 409
    assert client.delete(f"/api/jobs/{item['id']}").status_code == 409
    assert client.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code == 409
    assert (
        client.post(
            f"/api/batches/{batch['id']}/review", json={"decisions": {}, "consumed_mm": 60}
        ).status_code
        == 409
    )
    labels = client.get(f"/api/jobs/{item['id']}").json()["labels"]
    response = client.post(
        f"/api/batches/{batch['id']}/review",
        json={
            "decisions": {labels[1]["id"]: "queued", labels[2]["id"]: "cancelled"},
            "consumed_mm": 60,
        },
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/cartridges").json()[0]["remaining_mm"] == 7940
    assert (
        client.post(
            f"/api/batches/{batch['id']}/review", json={"decisions": {}, "consumed_mm": 60}
        ).status_code
        == 409
    )
    worker.backend.fail_after = None
    client.post("/api/queue/print")
    worker.tick()
    assert len(worker.backend.batches[1]) == 1
    assert worker.backend.batches[1][0].copy_id == labels[1]["id"]


def test_restart_recovers_inflight_intent_once(client: TestClient) -> None:
    tape = profile(client)
    cartridge = install(client, tape["id"])
    item = job(client, tape["id"])
    factory = client.app.state.factory
    with factory.begin() as session:
        batch = Batch(cartridge_id=cartridge["id"], estimated_mm=60)
        session.add(batch)
        session.flush()
        copy = session.get(LabelCopy, item["labels"][0]["id"])
        copy.state = State.PRINTING
        session.add(BatchItem(batch_id=batch.id, copy_id=copy.id, position=0))
    worker = QueueWorker(factory, client.app.state.worker.backend)
    worker.recover()
    worker.recover()
    worker.tick()
    assert not worker.backend.batches
    assert client.get("/api/batches").json()[0]["state"] == "needs_review"
    assert len(client.get("/api/notifications").json()) == 1


def test_no_write_failure_keeps_manual_flush(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tape = profile(client)
    install(client, tape["id"])
    job(client, tape["id"])
    worker = client.app.state.worker
    client.post("/api/queue/print")
    original = worker.backend.print_batch

    def fail(labels: object) -> PrintResult:
        raise PrintNotStarted("Disconnected before write")

    monkeypatch.setattr(worker.backend, "print_batch", fail)
    worker.tick()
    assert client.get("/api/jobs").json()[0]["status"] == "queued"
    monkeypatch.setattr(worker.backend, "print_batch", original)
    worker.tick()
    assert len(worker.backend.batches) == 1


def test_batch_frozen_and_printer_serialized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    job(client, tape["id"])
    worker = client.app.state.worker
    entered, release = Event(), Event()
    original = worker.backend.print_batch

    def slow(labels: object) -> PrintResult:
        entered.set()
        assert release.wait(5)
        return original(labels)

    monkeypatch.setattr(worker.backend, "print_batch", slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker.tick)
        try:
            assert entered.wait(5)
            job(client, tape["id"])
            second = pool.submit(worker.tick)
            assert (
                client.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code
                == 409
            )
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert [len(b) for b in worker.backend.batches] == [1, 1]


def test_snapshot_validation_and_shortage_warning(client: TestClient) -> None:
    tape = profile(client, threshold=1)
    install(client, tape["id"], remaining=10)
    item = job(client, tape["id"])
    assert item["template_snapshot"]["revision"] == 2
    assert (
        client.put(
            f"/api/tape-profiles/{tape['id']}", json={"name": "Changed", "width_mm": 12}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/jobs", json={"tape_profile": tape["id"], "copies": 0, "data": {"text": "x"}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/jobs",
            json={"tape_profile": tape["id"], "template": "../../secret", "data": {"text": "x"}},
        ).status_code
        == 422
    )
    client.app.state.worker.tick()
    assert client.get("/api/batches").json()[0]["shortage_warning"]
    assert client.get("/api/cartridges").json()[0]["remaining_mm"] == 0


def test_cancelled_jobs_do_not_print(client: TestClient) -> None:
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    item = job(client, tape["id"])
    assert client.delete(f"/api/jobs/{item['id']}").json()["status"] == "cancelled"
    client.app.state.worker.tick()
    assert not client.app.state.worker.backend.batches


def test_profile_filter_combines_with_status_before_pagination(client: TestClient) -> None:
    first = profile(client, name="White")
    second = profile(client, name="Yellow")
    one = job(client, first["id"])
    two = job(client, second["id"])
    cancelled = job(client, first["id"])
    client.delete(f"/api/jobs/{cancelled['id']}")
    response = client.get(
        "/api/jobs", params={"profile_id": first["id"], "copy_state": "queued", "limit": 1}
    )
    assert [j["id"] for j in response.json()] == [one["id"]]
    assert (
        client.get(
            "/api/jobs", params={"profile_id": first["id"], "copy_state": "queued", "offset": 1}
        ).json()
        == []
    )
    assert {
        j["id"] for j in client.get("/api/jobs", params={"profile_id": first["id"]}).json()
    } == {one["id"], cancelled["id"]}
    assert [
        j["id"] for j in client.get("/api/jobs", params={"profile_id": second["id"]}).json()
    ] == [two["id"]]
    assert len(client.get("/api/jobs").json()) == 3


def test_selected_flush_prints_only_selection_and_holds_remainder(client: TestClient) -> None:
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    first = job(client, tape["id"], 2)
    second = job(client, tape["id"])
    selected = [first["labels"][1]["id"], second["labels"][0]["id"]]
    response = client.post("/api/queue/print", json={"copy_ids": selected[::-1]})
    assert response.status_code == 202, response.text
    assert response.json()["copy_ids"] == selected
    worker = client.app.state.worker
    worker.tick()
    worker.tick()
    assert [[label.copy_id for label in batch] for batch in worker.backend.batches] == [selected]
    assert client.get("/api/status").json()["automatic_printing_held"]
    assert client.get(f"/api/jobs/{first['id']}").json()["labels"][0]["state"] == "queued"


def test_invalid_selection_is_atomic_and_does_not_hold_printing(client: TestClient) -> None:
    tape = profile(client)
    other = profile(client, name="Other")
    install(client, tape["id"])
    valid = job(client, tape["id"])["labels"][0]["id"]
    incompatible = job(client, other["id"])["labels"][0]["id"]
    assert client.post("/api/queue/print", json={"copy_ids": []}).status_code == 422
    assert client.post("/api/queue/print", json={"copy_ids": [valid, valid]}).status_code == 422
    for bad in [incompatible, "missing"]:
        assert client.post("/api/queue/print", json={"copy_ids": [valid, bad]}).status_code == 409
    status = client.get("/api/status").json()
    assert not status["automatic_printing_held"] and status["pending_flush"] is None


def test_remove_selection_across_tapes_preserves_other_copies(client: TestClient) -> None:
    first = job(client, profile(client)["id"], 2)
    second = job(client, profile(client, name="Other")["id"])
    ids = [first["labels"][0]["id"], second["labels"][0]["id"]]
    response = client.post("/api/queue/remove", json={"copy_ids": ids})
    assert response.status_code == 200
    assert response.json()["removed_copies"] == 2
    assert [c["state"] for c in client.get(f"/api/jobs/{first['id']}").json()["labels"]] == [
        "cancelled",
        "queued",
    ]
    remaining = first["labels"][1]["id"]
    assert (
        client.post("/api/queue/remove", json={"copy_ids": [remaining, ids[0]]}).status_code == 409
    )
    assert client.get(f"/api/jobs/{first['id']}").json()["labels"][1]["state"] == "queued"
    assert client.post("/api/queue/remove", json={"copy_ids": []}).status_code == 422
