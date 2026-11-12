from uuid import uuid4

from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as accounts
from test_cost_estimates import preview, set_price
from test_granular_printer_permissions import set_permissions
from test_price_consent import submission
from test_resource_management import apply

from app.accounts.billing_models import BillingCharge
from app.models import LabelCopy, Notification, PrintJob, State, TapeAllocation

ROOT = "/api/accounts/groups"


def grant(admin, account, user, permission, effect="allow"):
    response = admin.put(
        f"{ROOT}/{account}/access",
        json={
            "principal_kind": "user",
            "principal_id": user,
            "permission": permission,
            "effect": effect,
        },
    )
    assert response.status_code == 204, response.text


def setup(accounts):
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    set_price(admin, cartridge)
    set_permissions(admin, "alice", "view", "submit_directly")
    response = admin.post(ROOT, json={"name": "Verein"})
    assert response.status_code == 201, response.text
    account = response.json()["id"]
    for permission in ("request", "request_transfer", "record_payments"):
        grant(admin, account, "alice", permission)
    for permission in ("approve", "approve_transfer"):
        grant(admin, account, "bob", permission)
    return tape, cartridge, account


def submit_group(alice, tape, account, mode="wait"):
    quote = preview(alice, tape)["cost_estimate"]
    response = alice.post(
        "/api/jobs",
        json={**submission(tape, quote), "billing": {"account_id": account, "mode": mode}},
    )
    assert response.status_code == 201, response.text
    return response.json()


def decision(client, identifier, approve):
    return client.post(
        f"{ROOT}/requests/{identifier}/decision", json={"approve": approve, "reason": "Reviewed"}
    )


