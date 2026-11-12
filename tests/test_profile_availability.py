from concurrent.futures import ThreadPoolExecutor
from threading import Event

from alembic import command
from alembic.config import Config
from conftest import install, profile
from sqlalchemy import text
from test_access_security import accounts as accounts
from test_image_jobs import upload
from test_runs import run_body

from app import submissions
from app.db import make_engine, session_factory
from app.models import TapeProfile


def availability(client, identifier, available):
    response = client.put(
        f"/api/tape-profiles/{identifier}/availability", json={"available": available}
    )
    assert response.status_code == 200, response.text
    assert response.json()["available"] is available


def test_unavailable_profiles_reject_new_work_but_keep_saved_work_printable(client):
    body = run_body(client)
    identifier = body["tape_profile"]
    install(client, identifier)
    run = client.post("/api/runs/prepare", json=body).json()["run"]
    job_body = {"tape_profile": identifier, "data": {"text": "Existing label"}}
    headers = {"Idempotency-Key": "existing-job"}
    queued = client.post("/api/jobs", json=job_body, headers=headers)
    assert queued.status_code == 201, queued.text
    request_body = {"kind": "job", "input": job_body}
    pending = client.post("/api/requests", json=request_body)
    assert pending.status_code == 201, pending.text
    availability(client, identifier, False)
    listed = client.get("/api/tape-profiles").json()
    assert next(p for p in listed if p["id"] == identifier)["available"] is False
    assert client.post("/api/jobs", json=job_body).status_code == 409
    assert client.post("/api/requests", json=request_body).status_code == 409
    assert client.post("/api/runs/prepare", json={**body, "request_key": "new"}).status_code == 409
    asset, _ = upload(client)
    image = {"image_asset": asset, "tape_profile": identifier}
    assert client.post("/api/image-jobs", json=image).status_code == 409
    assert client.post("/api/requests", json={"kind": "image", "input": image}).status_code == 409
    assert (
        client.post("/api/jobs", json=job_body, headers=headers).json()["id"] == queued.json()["id"]
    )
    assert client.post("/api/runs/prepare", json=body).json()["run"]["id"] == run["id"]
    assert client.post(f"/api/runs/{run['id']}/submit").status_code == 200
    client.app.state.fleet.workers["main"].tick()
    assert client.app.state.fleet.workers["main"].backend.batches
    availability(client, identifier, True)
    assert client.post("/api/jobs", json=job_body).status_code == 201


def test_availability_requires_inventory_permission_and_is_not_reset_by_edit(accounts):
    admin, alice, _ = accounts
    tape = profile(admin)
    identifier = tape["id"]
    path = f"/api/tape-profiles/{identifier}"
    assert alice.put(path + "/availability", json={"available": False}).status_code == 403
    assert admin.put(path + "/availability", json={"available": "false"}).status_code == 422
    availability(admin, identifier, False)
    assert (
        admin.put(path, json={"name": "Renamed tape", "width_mm": 24}).json()["available"] is False
    )
    entries = admin.get("/api/audit", params={"action": "profile.availability_changed"}).json()[
        "items"
    ]
    assert any(entry["fields"].get("available") is False for entry in entries)


def test_pending_requests_can_still_be_approved(accounts):
    admin, alice, _ = accounts
    tape = profile(admin)
    pending = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {
                "tape_profile": tape["id"],
                "destination_id": "main",
                "data": {"text": "Saved request"},
            },
        },
    )
    assert pending.status_code == 201, pending.text
    availability(admin, tape["id"], False)
    approved = admin.post(
        f"/api/requests/{pending.json()['id']}/approve", json={"expected_revision": 1}
    )
    assert approved.status_code == 200, approved.text


def test_availability_migration_preserves_profiles_and_defaults_to_available(tmp_path):
    url = f"sqlite:///{tmp_path / 'availability.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = make_engine(url)
    with session_factory(engine).begin() as session:
        session.add(TapeProfile(id="existing", name="Existing tape", width_mm=24, available=False))
    command.downgrade(config, "20201b1c52b8")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT name, available FROM tape_profiles WHERE id='existing'")
        ).one()
        assert row == ("Existing tape", 1)
    engine.dispose()


def test_profile_disabled_during_render_cannot_create_new_work(client, monkeypatch):
    tape = profile(client)
    started, resume = Event(), Event()
    original = submissions.render_document

    def render(*args, **kwargs):
        started.set()
        assert resume.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(submissions, "render_document", render)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(
            client.post, "/api/jobs", json={"tape_profile": tape["id"], "data": {"text": "Race"}}
        )
        try:
            assert started.wait(5)
            changed = pool.submit(availability, client, tape["id"], False)
            changed.result(timeout=5)
        finally:
            resume.set()
        assert pending.result(timeout=5).status_code == 409
    assert client.get("/api/jobs").json() == []
