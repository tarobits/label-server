"""Confirmed completion, per-item preferences, and recipient boundaries."""

import time

import pytest
from conftest import install, job, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture
from test_image_jobs import upload
from test_notification_routing import endpoint
from test_runs import run_body

from app.config import Settings
from app.models import Batch, Notification, NotificationDelivery, PrintJob, Role, User
from app.notification_routing import deliver_routed_pending, endpoint_message
from app.notifications import enqueue_print_completions
from app.submissions import input_fingerprint

accounts = account_fixture


def completions(client):
    with client.app.state.factory() as session:
        return list(
            session.scalars(
                select(Notification).where(Notification.kind.in_(["job_printed", "batch_printed"]))
            )
        )


def test_success_is_once_per_item_and_batch_with_item_opt_out(client):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    first = job(client, tape["id"], 3)
    muted = client.post(
        "/api/jobs",
        json={
            "tape_profile": tape["id"],
            "data": {"text": "Silent"},
            "notify_on_completion": False,
        },
    ).json()
    worker = client.app.state.fleet.workers["main"]
    worker.tick()
    worker.tick()
    with client.app.state.factory.begin() as session:
        enqueue_print_completions(session, session.scalar(select(Batch)))
    notices = completions(client)
    assert sorted(n.kind for n in notices) == ["batch_printed", "job_printed"]
    personal = next(n for n in notices if n.kind == "job_printed")
    assert personal.context == {"job_id": first["id"]}
    assert "3 copies printed" in personal.message
    assert "4 labels printed" in next(n.message for n in notices if n.kind == "batch_printed")
    assert client.get(f"/api/jobs/{muted['id']}").json()["notify_on_completion"] is False


@pytest.mark.parametrize("decision", ["printed", "queued", "cancelled"])
def test_uncertain_copies_wait_for_review_and_retries_do_not_duplicate(client, decision):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    item = job(client, tape["id"], 2)
    worker = client.app.state.fleet.workers["main"]
    worker.backend.fail_after = 1
    worker.tick()
    assert completions(client) == []
    batch = client.get("/api/batches").json()[0]
    response = client.post(
        f"/api/batches/{batch['id']}/review",
        json={
            "decisions": {item["labels"][1]["id"]: decision},
            "consumed_mm": 60,
        },
    )
    assert response.status_code == 200, response.text
    if decision == "queued":
        assert completions(client) == []
        worker.backend.fail_after = None
        client.post("/api/queue/print")
        worker.tick()
    notices = completions(client)
    assert sorted(n.kind for n in notices) == (
        [] if decision == "cancelled" else ["batch_printed", "job_printed"]
    )


def test_completed_item_in_partial_batch_is_not_delayed_or_notified_twice(client):
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    first, second = job(client, tape["id"]), job(client, tape["id"])
    worker = client.app.state.fleet.workers["main"]
    worker.backend.fail_after = 1
    worker.tick()
    assert [n.context["job_id"] for n in completions(client)] == [first["id"]]
    batch = client.get("/api/batches").json()[0]
    assert (
        client.post(
            f"/api/batches/{batch['id']}/review",
            json={
                "decisions": {second["labels"][0]["id"]: "printed"},
                "consumed_mm": 120,
            },
        ).status_code
        == 200
    )
    assert len(completions(client)) == 3


def test_personal_completion_is_owner_only_and_opt_out_cancels_retry(accounts):
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    request = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {"tape_profile": tape["id"], "data": {"text": "Private"}},
        },
    ).json()
    approved = admin.post(f"/api/requests/{request['id']}/approve").json()
    identifier = approved["job_ids"][0]
    factory = admin.app.state.factory
    with factory.begin() as session:
        for owner in ("alice", "bob", "administrator"):
            session.get(User, owner).email = f"{owner}@example.invalid"
            endpoint(
                session,
                owner,
                owner_id=owner,
                transport="email",
                email=f"{owner}@example.invalid",
                kinds=["job_printed"],
                all_printers=False,
            )
        endpoint(session, "shared", kinds=["job_printed"])
    admin.app.state.fleet.workers["main"].tick()
    sent = []

    def fail(channel, notice):
        sent.append(channel.id)
        raise OSError("Simulated delivery failure")

    now = time.time() + 1
    deliver_routed_pending(factory, Settings(), now, fail)
    assert sent == ["alice"]  # Request-only users can receive their own completion.
    url = f"/api/jobs/{identifier}/completion-notification"
    for other in (admin, bob):
        assert other.put(url, json={"notify_on_completion": False}).status_code == 403
    assert alice.put(url, json={"notify_on_completion": False}).status_code == 200
    assert alice.put(url, json={"notify_on_completion": True}).status_code == 200
    deliver_routed_pending(factory, Settings(), now + 60, fail)
    assert sent == ["alice"]
    with factory() as session:
        assert session.scalar(select(NotificationDelivery)).cancelled


