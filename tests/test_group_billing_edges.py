from uuid import uuid4

import pytest
from sqlalchemy import select
from test_access_security import accounts as accounts
from test_auth import change
from test_cost_estimates import preview
from test_group_billing import ROOT, decision, grant, setup, submit_group
from test_price_consent import submission
from test_resource_management import apply

from app.accounts.billing import permissions
from app.accounts.billing_models import BillingCharge, BillingGrant, BillingRequest
from app.authn.access import Actor
from app.models import LabelCopy, State, TapeAllocation, UsageAdjustment


def test_account_rules_use_user_over_role_and_deny_ties(accounts):
    admin, _, _ = accounts
    _, _, account = setup(accounts)
    with admin.app.state.factory.begin() as session:
        for role, effect in (("role-a", "allow"), ("role-b", "deny")):
            session.add(
                BillingGrant(
                    account_id=account,
                    principal_kind="role",
                    principal_id=role,
                    permission="direct",
                    effect=effect,
                )
            )
        session.flush()
        actor = Actor(id="alice", role_ids=frozenset({"role-a", "role-b"}))
        assert "direct" not in permissions(session, actor, account)
        session.add(
            BillingGrant(
                account_id=account,
                principal_kind="user",
                principal_id="alice",
                permission="direct",
                effect="allow",
            )
        )
        session.flush()
        assert "direct" in permissions(session, actor, account)
        session.get(BillingGrant, (account, "user", "alice", "direct")).effect = "deny"
        session.flush()
        assert "direct" not in permissions(session, actor, account)
        assert "direct" in permissions(session, Actor(id="alice", is_admin=True), account)


def test_archiving_and_revocation_hold_approved_work_without_cancelling_it(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account)
    assert decision(bob, job["billing_request"]["id"], True).status_code == 200
    assert (
        admin.put(f"{ROOT}/{account}", json={"name": "Verein", "archived": True}).status_code == 200
    )
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    with admin.app.state.factory() as session:
        assert session.scalar(select(LabelCopy.state)) == State.QUEUED
    admin.put(f"{ROOT}/{account}", json={"name": "Verein", "archived": False})
    grant(admin, account, "alice", "request", "deny")
    worker.tick()
    with admin.app.state.factory() as session:
        assert session.scalar(select(LabelCopy.state)) == State.QUEUED
    grant(admin, account, "alice", "request")
    worker.tick()
    with admin.app.state.factory() as session:
        assert session.scalar(select(LabelCopy.state)) == State.PRINTED


def test_group_supplies_can_claim_unowned_cartridges_later(accounts):
    admin, alice, bob = accounts
    tape, cartridge, account = setup(accounts)
    apply(admin, {"kind": "cartridge", "identifier": cartridge["id"], "owner_id": "bob"})
    assert change(admin, "users", "DELETE", identifier="bob").status_code == 204
    job = submit_group(alice, tape, account)
    assert decision(admin, job["billing_request"]["id"], True).status_code == 200
    admin.app.state.fleet.workers["main"].tick()
    with admin.app.state.factory() as session:
        assert session.scalar(select(BillingCharge)).recipient_id is None
    apply(admin, {"kind": "cartridge", "identifier": cartridge["id"], "owner_id": "alice"})
    with admin.app.state.factory() as session:
        assert session.scalar(select(BillingCharge)).recipient_id == "alice"
    apply(admin, {"kind": "cartridge", "identifier": cartridge["id"], "owner_id": "administrator"})
    with admin.app.state.factory() as session:
        assert session.scalar(select(BillingCharge)).recipient_id == "alice"


def test_cancelling_unprinted_work_withdraws_funding_and_notifications(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account)
    assert alice.delete(f"/api/jobs/{job['id']}").status_code == 200
    with admin.app.state.factory() as session:
        assert session.get(BillingRequest, job["billing_request"]["id"]).status == "withdrawn"
    assert bob.get("/api/inbox").json()["unread"] == 0


