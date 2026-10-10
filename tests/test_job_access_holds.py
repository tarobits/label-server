"""Queued authorization changes require an explicit administrator decision."""

import pytest
from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture

from app.job_access import reconcile_access_holds
from app.job_access_models import JobAccessHold
from app.models import FlushRequest, LabelCopy, PrintJob, Role, State, TapeProfile, User
from app.queue import QueueWorker

accounts = account_fixture


def set_level(admin, username: str, level: str) -> None:
    with admin.app.state.fleet.lock, admin.app.state.factory.begin() as session:
        session.get(Role, f"{username}-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": level}
        ]
        session.flush()
        reconcile_access_holds(session)


def submit_direct(admin, alice, tape, copies=1):
    set_level(admin, "alice", "print")
    response = alice.post(
        "/api/jobs",
        json={"tape_profile": tape["id"], "copies": copies, "data": {"text": "Frozen label"}},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_revoked_job_hold_survives_restored_access_and_worker_restart(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    job = submit_direct(admin, alice, tape)
    set_level(admin, "alice", "none")
    held = admin.get("/api/access-holds")
    assert held.status_code == 200, held.text
    assert [hold["job_id"] for hold in held.json()] == [job["id"]]
    set_level(admin, "alice", "print")
    backend = admin.app.state.fleet.workers["main"].backend
    restarted_worker = QueueWorker(admin.app.state.factory, backend, printer_id="main")
    restarted_worker.tick()
    assert backend.batches == []
    assert admin.get("/api/access-holds").json()[0]["job_id"] == job["id"]
    release = admin.post(f"/api/access-holds/{job['id']}/release")
    assert release.status_code == 200, release.text
    assert release.json()["status"] == "released"
    assert (
        admin.post(f"/api/access-holds/{job['id']}/release").json()["resolved_at"]
        == release.json()["resolved_at"]
    )
    restarted_worker.tick()
    assert len(backend.batches) == 1
    assert admin.get("/api/access-holds").json() == []


def test_administrator_can_release_frozen_job_while_owner_remains_disabled(accounts) -> None:
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    job = submit_direct(admin, alice, tape)
    # Exercise the worker-side fallback as well as administration reconciliation.
    with admin.app.state.factory.begin() as session:
        session.get(User, "alice").disabled = True
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    assert not worker.backend.batches
    assert "disabled" in admin.get("/api/access-holds").json()[0]["reason"]
    assert bob.get("/api/access-holds").status_code == 403
    assert bob.post(f"/api/access-holds/{job['id']}/release").status_code == 403
    assert bob.post(f"/api/access-holds/{job['id']}/cancel").status_code == 403
    assert admin.post(f"/api/access-holds/{job['id']}/release").status_code == 200
    worker.tick()
    assert len(worker.backend.batches) == 1
    with admin.app.state.factory() as session:
        assert session.get(User, "alice").disabled
        assert session.get(JobAccessHold, job["id"]).resolved_by == "administrator"


def test_request_approval_requires_request_access_while_direct_jobs_require_print(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    direct = submit_direct(admin, alice, tape)
    request = alice.post(
        "/api/requests",
        json={"kind": "job", "input": {"tape_profile": tape["id"], "data": {"text": "Reviewed"}}},
    )
    assert request.status_code == 201, request.text
    approved = admin.post(f"/api/requests/{request.json()['id']}/approve")
    assert approved.status_code == 200, approved.text
    reviewed = approved.json()["job_ids"][0]
    set_level(admin, "alice", "request")
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    assert admin.get(f"/api/jobs/{direct['id']}").json()["status"] == "queued"
    assert admin.get(f"/api/jobs/{reviewed}").json()["status"] == "printed"
    assert [hold["job_id"] for hold in admin.get("/api/access-holds").json()] == [direct["id"]]
    with admin.app.state.factory() as session:
        assert session.get(PrintJob, reviewed).authorization_basis == "request"


def test_owner_can_cancel_queued_work_after_printer_access_is_revoked(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin)
    job = submit_direct(admin, alice, tape, copies=2)
    set_level(admin, "alice", "none")
    assert alice.get(f"/api/jobs/{job['id']}").status_code == 200
    cancelled = alice.delete(f"/api/jobs/{job['id']}")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert admin.get("/api/access-holds").json() == []
    assert admin.post(f"/api/access-holds/{job['id']}/release").status_code == 409


def test_cancel_hold_preserves_uncertain_copies_and_is_retry_safe(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin)
    job = submit_direct(admin, alice, tape, copies=2)
    with admin.app.state.factory.begin() as session:
        session.get(LabelCopy, job["labels"][0]["id"]).state = State.NEEDS_REVIEW
    set_level(admin, "alice", "none")
    cancelled = admin.post(f"/api/access-holds/{job['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    again = admin.post(f"/api/access-holds/{job['id']}/cancel")
    assert again.json()["resolved_at"] == cancelled.json()["resolved_at"]
    assert admin.post(f"/api/access-holds/{job['id']}/release").status_code == 409
    with admin.app.state.factory() as session:
        assert [
            copy.state
            for copy in session.scalars(
                select(LabelCopy).where(LabelCopy.job_id == job["id"]).order_by(LabelCopy.ordinal)
            )
        ] == [State.NEEDS_REVIEW, State.CANCELLED]
    # Physical review may requeue the uncertain copy later. That must become a
    # visible hold again rather than printing or disappearing behind cancellation.
    with admin.app.state.factory.begin() as session:
        session.get(LabelCopy, job["labels"][0]["id"]).state = State.QUEUED
        session.flush()
        reconcile_access_holds(session)
    assert admin.get("/api/access-holds").json()[0]["status"] == "held"


@pytest.mark.parametrize("manual", [False, True])
def test_access_holds_cannot_be_bypassed_by_manual_or_automatic_printing(accounts, manual) -> None:
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    job = submit_direct(admin, alice, tape)
    set_level(admin, "alice", "none")
    if manual:
        attempted = admin.post(
            "/api/destinations/main/print", json={"copy_ids": [job["labels"][0]["id"]]}
        )
        assert attempted.status_code == 409, attempted.text
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    assert worker.backend.batches == []
    assert admin.get(f"/api/jobs/{job['id']}").json()["status"] == "queued"


def test_access_held_jobs_do_not_trigger_tape_swap_reminders(accounts) -> None:
    from app.notifications import queued_count, schedule_reminders, waiting_condition

    admin, alice, _ = accounts
    tape = profile(admin, threshold=1, reminders=True)
    submit_direct(admin, alice, tape)
    with admin.app.state.factory() as session:
        stored = session.get(TapeProfile, tape["id"])
        assert waiting_condition(session, stored)
    set_level(admin, "alice", "none")
    with admin.app.state.factory.begin() as session:
        stored = session.get(TapeProfile, tape["id"])
        assert queued_count(session, stored) == 0
        assert not waiting_condition(session, stored)
        schedule_reminders(session, 100)
        assert not stored.reminder_active


def test_admin_preview_creates_no_hold_until_access_change_is_confirmed(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin)
    job = submit_direct(admin, alice, tape)
    payload = {"disabled": True, "role_ids": ["member", "alice-access"]}
    preview = admin.post(
        "/api/admin/access-preview",
        json={
            "resource": "users",
            "identifier": "alice",
            "method": "PUT",
            "payload": payload,
        },
    )
    assert preview.status_code == 200, preview.text
    assert admin.get("/api/access-holds").json() == []
    assert alice.get(f"/api/jobs/{job['id']}").status_code == 200
    confirmed = admin.put(
        "/api/admin/users/alice",
        json=payload,
        headers={
            "X-Access-Confirmation": preview.json()["confirmation_token"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert admin.get("/api/access-holds").json()[0]["job_id"] == job["id"]
    assert alice.get(f"/api/jobs/{job['id']}").status_code == 401


def test_held_manual_intent_does_not_block_other_users_automatic_jobs(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()  # Refresh hardware status before making a manual reservation.
    held = submit_direct(admin, alice, tape)
    reserved = alice.post(
        "/api/destinations/main/print",
        json={
            "copy_ids": [held["labels"][0]["id"]],
        },
    )
    assert reserved.status_code == 202, reserved.text
    flush = reserved.json()["requests"][0]["id"]
    set_level(admin, "alice", "none")
    with admin.app.state.factory() as session:
        assert session.get(FlushRequest, flush).completed
    other = admin.post("/api/jobs", json={"tape_profile": tape["id"], "data": {"text": "Allowed"}})
    assert other.status_code == 201, other.text
    worker.tick()
    assert admin.get(f"/api/jobs/{held['id']}").json()["status"] == "queued"
    assert admin.get(f"/api/jobs/{other.json()['id']}").json()["status"] == "printed"