def test_funding_preview_is_scoped_to_current_approvers_and_rechecks_access(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    set_permissions(admin, "bob")
    job = submit_group(alice, tape, account)
    funding = job["billing_request"]["id"]
    url = f"{ROOT}/requests/{funding}/preview"
    assert bob.get(f"/api/jobs/{job['id']}/preview").status_code == 403
    record = bob.get(f"{ROOT}/{account}").json()["requests"][0]
    assert record["preview"]["url"] == url
    response = bob.get(url)
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")
    assert response.headers["cache-control"] == "private, no-store"
    grant(admin, account, "bob", "approve", "deny")
    grant(admin, account, "bob", "view")
    assert bob.get(f"{ROOT}/{account}").json()["requests"][0]["preview"] is None
    assert bob.get(url).status_code == 404
    grant(admin, account, "bob", "approve")
    assert decision(bob, funding, False).status_code == 200
    assert bob.get(url).status_code == 200
    grant(admin, account, "bob", "approve", "deny")
    assert bob.get(url).status_code == 404
    assert alice.get(url).status_code == 200
    assert bob.get(f"{ROOT}/requests/not-a-request/preview").status_code == 404


def test_wait_rejection_holds_until_explicit_personal_choice(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account)
    assert job["payers"] == [
        {"kind": "group", "id": account, "name": "Verein", "note": "Awaiting approval"}
    ]
    funding = job["billing_request"]["id"]
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    with admin.app.state.factory() as session:
        assert (
            session.scalar(select(LabelCopy.state).where(LabelCopy.job_id == job["id"]))
            == State.QUEUED
        )
    grant(admin, account, "alice", "approve")
    assert decision(alice, funding, True).status_code == 403
    assert decision(bob, funding, False).status_code == 200
    worker.tick()
    with admin.app.state.factory() as session:
        assert (
            session.scalar(select(LabelCopy.state).where(LabelCopy.job_id == job["id"]))
            == State.QUEUED
        )
    assert (
        alice.post(f"{ROOT}/requests/{funding}/resolve", json={"cancel": False}).status_code == 200
    )
    worker.tick()
    with admin.app.state.factory() as session:
        assert (
            session.scalar(select(LabelCopy.state).where(LabelCopy.job_id == job["id"]))
            == State.PRINTED
        )
        assert not list(session.scalars(select(BillingCharge)))


def test_direct_permission_and_mixed_jobs_preserve_requester_costs(accounts):
    admin, alice, _ = accounts
    tape, _, account = setup(accounts)
    quote = preview(alice, tape)["cost_estimate"]
    body = {**submission(tape, quote), "billing": {"account_id": account, "mode": "direct"}}
    assert alice.post("/api/jobs", json=body).status_code == 403
    grant(admin, account, "alice", "direct")
    job = submit_group(alice, tape, account, "direct")
    personal = alice.post("/api/jobs", json=submission(tape, preview(alice, tape)["cost_estimate"]))
    assert personal.status_code == 201
    admin.app.state.fleet.workers["main"].tick()
    with admin.app.state.factory() as session:
        allocations = list(session.scalars(select(TapeAllocation)))
        charges = list(session.scalars(select(BillingCharge)))
        assert len(allocations) == len(charges) == 1
        assert 0 < int(charges[0].amount_micros) < int(allocations[0].charged_micros)
        assert session.get(PrintJob, job["id"]).owner_id == "alice"
        expected = int(allocations[0].charged_micros) - int(charges[0].amount_micros)
    from decimal import Decimal

    balance = alice.get("/api/accounts").json()["balances"][0]
    assert int(Decimal(balance["owed"]) * 1000000) == expected
    batch = admin.get("/api/batches").json()[0]
    assert {(payer["kind"], payer["id"]) for payer in batch["payers"]} == {
        ("group", account),
        ("user", "alice"),
    }


def test_risk_partial_payment_becomes_transfer_and_reimbursement_once(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account, "risk")
    assert job["payers"][0]["kind"] == "user"
    assert job["payers"][0]["note"] == "Awaiting group approval: Verein"
    admin.app.state.fleet.workers["main"].tick()
    assert (
        admin.post(
            "/api/accounts/repayments",
            json={
                "request_id": str(uuid4()),
                "user_id": "alice",
                "recipient_id": "administrator",
                "amount_minor": 1,
                "currency": "EUR",
                "note": "Received",
            },
        ).status_code
        == 201
    )
    funding = job["billing_request"]["id"]
    assert decision(bob, funding, True).status_code == 200
    assert decision(bob, funding, True).status_code == 200
    with admin.app.state.factory() as session:
        charges = list(session.scalars(select(BillingCharge)))
        assert len(charges) == 2
        reimbursement = next(charge for charge in charges if charge.kind == "reimbursement")
        assert reimbursement.recipient_id == "alice" and int(reimbursement.amount_micros) == 10000
        assert sum(int(charge.amount_micros) for charge in charges) == int(
            session.scalar(select(TapeAllocation)).charged_micros
        )
    assert alice.get("/api/accounts").json()["balances"][0]["owed"] == "0.000000"
    report = alice.get("/api/accounts").json()["group_cartridge_balances"]
    assert {row["recipient_id"] for row in report} == {"alice", "administrator"}
    batch = admin.get("/api/batches").json()[0]
    assert batch["payers"] == [{"kind": "group", "id": account, "name": "Verein"}]


def test_member_owned_cartridge_creates_group_obligation(accounts):
    admin, alice, bob = accounts
    tape, cartridge, account = setup(accounts)
    apply(admin, {"kind": "cartridge", "identifier": cartridge["id"], "owner_id": "alice"})
    job = submit_group(alice, tape, account)
    assert decision(bob, job["billing_request"]["id"], True).status_code == 200
    admin.app.state.fleet.workers["main"].tick()
    with admin.app.state.factory() as session:
        charge = session.scalar(select(BillingCharge))
        assert charge.kind == "supply" and charge.recipient_id == "alice"
        assert int(charge.amount_micros) > 0
    rows = alice.get("/api/accounts").json()["group_cartridge_balances"]
    assert len(rows) == 1 and rows[0]["recipient_id"] == "alice"
    assert rows[0]["group_account_id"] == account


def test_payment_report_requires_creditor_confirmation_and_is_idempotent(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account)
    assert decision(bob, job["billing_request"]["id"], True).status_code == 200
    admin.app.state.fleet.workers["main"].tick()
    charge = admin.get(f"{ROOT}/{account}").json()["charges"][0]
    body = {
        "request_id": str(uuid4()),
        "recipient_id": "administrator",
        "currency": "EUR",
        "amount_micros": charge["outstanding_micros"],
        "note": "Bank transfer",
    }
    response = alice.post(f"{ROOT}/{account}/payments", json=body)
    assert response.status_code == 201, response.text
    assert alice.post(f"{ROOT}/{account}/payments", json=body).status_code == 201
    payment = response.json()["id"]
    assert decision(alice, payment, True).status_code == 403
    assert decision(bob, payment, True).status_code == 403
    assert admin.get(f"{ROOT}/{account}").json()["charges"][0]["outstanding_micros"] > 0
    before = admin.get("/api/accounts").json()["group_balances"][0]["owed"]
    assert float(before) > 0
    assert decision(admin, payment, True).status_code == 200
    assert decision(admin, payment, True).status_code == 200
    assert admin.get(f"{ROOT}/{account}").json()["charges"][0]["outstanding_micros"] == 0
    assert admin.get("/api/accounts").json()["group_balances"][0]["owed"] == "0.000000"


def test_tape_usage_group_balances_follow_user_filter_and_account_access(accounts):
    from decimal import Decimal

    from test_usage_accounts import permissions

    admin, alice, bob = accounts
    tape, cartridge, account = setup(accounts)
    job = submit_group(alice, tape, account)
    assert alice.get("/api/accounts").json()["group_balances"] == []
    assert decision(bob, job["billing_request"]["id"], True).status_code == 200
    admin.app.state.fleet.workers["main"].tick()
    charge = admin.get(f"{ROOT}/{account}").json()["charges"][0]
    for client in (admin, alice):
        report = client.get("/api/accounts").json()
        row = report["group_cartridge_balances"][0]
        assert row["group_account_id"] == account and row["requester_name"] == "Verein"
        assert row["recipient_id"] == "administrator" and row["cartridge_id"] == cartridge["id"]
        assert Decimal(row["owed"]) * 1000000 == charge["outstanding_micros"]
        assert report["cartridge_balances"][0]["owed"] == "0.000000"
    assert admin.get("/api/accounts?user_id=bob").json()["group_balances"] == []
    assert admin.get("/api/accounts?user_id=alice").json()["group_balances"]
    permissions(admin, "bob", "usage.view_others")
    assert bob.get("/api/accounts?all_users=true").json()["group_balances"] == []
    grant(admin, account, "bob", "view")
    assert bob.get("/api/accounts?all_users=true").json()["group_balances"]
    assert bob.get("/api/accounts").json()["group_balances"] == []
    grant(admin, account, "bob", "view", "deny")
    assert bob.get("/api/accounts?all_users=true").json()["group_balances"] == []


def test_notifications_recheck_access_and_never_route_to_shared_channels(accounts):
    from app.accounts.billing_notifications import visible
    from app.authn.auth import actor_for_user
    from app.models import NotificationEndpoint, User
    from app.notifications.notification_routing import endpoint_message

    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account)
    funding = job["billing_request"]["id"]
    with admin.app.state.factory() as session:
        notices = [
            n
            for n in session.scalars(select(Notification))
            if n.context.get("billing_request_id") == funding
        ]
        assert {notice.recipient_id for notice in notices} == {"administrator", "bob"}
        notice = next(n for n in notices if n.recipient_id == "bob")
        endpoint = NotificationEndpoint(
            owner_id=None, enabled=True, kinds=["general"], transport="ntfy"
        )
        assert endpoint_message(session, notice, endpoint) is None
        assert visible(session, actor_for_user(session, session.get(User, "bob")), notice)
    grant(admin, account, "bob", "approve", "deny")
    assert not bob.get("/api/inbox").json()["items"]
    assert decision(bob, funding, True).status_code == 403
    assert decision(admin, funding, True).status_code == 200
    assert any(
        n["title"] == "Group account request updated"
        for n in alice.get("/api/inbox").json()["items"]
    )


