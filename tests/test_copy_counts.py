"""Quantity editing, ownership, physical-work boundaries and stale approvals."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import install, job, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture
from test_runs import run_body

from app.models import LabelCopy, PrintJob, Role

accounts = account_fixture


def grant(client, name, level):
    with client.app.state.factory.begin() as session:
        session.get(Role, name + "-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": level}
        ]


def pending(admin, owner):
    tape = profile(admin)
    response = owner.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {"tape_profile": tape["id"], "copies": 2, "data": {"text": "Saved label"}},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_pending_owner_edit_invalidates_old_approval_and_keeps_frozen_content(accounts):
    admin, alice, bob = accounts
    value = pending(admin, alice)
    path = f"/api/requests/{value['id']}"
    body = {"copies": 5, "expected_revision": value["revision"]}
    assert bob.put(path + "/labels/0/copies", json=body).status_code == 403
    edited = alice.put(path + "/labels/0/copies", json=body)
    assert edited.status_code == 200, edited.text
    changed = edited.json()
    assert changed["revision"] == 2
    assert changed["labels"][0] == {**value["labels"][0], "copies": 5}
    assert changed["owner_id"] == "alice"
    assert admin.post(path + "/approve").status_code == 422
    assert admin.post(path + "/approve", json={"expected_revision": 1}).status_code == 409
    assert admin.get("/api/jobs").json() == []
    assert alice.put(path + "/labels/0/copies", json=body).status_code == 409
    # A no-op does not invalidate a review, but changing back must not revive an old approval.
    assert (
        alice.put(path + "/labels/0/copies", json={**body, "expected_revision": 2}).json()[
            "revision"
        ]
        == 2
    )
    assert (
        alice.put(path + "/labels/0/copies", json={"copies": 2, "expected_revision": 2}).json()[
            "revision"
        ]
        == 3
    )
    assert admin.post(path + "/approve", json={"expected_revision": 1}).status_code == 409
    approval = admin.post(path + "/approve", json={"expected_revision": 3})
    assert approval.status_code == 200, approval.text
    queued = admin.get(f"/api/jobs/{approval.json()['job_ids'][0]}").json()
    assert queued["copies"] == 2 and queued["owner_id"] == "alice"
    assert not alice.get(f"/api/jobs/{queued['id']}").json()["can_change_copies"]
    assert (
        alice.put(
            f"/api/jobs/{queued['id']}/copies", json={"copies": 4, "expected_copies": 2}
        ).status_code
        == 403
    )
    assert (
        alice.put(path + "/labels/0/copies", json={"copies": 3, "expected_revision": 3}).status_code
        == 409
    )


def test_queue_quantity_requires_print_access_and_ownership_or_moderation(accounts):
    admin, alice, bob = accounts
    grant(admin, "alice", "print")
    grant(admin, "bob", "print")
    tape = profile(admin)
    original = job(alice, tape["id"], 2)
    path = f"/api/jobs/{original['id']}/copies"
    assert bob.put(path, json={"copies": 4, "expected_copies": 2}).status_code == 403
    grown = alice.put(path, json={"copies": 4, "expected_copies": 2})
    assert grown.status_code == 200, grown.text
    value = grown.json()
    assert [label["id"] for label in value["labels"][:2]] == [
        label["id"] for label in original["labels"]
    ]
    assert [label["ordinal"] for label in value["labels"]] == [0, 1, 2, 3]
    for key in ("owner_id", "payload", "template_snapshot", "attribution"):
        assert value[key] == original[key]
    assert alice.put(path, json={"copies": 3, "expected_copies": 2}).status_code == 409
    grant(admin, "alice", "request")
    assert alice.put(path, json={"copies": 3, "expected_copies": 4}).status_code == 403
    grant(admin, "bob", "moderator")
    # The original owner lost print access, so its durable work must be reviewed first.
    assert bob.put(path, json={"copies": 1, "expected_copies": 4}).status_code == 409
    grant(admin, "alice", "print")
    changed = bob.put(path, json={"copies": 1, "expected_copies": 4})
    assert changed.status_code == 200, changed.text
    assert changed.json()["owner_id"] == "alice"
    assert len(changed.json()["labels"]) == 1


@pytest.mark.parametrize("copies", [0, -1, 1001, 1.5, True, "4"])
def test_quantity_validation_is_strict_for_queue_and_requests(accounts, copies):
    admin, alice, _ = accounts
    value = pending(admin, alice)
    assert (
        alice.put(
            f"/api/requests/{value['id']}/labels/0/copies",
            json={"copies": copies, "expected_revision": 1},
        ).status_code
        == 422
    )
    tape = profile(admin)
    item = job(admin, tape["id"])
    assert (
        admin.put(
            f"/api/jobs/{item['id']}/copies", json={"copies": copies, "expected_copies": 1}
        ).status_code
        == 422
    )


def test_reserved_attempted_and_finished_copies_cannot_be_rewritten(client):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    item = job(client, tape["id"], 2)
    path = f"/api/jobs/{item['id']}/copies"
    assert client.post("/api/queue/print").status_code == 202
    assert client.put(path, json={"copies": 3, "expected_copies": 2}).status_code == 409
    assert not client.get(f"/api/jobs/{item['id']}").json()["can_change_copies"]
    worker = client.app.state.fleet.workers["main"]
    worker.backend.fail_after = 0
    worker.tick()
    assert client.put(path, json={"copies": 3, "expected_copies": 2}).status_code == 409
    batch = client.get("/api/batches").json()[0]
    assert (
        client.post(
            f"/api/batches/{batch['id']}/review",
            json={
                "decisions": {label["id"]: "queued" for label in item["labels"]},
                "consumed_mm": 0,
            },
        ).status_code
        == 200
    )
    # Queued again, but still linked to an immutable physical attempt.
    assert client.put(path, json={"copies": 3, "expected_copies": 2}).status_code == 409
    worker.tick()
    assert client.put(path, json={"copies": 3, "expected_copies": 2}).status_code == 409


def test_csv_request_changes_only_selected_row_and_preserves_approval_owner(accounts):
    admin, _, _ = accounts
    body = run_body(admin)
    run = admin.post("/api/runs/prepare", json=body).json()["run"]
    value = admin.post("/api/requests", json={"kind": "run", "run_id": run["id"]}).json()
    path = f"/api/requests/{value['id']}"
    changed = admin.put(path + "/labels/1/copies", json={"copies": 7, "expected_revision": 1})
    assert changed.status_code == 200, changed.text
    assert changed.json()["labels"][0] == value["labels"][0]
    assert admin.post(path + "/approve", json={"expected_revision": 1}).status_code == 409
    approved = admin.post(path + "/approve", json={"expected_revision": 2}).json()
    jobs = [admin.get(f"/api/jobs/{identifier}").json() for identifier in approved["job_ids"]]
    assert [item["copies"] for item in jobs] == [2, 7]
    assert [len(item["labels"]) for item in jobs] == [2, 7]


def test_approval_and_quantity_edit_cannot_race(accounts):
    admin, alice, _ = accounts
    value = pending(admin, alice)
    path = f"/api/requests/{value['id']}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        edit = pool.submit(
            alice.put, path + "/labels/0/copies", json={"copies": 8, "expected_revision": 1}
        )
        approve = pool.submit(admin.post, path + "/approve", json={"expected_revision": 1})
        assert sorted([edit.result().status_code, approve.result().status_code]) == [200, 409]
    current = alice.get(path).json()
    with admin.app.state.factory() as session:
        jobs = list(session.scalars(select(PrintJob)))
        labels = list(session.scalars(select(LabelCopy)))
        if current["status"] == "approved":
            assert len(jobs) == 1 and jobs[0].copies == 2 and len(labels) == 2
        else:
            assert current["labels"][0]["copies"] == 8 and not jobs and not labels


def test_changed_quantity_is_the_quantity_printed(client):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    item = job(client, tape["id"], 2)
    response = client.put(
        f"/api/jobs/{item['id']}/copies", json={"copies": 3, "expected_copies": 2}
    )
    assert response.status_code == 200, response.text
    worker = client.app.state.fleet.workers["main"]
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert len(worker.backend.batches[0]) == 3
    result = client.get(f"/api/jobs/{item['id']}").json()
    assert result["status"] == "printed" and result["copies"] == 3
    assert not result["can_change_copies"]
