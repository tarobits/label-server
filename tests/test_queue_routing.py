"""Printer changes require three permissions and preserve immutable activity."""

import copy

import pytest
from alembic import command
from alembic.config import Config
from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture
from test_fleet import device, group
from test_print_audit import direct

from app.job_access import job_eligible, reconcile_access_holds
from app.models import LabelCopy, PrinterDevice, PrintJob, PrintRun, Role, State, User
from app.queue_routing_models import QueueDestinationChange

accounts = account_fixture


def grant(admin, user, levels, permission=False):
    with admin.app.state.factory.begin() as session:
        session.get(Role, f"{user}-access").permissions = [
            {"kind": "destination", "destination_id": identifier, "level": level}
            for identifier, level in levels.items()
        ] + ([{"kind": "application", "permission": "queue.change_printer"}] if permission else [])


def setup(accounts):
    admin, alice, bob = accounts
    tape = profile(admin, threshold=100)
    install(admin, tape["id"])
    target = device(admin, "Packing")
    grant(admin, "alice", {"main": "print"})
    grant(admin, "bob", {"main": "moderator", target: "moderator"}, True)
    queued = direct(alice, tape, copies=2)
    return admin, alice, bob, target, tape, queued


def change(client, target, *jobs, reason="Printer offline"):
    return client.post(
        "/api/queue/change-printer",
        json={
            "printer_id": target,
            "copy_ids": [c["id"] for j in jobs for c in j["labels"] if c["state"] == "queued"],
            "reason": reason,
        },
    )


def history(client):
    response = client.get("/api/printer-changes/page")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("source", "target_level", "permission"),
    [
        ("moderator", "moderator", False),
        ("print", "moderator", True),
        ("moderator", "print", True),
        ("none", "moderator", True),
        ("moderator", "none", True),
    ],
)
def test_requires_both_moderator_grants_and_global_permission(
    accounts, source, target_level, permission
):
    admin, alice, bob, target, tape, job = setup(accounts)
    grant(admin, "bob", {"main": source, target: target_level}, permission)
    response = change(bob, target, job)
    assert response.status_code == 403, response.text
    assert admin.get(f"/api/jobs/{job['id']}").json()["destination_id"] == "main"
    assert history(admin)["total"] == 0


def test_change_records_actor_source_target_reason_and_keeps_requester(accounts):
    admin, alice, bob, target, tape, job = setup(accounts)
    response = change(bob, target, job)
    assert response.status_code == 200, response.text
    saved = admin.get(f"/api/jobs/{job['id']}").json()
    assert saved["destination_id"] == target
    assert saved["template_snapshot"] == job["template_snapshot"]
    assert saved["profile_id"] == job["profile_id"]
    assert saved["attribution"]["authorization"] == job["attribution"]["authorization"]
    assert saved["attribution"]["requested_by"]["id"] == "alice"
    event = history(admin)["items"][0]
    assert event["actor"] == {"id": "bob", "name": "bob"}
    assert event["source"] == {"id": "main", "name": "Mock printer"}
    assert event["target"] == {"id": target, "name": "Packing"}
    assert event["reason"] == "Printer offline"
    assert set(event["copy_ids"]) == {c["id"] for c in job["labels"]}
    assert saved["attribution"]["destination_changes"] == [event]
    assert history(alice)["total"] == 0
    assert history(bob)["total"] == 1
    assert change(bob, target, job).status_code == 409  # No duplicate audit or application.
    with admin.app.state.factory() as session:
        assert job_eligible(session, session.get(PrintJob, job["id"]))
    # A physically matching cartridge is still required after rerouting.
    assert admin.post(f"/api/destinations/{target}/print").status_code == 409
    cartridge = admin.post(
        "/api/cartridges",
        json={"profile_id": tape["id"], "name": "Packing tape", "nominal_length_mm": 8000},
    ).json()
    assert (
        admin.put(
            f"/api/printer/active-tape?printer_id={target}", json={"cartridge_id": cartridge["id"]}
        ).status_code
        == 200
    )
    worker = admin.app.state.fleet.workers[target]
    worker.latest_status = worker.backend.get_status()
    assert admin.post(f"/api/destinations/{target}/print").status_code == 202
    worker.tick()
    batch = admin.get("/api/batches").json()[0]
    assert batch["attribution_summary"][0]["attribution"]["destination_changes"] == [event]
    with admin.app.state.factory.begin() as session:
        session.get(User, "bob").username = "Renamed operator"
        session.get(PrinterDevice, target).name = "Renamed printer"
    assert history(admin)["items"] == [event]


@pytest.mark.parametrize("revocation", ["permission", "source", "target", "disabled"])
def test_revoked_authorizer_pauses_substituted_work(accounts, revocation):
    admin, alice, bob, target, tape, job = setup(accounts)
    assert change(bob, target, job).status_code == 200
    levels = {"main": "moderator", target: "moderator"}
    if revocation == "source":
        levels["main"] = "print"
    if revocation == "target":
        levels[target] = "print"
    grant(admin, "bob", levels, revocation != "permission")
    with admin.app.state.factory.begin() as session:
        if revocation == "disabled":
            session.get(User, "bob").disabled = True
        assert not job_eligible(session, session.get(PrintJob, job["id"]))
        reconcile_access_holds(session)
    assert admin.get(f"/api/jobs/{job['id']}").json()["access_hold"]["status"] == "held"


