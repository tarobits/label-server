"""Payer reports must never become credit without an authorized, atomic decision."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_access_security import accounts as accounts

from app.models import AuditEvent, PaymentReport, UsageAdjustment

ROOT = "/api/accounts/payment-reports"


def payment(**changes):
    return {
        "request_id": str(uuid4()),
        "recipient_id": "bob",
        "amount_minor": 408,
        "currency": "EUR",
        "note": "Bank transfer",
        **changes,
    }


def stored(admin):
    with admin.app.state.factory() as session:
        return (
            [(r.id, r.status) for r in session.scalars(select(PaymentReport))],
            [(a.id, a.amount_minor) for a in session.scalars(select(UsageAdjustment))],
        )


def test_reporting_does_not_change_balance_and_confirmation_is_once_only(accounts):
    admin, alice, bob = accounts
    body = payment()
    before = alice.get("/api/accounts").json()["balances"]
    created = alice.post(ROOT, json=body)
    assert created.status_code == 201, created.text
    identifier = created.json()["id"]
    assert created.json()["can_cancel"] and not created.json()["can_review"]
    assert alice.get("/api/accounts").json()["balances"] == before
    assert stored(admin) == ([(identifier, "pending")], [])
    assert alice.post(ROOT, json=body).json()["id"] == identifier
    assert alice.post(f"{ROOT}/{identifier}/approve").status_code == 403
    assert bob.post(f"{ROOT}/{identifier}/cancel").status_code == 403
    approved = bob.post(f"{ROOT}/{identifier}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert bob.post(f"{ROOT}/{identifier}/approve").status_code == 200
    assert bob.post(f"{ROOT}/{identifier}/reject").status_code == 409
    assert alice.post(f"{ROOT}/{identifier}/cancel").status_code == 409
    assert stored(admin) == ([(identifier, "approved")], [(identifier, 408)])
    assert alice.get("/api/accounts").json()["balances"][0]["owed"] == "-4.080000"
    with admin.app.state.factory() as session:
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(AuditEvent.action == "payment.approved")
                ).all()
            )
            == 1
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_minor": 0},
        {"amount_minor": -1},
        {"amount_minor": True},
        {"amount_minor": 1.5},
        {"amount_minor": 1_000_000_001},
        {"currency": "eur"},
        {"note": " "},
        {"user_id": "bob"},
        {"recipient_id": "alice"},
    ],
)
def test_invalid_payment_report_cannot_create_credit_or_poison_next_request(accounts, changes):
    admin, alice, _ = accounts
    assert alice.post(ROOT, json=payment(**changes)).status_code == 422
    assert stored(admin) == ([], [])
    assert alice.post(ROOT, json=payment()).status_code == 201
    assert stored(admin)[1] == []


def test_reports_are_private_and_cannot_reuse_another_payers_reference(accounts):
    admin, alice, bob = accounts
    body = payment(recipient_id="administrator")
    identifier = alice.post(ROOT, json=body).json()["id"]
    assert bob.get("/api/accounts").json()["payment_reports"] == []
    assert bob.post(ROOT, json=body).status_code == 409
    assert bob.post(f"{ROOT}/{identifier}/approve").status_code == 403
    assert alice.post(ROOT, json={**body, "amount_minor": 409}).status_code == 409
    csrf = admin.headers.pop("X-CSRF-Token")
    assert admin.post(f"{ROOT}/{identifier}/approve").status_code == 403
    admin.headers["X-CSRF-Token"] = csrf
    assert (
        admin.post(
            f"{ROOT}/{identifier}/approve", headers={"Origin": "https://other.example"}
        ).status_code
        == 403
    )
    assert stored(admin) == ([(identifier, "pending")], [])
    assert admin.post(f"{ROOT}/{identifier}/approve").status_code == 200


def test_competing_approval_and_cancellation_have_one_winner(accounts):
    admin, alice, bob = accounts
    identifier = alice.post(ROOT, json=payment()).json()["id"]
    barrier = Barrier(2)

    def decide(client, decision):
        barrier.wait(timeout=5)
        return client.post(f"{ROOT}/{identifier}/{decision}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        approval = pool.submit(decide, bob, "approve")
        cancellation = pool.submit(decide, alice, "cancel")
        responses = [approval.result(timeout=10), cancellation.result(timeout=10)]
    assert sorted(response.status_code for response in responses) == [200, 409]
    reports, adjustments = stored(admin)
    expected = "approved" if responses[0].status_code == 200 else "cancelled"
    assert reports == [(identifier, expected)]
    assert adjustments == ([(identifier, 408)] if expected == "approved" else [])
    assert alice.post(ROOT, json=payment()).status_code == 201


def test_failed_approval_rolls_back_credit_and_is_retryable(accounts, monkeypatch):
    from app.accounts import accounting_api  # noqa: F401

    admin, alice, bob = accounts
    identifier = alice.post(ROOT, json=payment()).json()["id"]
    original = accounting_api.payment_audit

    def fail_after_adjustment(session, report, action):
        if action == "approved":
            assert session.get(UsageAdjustment, identifier) is not None
            raise RuntimeError("injected audit failure")
        return original(session, report, action)

    with monkeypatch.context() as patch:
        patch.setattr(accounting_api, "payment_audit", fail_after_adjustment)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            bob.post(f"{ROOT}/{identifier}/approve")
    assert stored(admin) == ([(identifier, "pending")], [])
    assert bob.post(f"{ROOT}/{identifier}/approve").status_code == 200
    assert stored(admin) == ([(identifier, "approved")], [(identifier, 408)])


def test_recipient_cannot_make_negative_corrections_even_through_preview(accounts):
    admin, alice, bob = accounts
    body = {**payment(), "user_id": "alice", "amount_minor": -50}
    for path in ("/api/accounts/repayments/preview", "/api/accounts/repayments"):
        assert bob.post(path, json=body).status_code == 403
        assert alice.post(path, json=body).status_code == 403
    assert stored(admin) == ([], [])
    assert admin.post("/api/accounts/repayments", json=body).status_code == 201
    assert stored(admin)[1] == [(body["request_id"], -50)]
