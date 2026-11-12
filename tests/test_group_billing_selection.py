"""Transfers freeze selected labels and never broaden preview or billing access."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import select
from test_access_security import accounts as accounts
from test_cost_estimates import preview
from test_granular_printer_permissions import set_permissions
from test_group_billing import ROOT, decision, grant, setup, submit_group
from test_price_consent import submission

from app.accounts.billing_models import BillingCharge, BillingRequest
from app.models import TapeAllocation, UnitCharge


def personal(client, tape, text, copies=1):
    body = submission(tape, preview(client, tape, copies=copies)["cost_estimate"], copies=copies)
    response = client.post("/api/jobs", json={**body, "data": {"text": text}, "copies": copies})
    assert response.status_code == 201, response.text
    return response.json()


def transfer(client, account, batch, jobs, **extra):
    return client.post(
        f"{ROOT}/{account}/transfers",
        json={
            "request_id": str(uuid4()),
            "batch_id": batch,
            "job_ids": jobs,
            **extra,
        },
    )


def test_selected_labels_include_all_copies_and_exact_recorded_leader_share(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    first = personal(alice, tape, "Selected", 2)
    second = personal(alice, tape, "Not selected")
    admin.app.state.fleet.workers["main"].tick()
    history = alice.get(f"{ROOT}/history").json()[0]
    batch = history["batch_id"]
    with admin.app.state.factory() as session:
        total = int(session.get(TapeAllocation, (batch, "alice")).charged_micros)
        cost = int(session.get(UnitCharge, (batch, first["id"])).charged_micros)
    assert sum(item["available_micros"] for item in history["labels"]) == total
    response = transfer(alice, account, batch, [first["id"]])
    assert response.status_code == 201, response.text
    funding = response.json()
    assert funding["details"]["amount_micros"] == cost
    prints = bob.get(funding["prints_url"]).json()
    assert [(p["job_id"], p["copies"]) for p in prints["prints"]] == [(first["id"], 2)]
    assert prints["prints"][0]["outcomes"] == {"printed": 2}
    assert prints["batches"][0]["can_view"] is False
    assert alice.get(funding["prints_url"]).json()["batches"][0]["can_view"] is True
    assert decision(bob, funding["id"], True).status_code == 200
    assert decision(bob, funding["id"], True).status_code == 200
    charges = admin.get(f"{ROOT}/{account}").json()["charges"]
    assert len(charges) == 1 and int(charges[0]["amount_micros"]) == cost
    assert charges[0]["source_kind"] == "history"
    assert bob.get(charges[0]["prints_url"]).json()["prints"][0]["copies"] == 2
    assert bob.get(prints["prints"][0]["url"]).status_code == 200
    assert transfer(alice, account, batch, [first["id"]]).status_code == 409
    assert transfer(alice, account, batch, [second["id"]]).status_code == 201


def test_overlapping_requests_are_blocked_but_disjoint_labels_can_be_requested(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    first = personal(alice, tape, "One")
    second = personal(alice, tape, "Two")
    admin.app.state.fleet.workers["main"].tick()
    batch = alice.get(f"{ROOT}/history").json()[0]["batch_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: transfer(alice, account, batch, [first["id"]]), range(2))
        )
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert transfer(alice, account, batch, [second["id"]]).status_code == 201
    assert transfer(alice, account, batch, [first["id"], second["id"]]).status_code == 409
    assert transfer(alice, account, batch, []).status_code == 422
    assert transfer(alice, account, batch, [first["id"], first["id"]]).status_code == 422
    pending = next(r.json() for r in responses if r.status_code == 201)
    assert decision(bob, pending["id"], False).status_code == 200
    assert transfer(alice, account, batch, [first["id"]]).status_code == 201


def test_previews_and_selection_never_include_another_requester_or_unselected_label(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    set_permissions(admin, "bob", "view", "submit_directly")
    own = personal(alice, tape, "Selected")
    excluded = personal(alice, tape, "Private unselected")
    other = personal(bob, tape, "Other requester")
    admin.app.state.fleet.workers["main"].tick()
    batch = alice.get(f"{ROOT}/history").json()[0]["batch_id"]
    assert transfer(alice, account, batch, [other["id"]]).status_code == 409
    assert transfer(alice, account, batch, ["missing"]).status_code == 409
    funding = transfer(alice, account, batch, [own["id"]]).json()
    url = funding["prints_url"]
    prints = bob.get(url).json()["prints"]
    assert [p["text"] for p in prints] == ["Selected"]
    for job in (excluded, other):
        copy_id = job["labels"][0]["id"]
        assert (
            bob.get(f"{ROOT}/requests/{funding['id']}/items/{copy_id}/preview").status_code == 404
        )
    grant(admin, account, "bob", "approve_transfer", "deny")
    grant(admin, account, "bob", "view")
    assert bob.get(url).status_code == 404
    assert bob.get(prints[0]["url"]).status_code == 404
    # Approving new jobs does not grant historical-transfer preview access.
    assert bob.get(f"{ROOT}/{account}").json()["requests"][0]["prints_url"] is None
    assert alice.get(url).status_code == 200
    grant(admin, account, "bob", "approve_transfer")
    assert decision(bob, funding["id"], True).status_code == 200
    charge = admin.get(f"{ROOT}/{account}").json()["charges"][0]
    image = bob.get(bob.get(charge["prints_url"]).json()["prints"][0]["url"])
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert image.headers["cache-control"] == "private, no-store"
    grant(admin, account, "bob", "approve_transfer", "deny")
    assert bob.get(charge["prints_url"]).status_code == 404


def test_selected_labels_take_paid_credit_first_and_leave_remaining_costs_available(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    personal(alice, tape, "First, not selected")
    second = personal(alice, tape, "Second, selected")
    admin.app.state.fleet.workers["main"].tick()
    batch = alice.get(f"{ROOT}/history").json()[0]["batch_id"]
    payment = admin.post(
        "/api/accounts/repayments",
        json={
            "request_id": str(uuid4()),
            "user_id": "alice",
            "recipient_id": "administrator",
            "amount_minor": 1,
            "currency": "EUR",
            "note": "Received",
        },
    )
    assert payment.status_code == 201, payment.text
    funding = transfer(alice, account, batch, [second["id"]]).json()
    assert decision(bob, funding["id"], True).status_code == 200
    with admin.app.state.factory() as session:
        cost = int(session.get(UnitCharge, (batch, second["id"])).charged_micros)
        charges = list(session.scalars(select(BillingCharge)))
        assert sum(int(c.amount_micros) for c in charges) == cost
        assert sum(int(c.amount_micros) for c in charges if c.kind == "reimbursement") == min(
            cost, 10000
        )
    remaining = alice.get(f"{ROOT}/history").json()[0]
    assert remaining["available_micros"] > 0
    assert remaining["paid_micros"] == max(0, 10000 - cost)


def test_preapproved_and_historical_charges_have_distinct_sources_without_rewriting_ledger(
    accounts,
):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account)
    assert decision(bob, job["billing_request"]["id"], True).status_code == 200
    own = personal(alice, tape, "Historical later")
    admin.app.state.fleet.workers["main"].tick()
    history = alice.get(f"{ROOT}/history").json()[0]
    response = transfer(alice, account, history["batch_id"], [own["id"]])
    assert response.status_code == 201, response.text
    assert decision(bob, response.json()["id"], True).status_code == 200
    charges = admin.get(f"{ROOT}/{account}").json()["charges"]
    assert {c["source_kind"] for c in charges} == {"job", "history"}
    assert {c["kind"] for c in charges} == {"transfer"}
    for charge in charges:
        expected = job["id"] if charge["source_kind"] == "job" else own["id"]
        assert [p["job_id"] for p in bob.get(charge["prints_url"]).json()["prints"]] == [expected]


def test_legacy_whole_batch_transfer_remains_readable_and_idempotent(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = personal(alice, tape, "Legacy transfer")
    admin.app.state.fleet.workers["main"].tick()
    batch = alice.get(f"{ROOT}/history").json()[0]["batch_id"]
    body = {"request_id": str(uuid4()), "batch_id": batch}
    response = alice.post(f"{ROOT}/{account}/transfers", json=body)
    assert response.status_code == 201
    with admin.app.state.factory.begin() as session:
        value = session.get(BillingRequest, body["request_id"])
        value.details = {key: data for key, data in value.details.items() if key != "job_amounts"}
    assert alice.post(f"{ROOT}/{account}/transfers", json=body).status_code == 201
    assert decision(bob, body["request_id"], True).status_code == 200
    details = bob.get(response.json()["prints_url"]).json()
    assert [p["job_id"] for p in details["prints"]] == [job["id"]]
    assert transfer(alice, account, batch, [job["id"]]).status_code == 409


def test_selection_is_part_of_transfer_idempotency_receipt(accounts):
    admin, alice, _ = accounts
    tape, _, account = setup(accounts)
    first = personal(alice, tape, "One")
    second = personal(alice, tape, "Two")
    admin.app.state.fleet.workers["main"].tick()
    batch = alice.get(f"{ROOT}/history").json()[0]["batch_id"]
    identifier = str(uuid4())
    response = transfer(alice, account, batch, [first["id"]], request_id=identifier)
    assert response.status_code == 201
    assert transfer(alice, account, batch, [first["id"]], request_id=identifier).status_code == 201
    assert transfer(alice, account, batch, [second["id"]], request_id=identifier).status_code == 409
