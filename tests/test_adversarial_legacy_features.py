"""Attack earlier-release contracts on current code, never historical deployments.

All state is disposable fixture data. Concurrent probes synchronize their callers;
they do not claim to exhaust every possible database or hardware interleaving.
"""

import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from conftest import profile
from sqlalchemy import select
from test_access_security import SVG, image_document
from test_access_security import accounts as accounts
from test_account_recovery import mailbox as mailbox
from test_account_recovery import reset_link, verify_address
from test_auth import auth_client as auth_client
from test_auth import login, setup_admin
from test_granular_printer_permissions import set_permissions
from test_group_billing import decision, setup, submit_group
from test_personal_activity import shared_batch
from test_runs import run_body
from test_template_revisions import create, update

from app.accounts.billing_models import BillingCharge, BillingRequest
from app.models import JobSubmission, LabelCopy, PrintJob, ReleaseMigration, State
from migrations.relationships_v1 import VERSION


def collide(*operations):
    """Release API callers together, allowing application locks to arbitrate."""
    barrier = Barrier(len(operations))

    def invoke(operation):
        barrier.wait(timeout=5)
        return operation()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures = [pool.submit(invoke, operation) for operation in operations]
        return [future.result(timeout=15) for future in futures]


def test_conflicting_idempotent_submissions_choose_one_payload(client):
    tape = profile(client)
    headers = {"Idempotency-Key": "adversarial:conflicting-retry"}
    bodies = [
        {"tape_profile": tape["id"], "data": {"text": text}, "copies": copies}
        for text, copies in (("First payload", 1), ("Conflicting payload", 3))
    ]
    responses = collide(
        *(lambda body=body: client.post("/api/jobs", json=body, headers=headers) for body in bodies)
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    winner = next(index for index, response in enumerate(responses) if response.status_code == 201)
    job = responses[winner].json()
    assert job["payload"] == bodies[winner]["data"]
    assert len(job["labels"]) == bodies[winner]["copies"]
    for index, body in enumerate(bodies):
        replay = client.post("/api/jobs", json=body, headers=headers)
        assert replay.status_code == (201 if index == winner else 409)
        if index == winner:
            assert replay.json()["id"] == job["id"]
    with client.app.state.factory() as session:
        assert len(list(session.scalars(select(PrintJob)))) == 1
        assert len(list(session.scalars(select(JobSubmission)))) == 1
        assert len(list(session.scalars(select(LabelCopy)))) == bodies[winner]["copies"]


def test_same_idempotency_key_cannot_replay_another_users_job(accounts):
    admin, alice, bob = accounts
    tape = profile(admin)
    for user in ("alice", "bob"):
        set_permissions(admin, user, "view", "submit_directly")
    body = {"tape_profile": tape["id"], "data": {"text": "Shared input, private jobs"}}
    headers = {"Idempotency-Key": "same-key-in-different-accounts"}
    responses = collide(
        *(
            lambda client=client: client.post("/api/jobs", json=body, headers=headers)
            for client in (alice, bob)
        )
    )
    assert [response.status_code for response in responses] == [201, 201]
    ids = [response.json()["id"] for response in responses]
    assert ids[0] != ids[1], "An idempotency receipt crossed an account boundary"
    assert alice.get(f"/api/jobs/{ids[1]}").status_code == 403
    assert bob.get(f"/api/jobs/{ids[0]}").status_code == 403
    with admin.app.state.factory() as session:
        assert {session.get_one(PrintJob, identifier).owner_id for identifier in ids} == {
            "alice",
            "bob",
        }


def test_concurrent_csv_submit_after_template_deletion_uses_one_frozen_run(client):
    body = run_body(client)
    prepared = client.post("/api/runs/prepare", json=body)
    assert prepared.status_code == 200, prepared.text
    run = prepared.json()["run"]
    before = client.get(f"/api/runs/{run['id']}/rows/0/preview")
    assert before.status_code == 200
    assert client.delete("/api/templates/text").status_code == 200
    path = f"/api/runs/{run['id']}/submit"
    responses = collide(lambda: client.post(path), lambda: client.post(path))
    assert [response.status_code for response in responses] == [200, 200]
    jobs = responses[0].json()["jobs"]
    ids = [job["id"] for job in jobs]
    assert [job["id"] for job in responses[1].json()["jobs"]] == ids
    assert [job["source_row"] for job in jobs] == [3, 2]
    assert [job["payload"]["text"] for job in jobs] == ["Second", "First, label"]
    assert [job["id"] for job in client.post(path).json()["jobs"]] == ids
    assert client.get(f"/api/runs/{run['id']}/rows/0/preview").json() == before.json()
    with client.app.state.factory() as session:
        assert len(list(session.scalars(select(PrintJob)))) == 2
        assert len(list(session.scalars(select(LabelCopy)))) == 3


@pytest.mark.parametrize("restore", [False, True], ids=["two-edits", "edit-versus-restore"])
def test_template_revision_collision_preserves_exactly_one_winner(accounts, restore):
    _, alice, _ = accounts
    original = create(alice)
    current = update(alice, original)
    path = f"/api/templates/{original['id']}"

    def edit(name):
        document = copy.deepcopy(current["document"])
        document["elements"][0]["content"] = name
        return alice.put(
            path,
            json={
                "name": name,
                "scope": "personal",
                "document": document,
                "expected_revision": current["revision"],
            },
        )

    responses = collide(
        lambda: edit("Concurrent edit A"),
        (
            lambda: alice.post(
                path + "/revisions/1/restore", json={"expected_revision": current["revision"]}
            )
        )
        if restore
        else (lambda: edit("Concurrent edit B")),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    saved = alice.get(path).json()
    assert saved["revision"] == 3
    assert (saved["name"], saved["document"]) == (winner["name"], winner["document"])
    history = alice.get(path + "/revisions").json()
    assert [item["revision"] for item in history] == [3, 2, 1]


@pytest.mark.parametrize("surface", ["asset", "template", "revision"])
def test_warmed_preview_cannot_survive_revocation_via_conditional_headers(accounts, surface):
    admin, alice, _ = accounts
    uploaded = admin.post("/api/image-assets", content=SVG)
    assert uploaded.status_code == 201
    item = create(admin, scope="global", document=image_document(uploaded.json()["id"]))
    path = {
        "asset": f"/api/image-assets/{uploaded.json()['id']}/preview",
        "template": f"/api/templates/{item['id']}/preview.webp",
        "revision": f"/api/templates/{item['id']}/revisions/1/preview",
    }[surface]
    cached = alice.get(path)
    assert cached.status_code == 200, cached.text
    update(admin, item, scope="personal")
    for headers in (
        {},
        {"If-None-Match": cached.headers.get("etag", "*")},
        {"If-Modified-Since": "Thu, 01 Jan 2099 00:00:00 GMT"},
    ):
        denied = alice.get(path, headers=headers)
        assert denied.status_code == 403, (
            f"Revoked {surface} preview returned {denied.status_code} with {list(headers)}"
        )
        assert denied.content != cached.content
    assert admin.get(path).status_code == 200


@pytest.mark.parametrize("mutation", ["prefix", "suffix", "truncate", "case"])
def test_reset_token_mutations_cannot_reset_or_consume_valid_token(
    auth_client, tmp_path, mailbox, mutation
):
    setup_admin(auth_client, tmp_path)
    verify_address(auth_client, mailbox)
    token = reset_link(auth_client, mailbox)
    malformed = {
        "prefix": "x" + token,
        "suffix": token + "x",
        "truncate": token[:-1],
        "case": token.swapcase(),
    }[mutation]
    assert malformed != token
    replacement = "replacement password for adversarial test"
    denied = auth_client.post(
        "/api/auth/password/reset", json={"token": malformed, "new_password": replacement}
    )
    assert denied.status_code == 400
    assert malformed not in denied.text
    assert (
        auth_client.post(
            "/api/auth/password/reset", json={"token": token, "new_password": replacement}
        ).status_code
        == 204
    )
    assert (
        auth_client.post(
            "/api/auth/password/reset", json={"token": token, "new_password": replacement}
        ).status_code
        == 400
    )
    assert login(auth_client, password=replacement)["user"] is not None


def test_opposite_funding_decisions_cannot_both_commit_or_double_charge(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account)
    identifier = job["billing_request"]["id"]
    responses = collide(
        lambda: decision(bob, identifier, True), lambda: decision(admin, identifier, False)
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    approved = responses[0].status_code == 200
    # Replay the winning decision several times, including after physical-work simulation.
    for _ in range(3):
        assert decision(admin, identifier, approved).status_code == 200
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    worker.tick()
    assert decision(admin, identifier, approved).status_code == 200
    assert decision(admin, identifier, not approved).status_code == 409
    with admin.app.state.factory() as session:
        assert session.get_one(BillingRequest, identifier).status == (
            "approved" if approved else "rejected"
        )
        charges = list(session.scalars(select(BillingCharge)))
        assert len(charges) == (1 if approved else 0)
        assert set(session.scalars(select(LabelCopy.state))) == {
            State.PRINTED if approved else State.QUEUED
        }
    assert len(worker.backend.batches) == (1 if approved else 0)


@pytest.mark.parametrize(
    "query",
    [
        "requester_id=bob",
        "requester_id=alice&requester_id=bob",
        "requester_id=bob&requester_id=alice",
        "requester_id=",
        "requester_id=%25",
    ],
)
def test_duplicate_or_wildcard_history_filters_cannot_expand_personal_access(accounts, query):
    _, alice, _ = accounts
    batch, own, other = shared_batch(accounts)
    response = alice.get("/api/batches/page?limit=100&" + query)
    assert response.status_code == 200
    for forbidden in ("Bob private label", "PRIVATE ERROR FROM BOB", other["id"], "bob"):
        assert forbidden not in response.text
    assert response.json()["total"] <= 1
    for row in response.json()["items"]:
        assert row["id"] == batch["id"] and row["redacted"]
    # A legitimate list hit must never grant access to a different copy in the same batch.
    assert (
        alice.get(
            f"/api/batches/{batch['id']}/items/{other['labels'][0]['id']}/preview"
        ).status_code
        == 404
    )
    assert (
        alice.get(f"/api/batches/{batch['id']}/items/{own['labels'][0]['id']}/preview").status_code
        == 200
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/jobs"),
        ("POST", "/api/jobs"),
        ("GET", "/api/%6aobs"),
        ("GET", "/api/migration/relationships/../jobs"),
        ("POST", "/api/runs/prepare"),
        ("POST", "/api/queue/print"),
        ("GET", "/api/companion/work"),
        ("POST", "/api/preview"),
    ],
)
def test_maintenance_gate_rejects_work_even_for_admin_and_encoded_routes(accounts, method, path):
    admin, _, _ = accounts
    with admin.app.state.factory.begin() as session:
        session.get_one(ReleaseMigration, VERSION).completed_at = None
    admin.app.state.relationship_maintenance = True
    try:
        response = admin.request(method, path, json={})
        assert response.status_code == 503, f"{method} {path}: {response.status_code}"
        assert response.headers["cache-control"] == "no-store"
        with admin.app.state.factory() as session:
            assert not list(session.scalars(select(PrintJob)))
        assert admin.get("/api/health").status_code == 200
    finally:
        admin.app.state.relationship_maintenance = False
