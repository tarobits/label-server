"""Activity attribution survives account changes, release decisions and repeated attempts."""

import copy
import time

import pytest
from alembic import command
from alembic.config import Config
from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture

from app.job_access import job_eligible, reconcile_access_holds
from app.job_access_models import JobAccessHold
from app.models import Batch, BatchItem, LabelCopy, PrintJob, PrintRun, Role, State, User

accounts = account_fixture


def grant(admin, user, level):
    with admin.app.state.factory.begin() as session:
        session.get(Role, f"{user}-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": level}
        ]


def direct(client, tape, text="Audit", copies=1):
    response = client.post(
        "/api/jobs",
        json={
            "destination_id": "main",
            "tape_profile": tape["id"],
            "copies": copies,
            "data": {"text": text},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def prepare_printer(admin, threshold=1):
    tape = profile(admin, threshold=threshold)
    install(admin, tape["id"])
    worker = admin.app.state.fleet.workers["main"]
    worker.latest_status = worker.backend.get_status()
    return tape, worker


def detail(admin, identifier):
    response = admin.get(f"/api/batches/{identifier}")
    assert response.status_code == 200, response.text
    return response.json()


def test_direct_print_records_same_requester_and_authorizer_with_automatic_trigger(accounts):
    admin, alice, bob = accounts
    grant(admin, "alice", "print")
    tape, worker = prepare_printer(admin)
    job = direct(alice, tape, copies=2)
    person = {"id": "alice", "name": "alice"}
    assert job["attribution"]["requested_by"] == person
    assert job["attribution"]["authorization"] == {
        "kind": "direct",
        "actor": person,
        "at": job["created_at"],
        "request_id": None,
    }
    worker.tick()
    batch = admin.get("/api/batches").json()[0]
    assert batch["trigger"]["kind"] == "automatic"
    assert batch["trigger"]["actor"] is None
    assert batch["trigger"]["flush_request_id"] is None
    assert batch["attribution_summary"] == [{"attribution": job["attribution"], "copies": 2}]
    attempt = detail(admin, batch["id"])
    assert [item["attribution"] for item in attempt["items"]] == [job["attribution"]] * 2
    assert alice.get("/api/batches").json() == []
    assert bob.get(f"/api/batches/{batch['id']}").status_code == 403
    assert bob.get(f"/api/jobs/{job['id']}").status_code == 403


def test_approval_and_manual_starter_are_distinct_and_names_are_snapshotted(accounts):
    admin, alice, bob = accounts
    grant(admin, "bob", "moderator")
    tape, worker = prepare_printer(admin, threshold=100)
    requested = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {
                "destination_id": "main",
                "tape_profile": tape["id"],
                "data": {"text": "Approved"},
            },
        },
    )
    assert requested.status_code == 201, requested.text
    request = requested.json()
    with admin.app.state.factory.begin() as session:
        session.get(User, "alice").username = "alice-renamed-after-request"
    approved = bob.post(f"/api/requests/{request['id']}/approve")
    assert approved.status_code == 200, approved.text
    approved_job = alice.get(f"/api/jobs/{approved.json()['job_ids'][0]}").json()
    assert approved_job["attribution"]["requested_by"] == {"id": "alice", "name": "alice"}
    assert approved_job["attribution"]["authorization"] == {
        "kind": "approval",
        "actor": {"id": "bob", "name": "bob"},
        "at": approved.json()["decided_at"],
        "request_id": request["id"],
    }
    flush = admin.post("/api/queue/print?printer_id=main")
    assert flush.status_code == 202, flush.text
    with admin.app.state.factory.begin() as session:
        session.get(User, "bob").username = "bob-renamed-after-approval"
        session.get(User, "administrator").username = "administrator-renamed-after-start"
    worker.tick()
    batch = admin.get("/api/batches").json()[0]
    assert batch["trigger"] == {
        "kind": "manual",
        "actor": {"id": "administrator", "name": "administrator"},
        "at": flush.json()["created_at"],
        "flush_request_id": flush.json()["id"],
    }
    attribution = detail(admin, batch["id"])["items"][0]["attribution"]
    assert attribution == approved_job["attribution"]
    assert attribution["release"] is None


