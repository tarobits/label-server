"""Extra copies use saved label content and new, authorized submission ownership."""

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


def test_requeue_one_frozen_copy_preserves_history_and_retry_is_idempotent(client):
    original, batch, path, worker = printed(client)
    history = client.get(f"/api/batches/{batch['id']}").json()
    with client.app.state.factory.begin() as session:
        template = session.get(LabelTemplate, "text")
        document = copy.deepcopy(template.document)
        document["elements"][0]["content"] = "Changed after printing"
        template.document = document
        template.revision += 1
    response = client.post(path, headers={"Idempotency-Key": "extra-copy"})
    assert response.status_code == 201, response.text
    extra = response.json()
    assert extra["id"] != original["id"]
    assert extra["copies"] == len(extra["labels"]) == 1
    assert extra["status"] == "queued"
    assert extra["payload"] == original["payload"]
    assert extra["template_snapshot"]["document"] == original["template_snapshot"]["document"]
    assert extra["template_snapshot"]["render_spec"] == original["template_snapshot"]["render_spec"]
    assert extra["destination_id"] == batch["printer_id"]
    retry = client.post(path, headers={"Idempotency-Key": "extra-copy"})
    assert retry.status_code == 201 and retry.json()["id"] == extra["id"]
    assert len(client.get("/api/jobs").json()) == 2
    assert client.get(f"/api/batches/{batch['id']}").json() == history
    worker.tick()
    first, second = worker.backend.batches[0][0], worker.backend.batches[1][0]
    assert first.raster == second.raster
    assert (first.pixel_width, first.pixel_height, first.dpi_x, first.dpi_y) == (
        second.pixel_width,
        second.pixel_height,
        second.dpi_x,
        second.dpi_y,
    )
    again = client.post(path, headers={"Idempotency-Key": "another-copy"})
    assert again.status_code == 201 and again.json()["id"] != extra["id"]


def test_requeue_requires_batch_access_and_attributes_new_copy_to_actor(accounts):
    admin, alice, bob = accounts
    grant(admin, "alice", "print")
    grant(admin, "bob", "moderator")
    tape, worker = prepare_printer(admin)
    original = direct(alice, tape)
    worker.tick()
    batch = admin.get("/api/batches").json()[0]
    path = f"/api/batches/{batch['id']}/items/{original['labels'][0]['id']}/requeue"
    assert alice.post(path).status_code == 403
    # A physical printer moderator can repeat a frozen batch label even if the
    # job's group is not readable to them; the new job goes to that printer.
    with admin.app.state.factory.begin() as session:
        session.add(PrinterGroup(id="private-group", name="Private", printer_ids=["main"]))
        session.get(PrintJob, original["id"]).destination_id = "private-group"
    assert bob.get(f"/api/jobs/{original['id']}").status_code == 403
    response = bob.post(path, headers={"Idempotency-Key": "moderator-copy"})
    assert response.status_code == 201, response.text
    extra = response.json()
    assert extra["owner_id"] == "bob"
    assert extra["destination_id"] == "main"
    assert extra["authorization_basis"] == "print"
    assert extra["attribution"]["requested_by"] == {"id": "bob", "name": "bob"}
    assert extra["attribution"]["authorization"]["kind"] == "direct"
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