def test_preapproved_group_cost_does_not_consume_personal_credit(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    assert (
        admin.post(
            "/api/accounts/repayments",
            json={
                "request_id": str(uuid4()),
                "user_id": "alice",
                "recipient_id": "administrator",
                "amount_minor": 100,
                "currency": "EUR",
                "note": "Personal advance",
            },
        ).status_code
        == 201
    )
    job = submit_group(alice, tape, account)
    assert decision(bob, job["billing_request"]["id"], True).status_code == 200
    admin.app.state.fleet.workers["main"].tick()
    with admin.app.state.factory() as session:
        charges = list(session.scalars(select(BillingCharge)))
        assert len(charges) == 1 and charges[0].kind == "transfer"
        assert charges[0].recipient_id == "administrator"
    assert alice.get("/api/accounts").json()["balances"][0]["owed"] == "-1.000000"


def test_paid_history_reimbursement_preserves_original_payment_and_requires_approval(accounts):
    admin, alice, bob = accounts
    tape, cartridge, account = setup(accounts)
    alice.post("/api/jobs", json=submission(tape, preview(alice, tape)["cost_estimate"]))
    admin.app.state.fleet.workers["main"].tick()
    with admin.app.state.factory() as session:
        allocation = session.scalar(select(TapeAllocation))
        amount = int(allocation.charged_micros)
        batch = allocation.batch_id
    minor = (amount + 9999) // 10000
    payment = {
        "request_id": str(uuid4()),
        "user_id": "alice",
        "recipient_id": "administrator",
        "amount_minor": minor,
        "currency": "EUR",
        "note": "Received",
        "cartridge_allocations": {cartridge["id"]: minor * 10000},
    }
    assert admin.post("/api/accounts/repayments", json=payment).status_code == 201
    transfer = alice.post(
        f"{ROOT}/{account}/transfers", json={"request_id": str(uuid4()), "batch_id": batch}
    ).json()
    assert decision(bob, transfer["id"], True).status_code == 200
    with admin.app.state.factory() as session:
        charge = session.scalar(select(BillingCharge))
        assert charge.kind == "reimbursement" and charge.recipient_id == "alice"
        assert int(charge.amount_micros) == amount
        assert session.get(UsageAdjustment, payment["request_id"]).amount_minor == minor
        assert session.get(TapeAllocation, (batch, "alice")).charged_micros == str(amount)
    with pytest.raises(ValueError, match="immutable"), admin.app.state.factory.begin() as session:
        session.scalar(select(BillingCharge)).amount_micros = "0"


def test_request_access_does_not_grant_printer_access_or_financial_visibility(accounts):
    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account)
    with admin.app.state.factory() as session:
        assert session.scalar(select(BillingCharge)) is None
    assert bob.get(f"/api/jobs/{job['id']}").status_code == 403
    assert alice.get(f"{ROOT}/{account}/access").status_code == 403
    assert alice.get(f"{ROOT}/{account}/audit").status_code == 403
    grant(admin, account, "bob", "approve", "deny")
    grant(admin, account, "bob", "approve_transfer", "deny")
    assert bob.get(f"{ROOT}/{account}").status_code == 403


def test_csv_funding_is_frozen_for_each_row(accounts):
    admin, alice, _ = accounts
    tape, _, account = setup(accounts)
    template = admin.get("/api/templates/text").json()
    body = {
        "billing": {"account_id": account, "mode": "wait"},
        "request_key": str(uuid4()),
        "name": "Verein run",
        "template": "text",
        "expected_revision": template["revision"],
        "tape_profile": tape["id"],
        "csv_text": "Text\nOne\nTwo",
        "mapping": {"text": "Text"},
        "rows": [{"source_row": 2}, {"source_row": 3, "copies": 2}],
    }
    response = alice.post("/api/runs/prepare", json=body)
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    response = alice.post(f"/api/runs/{run['id']}/submit")
    assert response.status_code == 200, response.text
    assert len(response.json()["jobs"]) == 2
    assert all(job["billing_request"]["status"] == "pending" for job in response.json()["jobs"])
    admin.app.state.fleet.workers["main"].tick()
    with admin.app.state.factory() as session:
        assert set(session.scalars(select(LabelCopy.state))) == {State.QUEUED}


def test_later_personal_price_consent_cannot_raise_the_group_authorization(accounts):
    from app.accounts.pricing import remaining_allowance
    from app.models import PrintJob

    admin, alice, bob = accounts
    tape, _, account = setup(accounts)
    job = submit_group(alice, tape, account)
    assert decision(bob, job["billing_request"]["id"], True).status_code == 200
    with admin.app.state.factory.begin() as session:
        stored = session.get(PrintJob, job["id"])
        original = remaining_allowance(session, stored, "EUR")
        assert original is not None
        pricing = stored.template_snapshot["pricing"]
        stored.template_snapshot = {
            **stored.template_snapshot,
            "pricing": {
                **pricing,
                "quotes": {"EUR": original * 10, "USD": original * 10},
                "maximum": {"currency": "EUR", "micros": original * 10},
            },
        }
        assert remaining_allowance(session, stored, "EUR") == original
        assert remaining_allowance(session, stored, "USD") == -1


def test_image_submission_keeps_group_funding_separate_from_print_approval(accounts):
    from test_granular_printer_permissions import set_permissions
    from test_image_jobs import upload

    admin, alice, _ = accounts
    tape, _, account = setup(accounts)
    asset, _ = upload(alice)
    body = {
        "image_asset": asset,
        "tape_profile": tape["id"],
        "copies": 1,
        "billing": {"account_id": account, "mode": "wait"},
    }
    response = alice.post("/api/image-jobs/preview", json=body)
    assert response.status_code == 200, response.text
    body["quote_id"] = response.json()["cost_estimate"]["quote_id"]
    response = alice.post("/api/image-jobs", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["billing_request"]["status"] == "pending"
    set_permissions(admin, "alice", "view", "submit_requests")
    request = alice.post("/api/requests", json={"kind": "image", "input": body})
    assert request.status_code == 201, request.text
    response = admin.post(
        f"/api/requests/{request.json()['id']}/approve", json={"expected_revision": 1}
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_ids"][0]
    job = alice.get(f"/api/jobs/{job_id}").json()
    assert job["billing_request"]["status"] == "pending"
    assert job["owner_id"] == "alice"