def test_batch_completion_uses_per_printer_choices_and_current_moderator_access(accounts):
    admin, alice, _ = accounts
    factory = admin.app.state.factory
    with factory.begin() as session:
        session.get(User, "alice").email = "alice@example.invalid"
        channel = endpoint(
            session,
            "alice",
            owner_id="alice",
            transport="email",
            email="alice@example.invalid",
            kinds=["general"],
            destination_ids=["main"],
            printer_kinds={"main": ["batch_printed"]},
        )
        notice = Notification(
            kind="batch_printed",
            title="Finished",
            message="2 labels printed.",
            path="/",
            context={"printer_id": "main"},
        )
        assert endpoint_message(session, notice, channel) is None
        role = session.get(Role, "alice-access")
        role.permissions = [{"kind": "destination", "destination_id": "main", "level": "moderator"}]
        session.flush()
        assert (
            endpoint_message(session, notice, channel).message == "Mock printer: 2 labels printed."
        )
        channel.printer_kinds = {"main": []}
        assert endpoint_message(session, notice, channel) is None
        channel.printer_kinds = {"main": ["batch_printed"]}
        role.permissions = []
        session.flush()
        assert endpoint_message(session, notice, channel) is None
    alice.app.state.settings.smtp_host = "smtp.invalid"
    alice.app.state.settings.smtp_from = "sender@example.invalid"
    assert (
        alice.put(
            "/api/auth/email/subscription",
            json={
                "kinds": ["job_printed"],
                "all_printers": False,
            },
        ).status_code
        == 204
    )
    assert (
        alice.put(
            "/api/auth/email/subscription",
            json={
                "kinds": ["batch_printed"],
                "destination_ids": ["main"],
            },
        ).status_code
        == 403
    )


@pytest.mark.parametrize("approval", [False, True])
def test_csv_and_approval_preserve_item_opt_out(accounts, approval):
    client = accounts[0]
    body = run_body(client)
    body["rows"][0]["notify_on_completion"] = False
    run = client.post("/api/runs/prepare", json=body).json()["run"]
    assert [row["notify_on_completion"] for row in run["rows"]] == [False, True]
    if approval:
        request = client.post("/api/requests", json={"kind": "run", "run_id": run["id"]}).json()
        response = client.post(f"/api/requests/{request['id']}/approve")
        assert response.status_code == 200, response.text
        identifiers = response.json()["job_ids"]
    else:
        response = client.post(f"/api/runs/{run['id']}/submit")
        assert response.status_code == 200, response.text
        identifiers = [job["id"] for job in response.json()["jobs"]]
    with client.app.state.factory() as session:
        assert [
            session.get(PrintJob, identifier).notify_on_completion for identifier in identifiers
        ] == [False, True]


@pytest.mark.parametrize("approval", [False, True])
def test_image_submissions_preserve_item_opt_out(accounts, approval):
    client = accounts[0]
    tape = profile(client)
    asset, _ = upload(client)
    body = {"tape_profile": tape["id"], "image_asset": asset, "notify_on_completion": False}
    if approval:
        request = client.post("/api/requests", json={"kind": "image", "input": body}).json()
        response = client.post(f"/api/requests/{request['id']}/approve")
        assert response.status_code == 200, response.text
        identifier = response.json()["job_ids"][0]
        result = client.get(f"/api/jobs/{identifier}").json()
    else:
        response = client.post("/api/image-jobs", json=body)
        assert response.status_code == 201, response.text
        result = response.json()
    assert result["notify_on_completion"] is False


def test_default_preference_preserves_legacy_idempotency():
    for legacy, current in [
        ({"copies": 2}, {"copies": 2, "notify_on_completion": True}),
        ({"input": {"copies": 2}}, {"input": {"copies": 2, "notify_on_completion": True}}),
        (
            {"rows": [{"source_row": 2}]},
            {"rows": [{"source_row": 2, "notify_on_completion": True}]},
        ),
    ]:
        assert input_fingerprint(legacy) == input_fingerprint(current)
    assert input_fingerprint({}) != input_fingerprint({"notify_on_completion": False})
