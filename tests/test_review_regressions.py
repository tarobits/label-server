"""Cross-layer regressions found during the AI-code consistency review."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from alembic import command
from alembic.config import Config
from conftest import create_test_app, install, job, profile
from fastapi.testclient import TestClient
from printer_factory import browser_printer
from sqlalchemy import select
from test_access import Policy
from test_brother import Transport
from test_fleet import device, fit, group, submit

from app.access import Action
from app.models import LabelCopy, LabelTemplate, PrinterDevice, PrintJob, TapeProfile
from app.printer.brother import BrotherPTP710BT, encode_raster
from app.render import render_job


def draft_body(tape):
    return {
        "request_key": "review-draft",
        "name": "Review draft",
        "template": "text",
        "expected_revision": 2,
        "tape_profile": tape["id"],
        "csv_text": "Text\nSaved\n",
        "mapping": {"text": "Text"},
        "rows": [{"source_row": 2}],
    }


def test_retired_waiting_work_does_not_block_new_registration(client):
    tape = profile(client, threshold=1, reminders=True)
    queued = job(client, tape["id"])
    with client.app.state.factory.begin() as session:
        session.get(PrinterDevice, "main").config = {"retired": True}
    second = device(client)
    assert second
    assert client.get(f"/api/jobs/{queued['id']}").json()["destination_id"] == "main"


def test_physical_selected_flush_holds_group_and_releases_cancelled_requests(client):
    tape = profile(client, threshold=1)
    second = device(client)
    dest = group(client, ["main", second])
    first_cart = fit(client, "main", tape)
    fit(client, second, tape)
    selected, unselected = submit(client, dest, tape), submit(client, dest, tape)
    response = client.post(
        f"/api/queue/print?printer_id=main&destination_id={dest}",
        json={"copy_ids": [selected["labels"][0]["id"]]},
    )
    assert response.status_code == 202, response.text
    assert (
        client.put(
            "/api/printer/active-tape?printer_id=main", json={"cartridge_id": None}
        ).status_code
        == 409
    )
    assert client.get(f"/api/status?printer_id={second}").json()["pending_flush"] is None
    workers = client.app.state.fleet.workers
    workers[second].tick()
    assert client.get(f"/api/jobs/{unselected['id']}").json()["status"] == "queued"
    client.delete(f"/api/jobs/{selected['id']}")
    assert client.get("/api/status?printer_id=main").json()["pending_flush"] is None
    assert (
        client.put(
            "/api/printer/active-tape?printer_id=main", json={"cartridge_id": None}
        ).status_code
        == 200
    )
    assert first_cart["id"]


def test_draft_prevents_profile_deletion_and_default_retry_survives_second_printer(client):
    tape = profile(client)
    body = draft_body(tape)
    first = client.post("/api/runs/prepare", json=body).json()["run"]
    assert client.delete(f"/api/tape-profiles/{tape['id']}").status_code == 409
    device(client)
    assert client.post("/api/runs/prepare", json=body).json()["run"]["id"] == first["id"]


@pytest.mark.parametrize("image", [False, True])
def test_default_job_retry_uses_receipt_destination(client, image):
    tape = profile(client)
    body = {"tape_profile": tape["id"], "data": {"text": "Repeat"}}
    path = "/api/jobs"
    if image:
        asset = client.post(
            "/api/image-assets",
            content=b'<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>',
        ).json()
        body = {"tape_profile": tape["id"], "image_asset": asset["id"]}
        path = "/api/image-jobs"
    headers = {"Idempotency-Key": "review:default"}
    first = client.post(path, json=body, headers=headers)
    assert first.status_code == 201, first.text
    second = device(client)
    retry = client.post(path, json=body, headers=headers)
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]
    assert (
        client.post(path, json={**body, "destination_id": second}, headers=headers).status_code
        == 409
    )


def test_reminder_episode_resets_when_each_destination_falls_below_threshold(client):
    tape = profile(client, threshold=3, reminders=True)
    second = device(client)
    first = submit(client, "main", tape, 3)
    submit(client, second, tape, 2)
    client.put(f"/api/tape-profiles/{tape['id']}/reminder", json={"action": "silence"})
    client.post("/api/queue/remove", json={"copy_ids": [first["labels"][0]["id"]]})
    saved = client.get("/api/tape-profiles").json()[0]
    assert not saved["reminder_silenced"]
    submit(client, second, tape)
    assert len(client.get("/api/notifications").json()) == 2


def test_offline_group_demand_alerts_and_clears_when_hardware_returns(client):
    tape = profile(client, threshold=1)
    dest = group(client, ["main"])
    fit(client, "main", tape)
    queued = submit(client, dest, tape)
    worker = client.app.state.fleet.workers["main"]
    worker.backend.connected = False
    worker.tick()
    assert client.get("/api/status").json()["blocker"] == "Printer disconnected"
    assert len(client.get("/api/notifications").json()) == 1
    worker.tick()
    assert len(client.get("/api/notifications").json()) == 1
    worker.backend.connected = True
    worker.tick()
    assert client.get("/api/status").json()["blocker"] is None
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"
    batch = client.get("/api/batches").json()[0]
    assert batch["finished_at"] >= batch["created_at"]


def test_invalid_persistent_configuration_is_visible_and_repairable(client):
    with client.app.state.factory.begin() as session:
        stored = session.get(PrinterDevice, "main")
        stored.driver, stored.config = "brother-pt-p710bt", {"feed_mm": 0}
    settings = client.app.state.settings
    client.__exit__(None, None, None)
    with TestClient(create_test_app(settings, start_worker=False)) as restarted:
        devices = restarted.get("/api/printers").json()
        assert len(devices) == 1 and devices[0]["configuration_error"]
        response = restarted.put("/api/printers/main", json={"name": "Repaired", "feed_mm": 2})
        assert response.status_code == 200, response.text
        assert restarted.get("/api/printers").json()[0]["configuration_error"] is None
        assert "main" in restarted.app.state.fleet.workers


def test_read_policy_csv_and_resolved_destination_authorization(client):
    policy = Policy(Action.WRITE)
    client.app.state.access_policy = policy
    assert client.post("/api/csv/parse", json={"csv_text": "Name\nOne"}).status_code == 200
    assert client.get("/api/status").status_code == 200
    assert policy.calls[-1][2].destination_id == "main"
    client.post("/api/queue/print")
    assert any(
        action == Action.PRINT and resource.destination_id == "main"
        for _, action, resource in policy.calls
    )


def test_job_length_schema_matches_renderer(client):
    tape = profile(client)
    assert (
        client.post(
            "/api/jobs",
            json={"tape_profile": tape["id"], "data": {"text": "Too long"}, "length_mm": 500},
        ).status_code
        == 422
    )
    assert (
        client.app.openapi()["components"]["schemas"]["JobInput"]["properties"]["length_mm"][
            "anyOf"
        ][0]["maximum"]
        == 300
    )


@pytest.mark.parametrize("path", ["/api/jobs", "/api/runs/prepare", "/api/preview"])
def test_rendering_does_not_hold_fleet_lock_and_rejects_concurrent_template_edit(
    client, monkeypatch, path
):
    import app.api
    import app.submissions

    tape = profile(client)
    entered, release = Event(), Event()
    module = app.api if path == "/api/preview" else app.submissions
    original = module.render_document

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "render_document", slow)
    body = {"tape_profile": tape["id"], "data": {"text": "Concurrent"}}
    if path == "/api/runs/prepare":
        body = draft_body(tape)
    elif path == "/api/preview":
        body = {"template_id": "text", "data": {"text": "Preview"}}
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, path, json=body)
        try:
            assert entered.wait(5)
            assert client.app.state.fleet.lock.acquire(timeout=1)
            try:
                with client.app.state.factory.begin() as session:
                    session.get(LabelTemplate, "text").archived = True
            finally:
                client.app.state.fleet.lock.release()
            assert client.get("/api/status").status_code == 200
        finally:
            release.set()
        response = future.result(5)
    assert response.status_code == (200 if path == "/api/preview" else 409), response.text
    assert client.get("/api/jobs").json() == []


def test_queue_renders_without_fleet_lock_but_preserves_reservation(client, monkeypatch):
    import app.queue

    tape = profile(client, threshold=1)
    install(client, tape["id"])
    queued = job(client, tape["id"])
    entered, release = Event(), Event()
    original = app.queue.render_job

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(app.queue, "render_job", slow)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.app.state.fleet.workers["main"].tick)
        try:
            assert entered.wait(5)
            assert client.get("/api/status").json()["printing"]
            assert client.delete(f"/api/jobs/{queued['id']}").status_code == 409
            assert (
                client.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code
                == 409
            )
        finally:
            release.set()
        future.result(5)
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"


def test_browser_backend_preserves_capabilities_and_rejects_unknown_drivers():
    definition, backend = browser_printer(
        "brother-pt-p710bt", {"resolution": "high", "feed_mm": 3, "cut_each": False}
    )
    assert definition.capabilities.dpi_x == 360
    assert 3.5 in definition.capabilities.supported_widths_mm
    assert not backend.plan_batch([]).cut_each
    with pytest.raises(ValueError):
        browser_printer("imaginary-driver", {})


def test_narrow_width_is_physical_and_migration_preserves_frozen_raster(client):
    tape = profile(client, width=3.5)
    queued = job(client, tape["id"])
    with client.app.state.factory.begin() as session:
        saved = session.get(PrintJob, queued["id"])
        snapshot = {
            **saved.template_snapshot,
            "render_spec": {**saved.template_snapshot["render_spec"], "dpi_x": 360},
        }
        saved.width_mm = 4
        session.get(TapeProfile, tape["id"]).width_mm = 4
        snapshot["document"] = {**snapshot["document"], "width_mm": 4}
        snapshot["render_spec"].pop("stretch_canvas", None)
        snapshot["render_spec"].pop("supported_widths_mm", None)
        saved.template_snapshot = snapshot
        queued["template_snapshot"] = snapshot
        label = session.scalar(select(LabelCopy).where(LabelCopy.job_id == saved.id))
        before = render_job(saved, label)
    config = Config("alembic.ini")
    config.attributes["database_url"] = client.app.state.settings.database_url
    command.downgrade(config, "f31a729de840")
    command.upgrade(config, "head")
    command.check(config)
    with client.app.state.factory() as session:
        saved = session.get(PrintJob, queued["id"])
        label = session.scalar(select(LabelCopy).where(LabelCopy.job_id == saved.id))
        after = render_job(saved, label)
        assert session.get(TapeProfile, tape["id"]).width_mm == 3.5
        assert saved.template_snapshot == queued["template_snapshot"]
    assert after.raster == before.raster and after.pixel_height == before.pixel_height
    assert after.tape_width_mm == 3.5 and after.canvas_width_mm == 4
    assert encode_raster(after)
    assert BrotherPTP710BT(Transport(width=4)).get_status().tape_width_mm == 3.5


def test_cancel_pending_flush_preserves_jobs_and_hold(client):
    tape = profile(client)
    install(client, tape["id"])
    queued = job(client, tape["id"])
    pending = client.post("/api/queue/print", json={"copy_ids": [queued["labels"][0]["id"]]}).json()
    assert client.delete(f"/api/queue/flush/{pending['id']}").status_code == 200
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"
    status = client.get("/api/status").json()
    assert status["pending_flush"] is None and status["automatic_printing_held"]
    assert client.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code == 200


def test_image_deleted_during_preparation_does_not_get_dangling_reference(client, monkeypatch):
    import app.submissions

    tape = profile(client)
    asset = client.post(
        "/api/image-assets",
        content=b'<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>',
    ).json()
    entered, release = Event(), Event()
    original = app.submissions.render_document

    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(app.submissions, "render_document", slow)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(
            client.post,
            "/api/image-jobs",
            json={"image_asset": asset["id"], "tape_profile": tape["id"]},
        )
        try:
            assert entered.wait(5)
            assert client.delete(f"/api/image-assets/{asset['id']}/permanent").status_code == 200
        finally:
            release.set()
        assert future.result(5).status_code == 409
    assert client.get("/api/jobs").json() == []
