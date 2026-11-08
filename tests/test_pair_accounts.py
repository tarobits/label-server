from uuid import uuid4

from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as accounts
from test_granular_printer_permissions import set_permissions, submit
from test_resource_management import apply

from app.models import AuditEvent, TapeAllocation, UsageAdjustment


def test_owner_snapshots_keep_debts_with_original_recipient_and_hide_unrelated_accounts(accounts):
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    admin.put(
        f"/api/cartridges/{cartridge['id']}/price", json={"price_minor": 2000, "currency": "EUR"}
    )
    set_permissions(admin, "alice", "view", "submit_directly")
    assert submit(alice, tape).status_code == 201
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    apply(admin, {"kind": "cartridge", "identifier": cartridge["id"], "owner_id": "bob"})
    assert submit(alice, tape).status_code == 201
    worker.tick()
    accounts = alice.get("/api/accounts").json()
    assert {row["recipient_id"] for row in accounts["balances"]} == {"administrator", "bob"}
    bob_accounts = bob.get("/api/accounts").json()
    assert len(bob_accounts["balances"]) == 1
    assert bob_accounts["balances"][0]["recipient_id"] == "bob"
    assert len(bob_accounts["charges"]) == 1
    assert "payload" not in bob_accounts["charges"][0]
    assert bob.get("/api/accounts?all_users=true").status_code == 403
    assert bob.get("/api/accounts?user_id=alice").status_code == 403
    with admin.app.state.factory() as session:
        assert {row.recipient_id for row in session.scalars(select(TapeAllocation))} == {
            "administrator",
            "bob",
        }


def test_only_recipient_or_accounting_editor_records_repayment_once(accounts):
    admin, alice, bob = accounts
    payment = {
        "request_id": str(uuid4()),
        "user_id": "alice",
        "recipient_id": "bob",
        "amount_minor": 100,
        "currency": "EUR",
        "note": "Cash received",
    }
    assert alice.post("/api/accounts/repayments", json=payment).status_code == 403
    response = bob.post("/api/accounts/repayments", json=payment)
    assert response.status_code == 201, response.text
    assert bob.post("/api/accounts/repayments", json=payment).status_code == 201
    assert (
        bob.post("/api/accounts/repayments", json={**payment, "amount_minor": 200}).status_code
        == 409
    )
    assert alice.get("/api/accounts").json()["balances"][0]["owed"] == "-1.000000"
    with admin.app.state.factory() as session:
        assert len(session.scalars(select(UsageAdjustment)).all()) == 1
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "account.adjusted")
        ).all()
        assert len(events) == 1 and events[0].fields["actor_id"]["value"] == "bob"
    assert (
        admin.post(
            "/api/accounts/repayments",
            json={**payment, "request_id": str(uuid4()), "amount_minor": -50, "note": "Correction"},
        ).status_code
        == 201
    )
    assert alice.get("/api/accounts").json()["balances"][0]["owed"] == "-0.500000"


def test_own_cartridge_printing_tracks_cost_without_self_debt(accounts):
    admin, _, _ = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    admin.put(f"/api/cartridges/{cartridge['id']}/price", json={"price_minor": 2000})
    submit(admin, tape)
    admin.app.state.fleet.workers["main"].tick()
    report = admin.get("/api/accounts").json()
    assert report["balances"] == []
    assert report["charges"][0]["own_cartridge"]
    assert float(report["charges"][0]["actual_cost"]) > 0
