from decimal import Decimal
from uuid import uuid4

from conftest import install, profile
from sqlalchemy import delete, select
from test_access_security import accounts as accounts
from test_cost_estimates import preview, set_price
from test_fleet import device, fit, group
from test_granular_printer_permissions import set_permissions
from test_price_consent import submission
from test_runs import run_body

from app.i18n import notice_text
from app.models import LabelCopy, Notification, PrintJob, ResourceGrant, TapeAllocation


def interrupted(accounts, *, priced=True):
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    if priced:
        set_price(admin, cartridge)
    set_permissions(admin, "alice", "view", "view_activity", "submit_directly", "start_own")
    set_permissions(admin, "bob", "view", "view_activity", "start_any")
    with admin.app.state.factory.begin() as session:
        session.add(
            ResourceGrant(
                principal_kind="user",
                principal_id="bob",
                scope_kind="cartridge",
                scope_id=cartridge["id"],
                permission="cartridge.approve_use",
            )
        )
    quote = preview(alice, tape, 3)["cost_estimate"]
    response = alice.post("/api/jobs", json=submission(tape, quote, 3))
    assert response.status_code == 201, response.text
    original = response.json()
    worker = admin.app.state.fleet.workers["main"]
    worker.backend.fail_after = 1
    worker.tick()
    batch = admin.get("/api/batches").json()[0]
    assert batch["state"] == "needs_review"
    detail = admin.get(f"/api/batches/{batch['id']}").json()
    decisions = {
        item["copy_id"]: "failed" for item in detail["items"] if item["outcome"] == "needs_review"
    }
    assert (
        admin.post(
            f"/api/batches/{batch['id']}/review", json={"decisions": decisions, "consumed_mm": 100}
        ).status_code
        == 200
    )
    worker.backend.fail_after = None
    worker.tick()
    assert len(worker.backend.batches) == 1
    return cartridge, original, batch, list(decisions), worker


def body(copies, cartridge=None):
    return {
        "request_id": str(uuid4()),
        "copy_ids": copies,
        "mode": "free" if cartridge else "paid",
        "cartridge_id": cartridge,
    }


def test_free_retry_preserves_requester_old_charge_and_frozen_content(accounts):
    admin, alice, bob = accounts
    cartridge, original, batch, failed, worker = interrupted(accounts)
    before = alice.get("/api/accounts").json()["charges"][0]
    payload = body([failed[0]], cartridge["id"])
    path = f"/api/batches/{batch['id']}/retry-offers"
    result = bob.post(path, json=payload)
    assert result.status_code == 201, result.text
    offer = result.json()[0]
    assert bob.post(path, json=payload).json()[0]["job_id"] == offer["job_id"]
    retry = admin.get(f"/api/jobs/{offer['job_id']}").json()
    assert retry["owner_id"] == "alice" and retry["copies"] == 1
    assert retry["template_snapshot"]["document"] == original["template_snapshot"]["document"]
    assert retry["attribution"]["retry_authorization"]["actor_id"] == "bob"
    assert (
        alice.put(
            f"/api/jobs/{retry['id']}/copies", json={"copies": 2, "expected_copies": 1}
        ).status_code
        == 409
    )
    assert admin.post("/api/queue/print").status_code == 202
    worker.tick()
    charges = alice.get("/api/accounts").json()["charges"]
    assert len(charges) == 2
    assert next(row for row in charges if row["batch_id"] == batch["id"]) == before
    extra = next(row for row in charges if row["batch_id"] != batch["id"])
    assert Decimal(extra["charged"]) == 0 < Decimal(extra["actual_cost"])
    assert worker.backend.batches[0][0].raster == worker.backend.batches[1][0].raster
    assert bob.post(path, json=body([failed[0]], cartridge["id"])).status_code == 409


def test_paid_retry_only_queues_after_requester_accepts_new_quote(accounts):
    admin, alice, bob = accounts
    _, _, batch, failed, worker = interrupted(accounts)
    offer = bob.post(f"/api/batches/{batch['id']}/retry-offers", json=body(failed)).json()[0]
    assert offer["status"] == "pending" and offer["job_id"] is None
    with admin.app.state.factory() as session:
        assert len(list(session.scalars(select(PrintJob)))) == 1
        notice = session.scalar(
            select(Notification).where(Notification.title == "Print retry needs your approval")
        )
        assert notice.recipient_id == "alice"
        assert notice_text(notice, "title", "de") == "Wiederholungsdruck benötigt deine Zustimmung"
        assert notice_text(notice, "message", "de") == (
            "Prüfe ein neues Preisangebot, bevor du einem Wiederholungsdruck auf deine Kosten zustimmst."
        )
        assert session.scalar(
            select(Notification).where(
                Notification.recipient_id == "alice",
                Notification.title == "Print retry needs your approval",
            )
        )
    path = f"/api/retries/{offer['id']}"
    denied = bob.get(path, headers={"Accept-Language": "de"})
    assert denied.status_code == 404
    assert denied.json()["detail"] == "Wiederholungsangebot nicht gefunden."
    assert admin.post(path + "/quote").status_code == 404
    quote = alice.post(path + "/quote").json()
    accept = {
        "quote_id": quote["quote_id"],
        "maximum_price": {
            "currency": "EUR",
            "micros": int(Decimal(quote["quotes"][0]["maximum"]) * 1000000),
        },
    }
    accepted = alice.post(path + "/accept", json=accept)
    assert accepted.status_code == 200, accepted.text
    assert alice.post(path + "/accept", json=accept).json()["job_id"] == accepted.json()["job_id"]
    assert (
        alice.post(
            path + "/accept", json={**accept, "maximum_price": {"currency": "EUR", "micros": 1}}
        ).status_code
        == 409
    )
    assert admin.post("/api/queue/print").status_code == 202
    worker.tick()
    assert len(worker.backend.batches) == 2
    assert Decimal(alice.get("/api/accounts").json()["charges"][0]["charged"]) > 0