def test_historical_transfer_requires_approval_and_cannot_claim_twice(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    assert (
        alice.post(
            "/api/jobs", json=submission(tape, preview(alice, tape)["cost_estimate"])
        ).status_code
        == 201
    )
    admin.app.state.fleet.workers["main"].tick()
    history = alice.get(f"{ROOT}/history").json()[0]
    batch_id = history["batch_id"]
    assert admin.get(f"/api/batches/{batch_id}").json()["payers"] == [
        {"kind": "user", "id": "alice", "name": "alice"}
    ]
    assert history["previews"] and history["previews"][0]["copies"] > 0
    url = history["previews"][0]["url"]
    image = alice.get(url)
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert image.headers["cache-control"] == "private, no-store"
    assert bob.get(url).status_code == 404
    assert admin.get(url).status_code == 404
    body = {"request_id": str(uuid4()), "batch_id": history["batch_id"]}
    response = alice.post(f"{ROOT}/{account}/transfers", json=body)
    assert response.status_code == 201, response.text
    assert alice.post(f"{ROOT}/{account}/transfers", json=body).status_code == 201
    assert (
        alice.post(
            f"{ROOT}/{account}/transfers", json={**body, "request_id": str(uuid4())}
        ).status_code
        == 409
    )
    assert decision(bob, response.json()["id"], True).status_code == 200
    assert admin.get(f"/api/batches/{batch_id}").json()["payers"] == [
        {"kind": "group", "id": account, "name": "Verein"}
    ]
    assert (
        alice.post(
            f"{ROOT}/{account}/transfers", json={**body, "request_id": str(uuid4())}
        ).status_code
        == 409
    )


def test_historical_previews_exclude_other_requesters_in_the_same_batch(accounts):
    admin, alice, bob = accounts
    tape, _, _ = setup(accounts)
    set_permissions(admin, "bob", "view", "submit_directly")
    for client in (alice, bob):
        assert (
            client.post(
                "/api/jobs", json=submission(tape, preview(client, tape)["cost_estimate"])
            ).status_code
            == 201
        )
    admin.app.state.fleet.workers["main"].tick()
    a = alice.get(f"{ROOT}/history").json()[0]
    b = bob.get(f"{ROOT}/history").json()[0]
    assert a["batch_id"] == b["batch_id"]
    assert len(a["previews"]) == len(b["previews"]) == 1
    assert a["previews"][0]["job_id"] != b["previews"][0]["job_id"]
    assert alice.get(b["previews"][0]["url"]).status_code == 404
    assert bob.get(a["previews"][0]["url"]).status_code == 404