@pytest.mark.parametrize("state", [State.PRINTING, State.NEEDS_REVIEW, State.CANCELLED])
def test_no_changes_for_nonqueued_copies_or_uncertain_job(accounts, state):
    admin, alice, bob, target, tape, job = setup(accounts)
    with admin.app.state.factory.begin() as session:
        session.get(LabelCopy, job["labels"][0]["id"]).state = state
    response = change(bob, target, job)
    assert response.status_code == 409
    assert history(admin)["total"] == 0


def test_partial_selection_and_reserved_work_are_rejected(accounts):
    admin, alice, bob, target, tape, job = setup(accounts)
    partial = copy.deepcopy(job)
    partial["labels"] = partial["labels"][:1]
    assert change(bob, target, partial).status_code == 409
    worker = admin.app.state.fleet.workers["main"]
    worker.latest_status = worker.backend.get_status()
    assert admin.post("/api/destinations/main/print").status_code == 202
    response = change(bob, target, job)
    assert response.status_code == 409
    assert "reservation" in response.json()["detail"]
    assert history(admin)["total"] == 0


def test_incompatible_geometry_and_access_hold_are_rejected(accounts):
    admin, alice, bob, target, tape, job = setup(accounts)
    with admin.app.state.factory.begin() as session:
        saved = session.get(PrintJob, job["id"])
        snapshot = copy.deepcopy(saved.template_snapshot)
        saved.template_snapshot = {
            **snapshot,
            "render_spec": {**snapshot["render_spec"], "dpi": 999},
        }
    response = change(bob, target, job)
    assert response.status_code == 409
    assert "resolution" in response.json()["detail"]
    with admin.app.state.factory.begin() as session:
        session.get(PrintJob, job["id"]).template_snapshot = snapshot
        session.get(User, "alice").disabled = True
    response = change(bob, target, job)
    assert response.status_code == 409
    assert "hold" in response.json()["detail"]
    assert history(admin)["total"] == 0


def test_csv_run_moves_all_queued_rows_and_retains_assignment_in_audit(accounts):
    admin, alice, bob, target, tape, job = setup(accounts)
    destination = group(admin, ["main", target])
    response = admin.post(
        "/api/runs/prepare",
        json={
            "destination_id": destination,
            "request_key": "change-run",
            "name": "Shipping",
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
    jobs = admin.post(f"/api/runs/{run['id']}/submit").json()["jobs"]
    with admin.app.state.factory.begin() as session:
        session.get(PrintRun, run["id"]).assigned_printer_id = "main"
    response = change(admin, target, jobs[0])
    assert response.status_code == 409
    assert "CSV run" in response.json()["detail"]
    response = change(admin, target, *jobs)
    assert response.status_code == 200, response.text
    assert all(event["previous_assignment"]["id"] == "main" for event in response.json()["changes"])
    with admin.app.state.factory() as session:
        saved_run = session.get(PrintRun, run["id"])
        assert saved_run.destination_id == saved_run.assigned_printer_id == target
        assert {
            j.destination_id
            for j in session.scalars(select(PrintJob).where(PrintJob.run_id == run["id"]))
        } == {target}


def test_global_permission_is_assignable_through_roles_api(accounts):
    admin, alice, bob = accounts
    body = {
        "name": "Printer operators",
        "permissions": [{"kind": "application", "permission": "queue.change_printer"}],
    }
    preview = admin.post(
        "/api/admin/access-preview", json={"resource": "roles", "method": "POST", "payload": body}
    )
    assert preview.status_code == 200, preview.text
    response = admin.post(
        "/api/admin/roles",
        json=body,
        headers={"X-Access-Confirmation": preview.json()["confirmation_token"]},
    )
    assert response.status_code == 201, response.text


def test_audit_migration_round_trip_preserves_existing_jobs(accounts):
    admin, alice, bob, target, tape, job = setup(accounts)
    config = Config("alembic.ini")
    config.attributes["database_url"] = admin.app.state.settings.database_url
    command.downgrade(config, "d83f5c012e46")
    command.upgrade(config, "head")
    assert admin.get(f"/api/jobs/{job['id']}").json()["destination_id"] == "main"
    assert change(bob, target, job).status_code == 200
    with admin.app.state.factory() as session:
        assert len(list(session.scalars(select(QueueDestinationChange)))) == 1


def test_multi_item_change_is_atomic_and_repeated_changes_keep_history(accounts):
    admin, alice, bob, target, tape, first = setup(accounts)
    second = direct(alice, tape, text="Second")
    with admin.app.state.factory.begin() as session:
        saved = session.get(PrintJob, second["id"])
        snapshot = copy.deepcopy(saved.template_snapshot)
        saved.template_snapshot = {
            **snapshot,
            "render_spec": {**snapshot["render_spec"], "dpi": 999},
        }
    assert change(bob, target, first, second).status_code == 409
    assert history(admin)["total"] == 0
    assert admin.get(f"/api/jobs/{first['id']}").json()["destination_id"] == "main"
    with admin.app.state.factory.begin() as session:
        session.get(PrintJob, second["id"]).template_snapshot = snapshot
    assert change(bob, target, first, second).status_code == 200
    original_events = history(admin)["items"]
    assert len(original_events) == 2
    assert change(bob, "main", first, second, reason="Printer restored").status_code == 200
    saved = admin.get(f"/api/jobs/{first['id']}").json()
    assert saved["destination_id"] == "main"
    assert len(saved["attribution"]["destination_changes"]) == 2
    assert {event["id"] for event in original_events}.issubset(
        {event["id"] for event in history(admin)["items"]}
    )
    page = admin.get("/api/printer-changes/page?limit=1").json()
    next_page = admin.get(
        f"/api/printer-changes/page?limit=1&offset=1&before={page['before']}"
    ).json()
    assert page["total"] == next_page["total"] == 4
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
