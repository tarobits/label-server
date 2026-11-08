"""The legacy requeue route cannot bypass explicit retry funding."""

import copy

import pytest
from conftest import install, job, profile
from test_access_security import accounts as account_fixture
from test_print_audit import direct, grant, prepare_printer

from app.deletion import retain
from app.models import BatchItem, LabelTemplate, PrinterDevice, PrinterGroup, PrintJob, State

accounts = account_fixture


def printed(client):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    original = job(client, tape["id"], copies=3)
    worker = client.app.state.fleet.workers["main"]
    worker.tick()
    batch = client.get("/api/batches").json()[0]
    path = f"/api/batches/{batch['id']}/items/{original['labels'][0]['id']}/requeue"
    return original, batch, path, worker


def test_legacy_requeue_leaves_history_unchanged_and_requires_funding(client):
    original, batch, path, worker = printed(client)
    history = client.get(f"/api/batches/{batch['id']}").json()
    with client.app.state.factory.begin() as session:
        template = session.get(LabelTemplate, "text")
        document = copy.deepcopy(template.document)
        document["elements"][0]["content"] = "Changed after printing"
        template.document = document
        template.revision += 1
    response = client.post(path, headers={"Idempotency-Key": "extra-copy"})
    assert response.status_code == 409, response.text
    assert "retry funding" in response.json()["detail"]
    retry = client.post(path, headers={"Idempotency-Key": "extra-copy"})
    assert retry.status_code == 409
    assert len(client.get("/api/jobs").json()) == 1
    assert client.get(f"/api/batches/{batch['id']}").json() == history
    worker.tick()
    assert len(worker.backend.batches) == 1


def test_legacy_requeue_requires_batch_access_and_never_changes_requester(accounts):
    admin, alice, bob = accounts
    grant(admin, "alice", "print")
    grant(admin, "bob", "moderator")
    tape, worker = prepare_printer(admin)
    original = direct(alice, tape)
    worker.tick()
    batch = admin.get("/api/batches").json()[0]
    path = f"/api/batches/{batch['id']}/items/{original['labels'][0]['id']}/requeue"
    assert alice.post(path).status_code == 403
    # Batch visibility does not let a moderator bypass funding or take ownership.
    with admin.app.state.factory.begin() as session:
        session.add(PrinterGroup(id="private-group", name="Private", printer_ids=["main"]))
        session.get(PrintJob, original["id"]).destination_id = "private-group"
    assert bob.get(f"/api/jobs/{original['id']}").status_code == 403
    response = bob.post(path, headers={"Idempotency-Key": "moderator-copy"})
    assert response.status_code == 409, response.text
    assert len(admin.get("/api/jobs").json()) == 1
    assert admin.get(f"/api/jobs/{original['id']}").json()["owner_id"] == "alice"
    grant(admin, "bob", "request")
    assert bob.post(path, headers={"Idempotency-Key": "moderator-copy"}).status_code == 403


@pytest.mark.parametrize("outcome", [State.NEEDS_REVIEW, State.FAILED, State.PRINTING])
def test_unconfirmed_attempt_cannot_be_copied(client, outcome):
    original, batch, path, _ = printed(client)
    with client.app.state.factory.begin() as session:
        session.get(BatchItem, (batch["id"], original["labels"][0]["id"])).outcome = outcome
    assert client.post(path).status_code == 409
    assert len(client.get("/api/jobs").json()) == 1


@pytest.mark.parametrize("blocker", ["deleted-template", "retired-printer", "changed-geometry"])
def test_unavailable_saved_content_or_printer_cannot_be_silently_changed(client, blocker):
    original, _, path, _ = printed(client)
    with client.app.state.factory.begin() as session:
        if blocker == "deleted-template":
            retain(session, "templates", "text", "Text", "local-owner", "local-owner")
        elif blocker == "retired-printer":
            session.get(PrinterDevice, "main").config = {"retired": True}
        else:
            saved = session.get(PrintJob, original["id"])
            snapshot = copy.deepcopy(saved.template_snapshot)
            snapshot["render_spec"]["dpi"] = 999
            saved.template_snapshot = snapshot
    assert client.post(path).status_code == 409
    assert len(client.get("/api/jobs").json()) == 1


def test_copy_must_belong_to_the_authorized_batch(client):
    _, batch, _, _ = printed(client)
    other = job(client, client.get("/api/tape-profiles").json()[0]["id"])
    path = f"/api/batches/{batch['id']}/items/{other['labels'][0]['id']}/requeue"
    assert client.post(path).status_code == 404