def test_release_and_retried_attempt_keep_separate_historical_snapshots(accounts):
    admin, alice, bob = accounts
    grant(admin, "alice", "print")
    tape, worker = prepare_printer(admin)
    job = direct(alice, tape)
    worker.backend.fail_after = 0
    worker.tick()
    first = admin.get("/api/batches").json()[0]
    first_detail = copy.deepcopy(detail(admin, first["id"]))
    assert first_detail["items"][0]["attribution"]["release"] is None
    assert (
        admin.post(
            f"/api/batches/{first['id']}/review",
            json={
                "decisions": {job["labels"][0]["id"]: "queued"},
                "consumed_mm": 0,
            },
        ).status_code
        == 200
    )
    with admin.app.state.factory.begin() as session:
        session.get(User, "alice").disabled = True
        reconcile_access_holds(session)
    released = admin.post(f"/api/access-holds/{job['id']}/release")
    assert released.status_code == 200, released.text
    release_time = released.json()["resolved_at"]
    with admin.app.state.factory.begin() as session:
        session.get(User, "administrator").username = "renamed-after-release"
    worker.backend.fail_after = None
    worker.tick()
    second = next(batch for batch in admin.get("/api/batches").json() if batch["id"] != first["id"])
    second_snapshot = detail(admin, second["id"])["items"][0]["attribution"]
    assert second_snapshot["release"] == {
        "actor": {"id": "administrator", "name": "administrator"},
        "at": release_time,
    }
    assert second_snapshot["authorization"] == job["attribution"]["authorization"]
    # A future hold cycle must never rewrite either previous physical attempt.
    with admin.app.state.factory.begin() as session:
        hold = session.get(JobAccessHold, job["id"])
        hold.status = "held"
        hold.resolved_at = hold.resolved_by = None
        hold.resolved_by_snapshot = None
    assert (
        detail(admin, first["id"])["items"][0]["attribution"]
        == first_detail["items"][0]["attribution"]
    )
    assert detail(admin, second["id"])["items"][0]["attribution"] == second_snapshot


def prepare_csv(alice, tape, key="audit-csv"):
    prepared = alice.post(
        "/api/runs/prepare",
        json={
            "request_key": key,
            "name": "Alice's draft",
            "destination_id": "main",
            "template": "text",
            "expected_revision": 2,
            "tape_profile": tape["id"],
            "csv_text": "Text\nFirst\nSecond\n",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2, "copies": 1}, {"source_row": 3, "copies": 1}],
        },
    )
    assert prepared.status_code == 200, prepared.text
    return prepared.json()["run"]