def test_retry_requires_start_any_and_excludes_printed_copies_by_default(accounts):
    admin, alice, bob = accounts
    cartridge, original, batch, failed, _ = interrupted(accounts)
    path = f"/api/batches/{batch['id']}/retry-offers"
    set_permissions(admin, "bob", "view", "view_activity", "review")
    assert bob.post(path, json=body(failed, cartridge["id"])).status_code == 403
    set_permissions(admin, "bob", "view", "view_activity", "start_any")
    assert (
        bob.post(path, json=body([original["labels"][0]["id"]], cartridge["id"])).status_code == 409
    )
    assert alice.post(path, json=body(failed, cartridge["id"])).status_code == 403
    assert admin.post(f"/api/batches/{batch['id']}/items/{failed[0]}/requeue").status_code == 409


def test_revocation_during_rendering_stops_free_retry_before_hardware(accounts):
    admin, _, bob = accounts
    cartridge, _, batch, failed, worker = interrupted(accounts)
    result = bob.post(
        f"/api/batches/{batch['id']}/retry-offers", json=body(failed, cartridge["id"])
    )
    assert result.status_code == 201, result.text
    assert admin.post("/api/queue/print").status_code == 202
    original_render = worker._render_reserved

    def revoke(batch_id):
        rendered = original_render(batch_id)
        with admin.app.state.factory.begin() as session:
            session.execute(delete(ResourceGrant).where(ResourceGrant.principal_id == "bob"))
        return rendered

    worker._render_reserved = revoke
    worker.tick()
    assert len(worker.backend.batches) == 1
    with admin.app.state.factory() as session:
        retry_id = result.json()[0]["job_id"]
        assert all(
            row.state.value == "queued"
            for row in session.scalars(select(LabelCopy).where(LabelCopy.job_id == retry_id))
        )


def test_unpriced_free_retry_records_consumption_without_a_requester_charge(accounts):
    admin, alice, bob = accounts
    cartridge, _, batch, failed, worker = interrupted(accounts, priced=False)
    response = bob.post(
        f"/api/batches/{batch['id']}/retry-offers", json=body(failed, cartridge["id"])
    )
    assert response.status_code == 201, response.text
    assert admin.post("/api/queue/print").status_code == 202
    worker.tick()
    with admin.app.state.factory() as session:
        rows = list(
            session.scalars(select(TapeAllocation).where(TapeAllocation.batch_id != batch["id"]))
        )
        assert len(rows) == 1 and rows[0].consumed_mm > 0
        assert rows[0].cost_micros is None and rows[0].charged_micros == "0"


def test_csv_retry_preserves_source_order_and_physical_printer(accounts):
    client, _, _ = accounts
    draft = run_body(client)
    second = device(client)
    destination = group(client, ["main", second])
    draft["destination_id"] = destination
    tape = next(
        row for row in client.get("/api/tape-profiles").json() if row["id"] == draft["tape_profile"]
    )
    cartridge = fit(client, "main", tape)
    fit(client, second, tape)
    run = client.post("/api/runs/prepare", json=draft).json()["run"]
    originals = client.post(f"/api/runs/{run['id']}/submit").json()["jobs"]
    copies = [label["id"] for job in originals for label in job["labels"]]
    main = client.app.state.fleet.workers["main"]
    other = client.app.state.fleet.workers[second]
    main.backend.fail_after = 0
    main.tick()
    batch = client.get("/api/batches").json()[0]
    response = client.post(
        f"/api/batches/{batch['id']}/review",
        json={"decisions": dict.fromkeys(copies, "failed"), "consumed_mm": 40},
    )
    assert response.status_code == 200, response.text
    # Selection order must not reorder the saved CSV print order.
    response = client.post(
        f"/api/batches/{batch['id']}/retry-offers",
        json=body(list(reversed(copies)), cartridge["id"]),
    )
    assert response.status_code == 201, response.text
    retries = [client.get(f"/api/jobs/{row['job_id']}").json() for row in response.json()]
    assert [job["source_row"] for job in retries] == [3, 2]
    assert [job["copies"] for job in retries] == [2, 1]
    assert all(job["template_snapshot"]["retry"]["source_run_id"] == run["id"] for job in retries)
    assert [job["payload"] for job in retries] == [job["payload"] for job in originals]
    main.backend.connected = False
    response = client.post(f"/api/destinations/{destination}/print")
    assert response.status_code == 202, response.text
    other.tick()
    assert not other.backend.batches
    main.backend.connected = True
    main.backend.fail_after = None
    main.tick()
    assert len(main.backend.batches) == 2
    assert [label.copy_id for label in main.backend.batches[-1]] == [
        label["id"] for job in retries for label in job["labels"]
    ]