def test_csv_submission_attributes_original_owner_and_admin_with_immutable_attempts(accounts):
    admin, alice, _ = accounts
    grant(admin, "alice", "print")
    tape, worker = prepare_printer(admin)
    run = prepare_csv(alice, tape)
    submitted = admin.post(f"/api/runs/{run['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    original = {"id": "alice", "name": "alice"}
    submitter = {"id": "administrator", "name": "administrator"}
    for job in submitted.json()["jobs"]:
        assert job["owner_id"] == "alice"
        assert job["attribution"]["requested_by"] == original
        assert job["attribution"]["submitted_by"] == submitter
        assert job["attribution"]["authorization"]["actor"] == submitter
    with admin.app.state.factory.begin() as session:
        session.get(User, "alice").username = "Alice renamed"
        session.get(User, "administrator").username = "Admin renamed"
    # Retrying submission preserves the first actor snapshots and jobs.
    assert admin.post(f"/api/runs/{run['id']}/submit").json() == submitted.json()
    worker.tick()
    assert all(job["status"] == "printed" for job in admin.get("/api/jobs").json())
    batch = admin.get("/api/batches").json()[0]
    attempts = detail(admin, batch["id"])["items"]
    assert len(attempts) == 2
    for attempt in attempts:
        assert attempt["attribution"]["requested_by"] == original
        assert attempt["attribution"]["submitted_by"] == submitter
        assert attempt["attribution"]["authorization"]["actor"] == submitter


@pytest.mark.parametrize("discrepancy", ["request_only", "disabled", "unavailable"])
def test_delegated_csv_requires_explicit_admin_override_and_preserves_snapshot(
    accounts, discrepancy
):
    admin, alice, _ = accounts
    tape, worker = prepare_printer(admin)
    run = prepare_csv(alice, tape)
    with admin.app.state.factory.begin() as session:
        if discrepancy == "disabled":
            session.get(User, "alice").disabled = True
        elif discrepancy == "unavailable":
            session.get(PrintRun, run["id"]).owner_id = "missing-author"
    declined = admin.post(f"/api/runs/{run['id']}/submit")
    assert declined.status_code == 409, declined.text
    assert declined.json()["detail"]["code"] == "owner_access_discrepancy"
    assert declined.json()["detail"]["override_allowed"] is True
    assert "Confirm an administrator override" in declined.json()["detail"]["message"]
    with admin.app.state.factory() as session:
        assert session.scalar(select(PrintJob)) is None
        assert session.scalar(select(LabelCopy)) is None
        assert session.get(PrintRun, run["id"]).submitted_at is None
    submitted = admin.post(f"/api/runs/{run['id']}/submit", json={"authorization_override": True})
    assert submitted.status_code == 200, submitted.text
    for job in submitted.json()["jobs"]:
        assert job["owner_id"] == ("missing-author" if discrepancy == "unavailable" else "alice")
        assert job["attribution"]["authorization"]["kind"] == "override"
        assert job["authorization_basis"] == "override"
        assert job["attribution"]["submitted_by"] == {
            "id": "administrator",
            "name": "administrator",
        }
    with admin.app.state.factory.begin() as session:
        session.get(User, "administrator").username = "Renamed after override"
    assert admin.post(f"/api/runs/{run['id']}/submit").json() == submitted.json()
    worker.tick()
    assert all(job["status"] == "printed" for job in admin.get("/api/jobs").json())
    batch = admin.get("/api/batches").json()[0]
    assert (
        detail(admin, batch["id"])["items"][0]["attribution"]
        == submitted.json()["jobs"][0]["attribution"]
    )


def test_non_administrator_cannot_override_own_or_foreign_csv(accounts):
    admin, alice, bob = accounts
    tape, _ = prepare_printer(admin)
    grant(admin, "alice", "print")
    grant(admin, "bob", "moderator")
    run = prepare_csv(alice, tape)
    for client in (alice, bob):
        response = client.post(
            f"/api/runs/{run['id']}/submit", json={"authorization_override": True}
        )
        assert response.status_code == 403, response.text
    with admin.app.state.factory() as session:
        assert session.scalar(select(PrintJob)) is None


@pytest.mark.parametrize("revocation", ["disabled", "lost_access"])
def test_override_jobs_pause_when_authorizer_loses_access(accounts, revocation):
    admin, alice, bob = accounts
    tape, worker = prepare_printer(admin)
    run = prepare_csv(alice, tape)
    submitted = admin.post(f"/api/runs/{run['id']}/submit", json={"authorization_override": True})
    assert submitted.status_code == 200, submitted.text
    with admin.app.state.factory.begin() as session:
        actor = session.get(User, "administrator")
        if revocation == "disabled":
            actor.disabled = True
        else:
            actor.role_ids = ["member"]
        # A separate administrator can decide what to do with the paused work.
        session.get(User, "bob").role_ids = ["administrator"]
    worker.tick()
    assert bob.get("/api/batches").json() == []
    with admin.app.state.factory() as session:
        for value in submitted.json()["jobs"]:
            job = session.get(PrintJob, value["id"])
            assert not job_eligible(session, job)
            hold = session.get(JobAccessHold, job.id)
            assert hold.status == "held"
            assert "authorizer" in hold.reason
            assert (
                session.scalar(select(LabelCopy).where(LabelCopy.job_id == job.id)).state
                == State.QUEUED
            )
    for job in submitted.json()["jobs"]:
        assert bob.post(f"/api/access-holds/{job['id']}/release").status_code == 200
    worker.tick()
    assert all(job["status"] == "printed" for job in bob.get("/api/jobs").json())


def test_legacy_migration_does_not_invent_requesters_or_batch_starters(accounts):
    admin, alice, _ = accounts
    grant(admin, "alice", "print")
    tape, worker = prepare_printer(admin)
    old = direct(alice, tape)
    csv_run = prepare_csv(alice, tape)
    csv_jobs = admin.post(f"/api/runs/{csv_run['id']}/submit").json()["jobs"]
    worker.tick()
    old_batch = admin.get("/api/batches").json()[0]
    # Simulate an old pre-auth owner mapping and a later bootstrap administrator.
    with admin.app.state.factory.begin() as session:
        session.get(User, "alice").created_at = time.time() + 100
    config = Config("alembic.ini")
    config.attributes["database_url"] = admin.app.state.settings.database_url
    command.downgrade(config, "c9e4136a7052")
    command.upgrade(config, "head")
    command.check(config)
    result = detail(admin, old_batch["id"])
    assert result["trigger"]["kind"] == "unknown"
    assert result["trigger"]["actor"] is None
    attribution = result["items"][0]["attribution"]
    assert attribution["requested_by"] is None
    assert attribution["authorization"]["kind"] == "unknown"
    assert attribution["authorization"]["actor"] is None
    with admin.app.state.factory() as session:
        assert session.get(PrintJob, old["id"]).attribution == attribution
        assert session.scalar(select(BatchItem)).attribution == attribution
        assert session.get(Batch, old_batch["id"]).trigger is None
        for job in csv_jobs:
            # A foreign-owned CSV's historical submitter cannot be reconstructed
            # from its owner; migration must not invent direct authorization.
            snapshot = session.get(PrintJob, job["id"]).attribution
            assert snapshot["requested_by"] is None
            assert snapshot["authorization"]["kind"] == "unknown"
            assert snapshot["authorization"]["actor"] is None
            assert snapshot.get("submitted_by") is None
