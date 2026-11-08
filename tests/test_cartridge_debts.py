from uuid import uuid4

from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as accounts
from test_auth import change
from test_cost_estimates import set_price
from test_granular_printer_permissions import set_permissions, submit
from test_resource_management import apply

from app.models import Cartridge, PrinterDevice, TapeAllocation


def test_deleted_owner_leaves_grants_and_cartridge_debts_for_next_owner_once(accounts):
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    set_price(admin, cartridge)
    apply(admin, {"kind": "cartridge", "identifier": cartridge["id"], "owner_id": "bob"})
    apply(admin, {"kind": "printer", "identifier": "main", "owner_id": "bob"})
    set_permissions(admin, "alice", "view", "submit_directly")
    worker = admin.app.state.fleet.workers["main"]
    assert submit(alice, tape).status_code == 201
    worker.tick()
    assert change(admin, "users", "DELETE", identifier="bob").status_code == 204
    with admin.app.state.factory() as session:
        assert session.get(Cartridge, cartridge["id"]).owner_id is None
        assert session.get(PrinterDevice, "main").owner_id is None
    assert submit(alice, tape).status_code == 201
    worker.tick()
    report = alice.get("/api/accounts").json()
    assert len(report["balances"]) == 2
    unassigned = next(row for row in report["balances"] if row["recipient_id"] is None)
    assert unassigned["cartridge_id"] == cartridge["id"]
    assert unassigned["recipient_name"] == cartridge["name"]
    preview = admin.post(
        "/api/resource-access/preview",
        json={"kind": "cartridge", "identifier": cartridge["id"], "owner_id": "administrator"},
    )
    assert preview.json()["claims_unassigned_debts"]
    apply(admin, {"kind": "cartridge", "identifier": cartridge["id"], "owner_id": "administrator"})
    with admin.app.state.factory() as session:
        rows = list(session.scalars(select(TapeAllocation)))
        assert {row.recipient_id for row in rows} == {"bob", "administrator"}
        assert next(
            row for row in rows if row.recipient_id == "administrator"
        ).recipient_assigned_at
    apply(admin, {"kind": "cartridge", "identifier": cartridge["id"], "owner_id": "alice"})
    assert {row["recipient_id"] for row in alice.get("/api/accounts").json()["balances"]} == {
        "bob",
        "administrator",
    }


def test_repayments_default_to_oldest_debts_but_allow_specific_cartridge(accounts):
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    first = install(admin, tape["id"])
    set_price(admin, first)
    set_permissions(admin, "alice", "view", "submit_directly")
    worker = admin.app.state.fleet.workers["main"]
    submit(alice, tape)
    worker.tick()
    second = install(admin, tape["id"])
    set_price(admin, second)
    submit(alice, tape)
    worker.tick()
    body = {
        "request_id": str(uuid4()),
        "user_id": "alice",
        "recipient_id": "administrator",
        "amount_minor": 1,
        "currency": "EUR",
        "note": "Payment",
    }
    preview = admin.post("/api/accounts/repayments/preview", json=body).json()
    assert preview["allocations"] == {first["id"]: 10000}
    assert admin.post("/api/accounts/repayments", json=body).json()["cartridge_allocations"] == {
        first["id"]: "10000"
    }
    selected = {**body, "request_id": str(uuid4()), "cartridge_allocations": {second["id"]: 10000}}
    assert admin.post("/api/accounts/repayments", json=selected).status_code == 201
    assert admin.post("/api/accounts/repayments", json=selected).status_code == 201
    assert (
        admin.post(
            "/api/accounts/repayments",
            json={**selected, "cartridge_allocations": {first["id"]: 10000}},
        ).status_code
        == 409
    )
    report = alice.get("/api/accounts").json()
    assert len(report["cartridge_balances"]) == 2
    assert all(float(row["owed"]) > 0 for row in report["cartridge_balances"])


def test_printer_can_be_registered_without_owner(accounts):
    admin, _, _ = accounts
    response = admin.post(
        "/api/printers", json={"name": "Shared printer", "driver": "mock", "unowned": True}
    )
    assert response.status_code == 201, response.text
    assert response.json()["owner_id"] is None
    assert "unowned" not in response.json()["config"]
    owned = admin.post("/api/printers", json={"name": "Owned printer", "driver": "mock"}).json()
    listed = {row["id"]: row for row in admin.get("/api/printers").json()}
    assert listed[owned["id"]]["owner_id"] == "administrator"
    assert listed[response.json()["id"]]["owner_id"] is None


def test_default_allocation_interleaves_cartridges_by_individual_charge_age(accounts):
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    first = install(admin, tape["id"])
    set_price(admin, first)
    set_permissions(admin, "alice", "view", "submit_directly")
    worker = admin.app.state.fleet.workers["main"]
    submit(alice, tape)
    worker.tick()
    second = install(admin, tape["id"])
    set_price(admin, second)
    submit(alice, tape)
    worker.tick()
    assert (
        admin.put("/api/printer/active-tape", json={"cartridge_id": first["id"]}).status_code == 200
    )
    submit(alice, tape)
    worker.tick()
    body = {
        "request_id": str(uuid4()),
        "user_id": "alice",
        "recipient_id": "administrator",
        "amount_minor": 30,
        "currency": "EUR",
        "note": "Oldest first",
    }
    preview = admin.post("/api/accounts/repayments/preview", json=body).json()
    assert preview["allocations"] == {first["id"]: 200000, second["id"]: 100000}


def test_excess_payment_remains_visible_as_unallocated_credit(accounts):
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    set_price(admin, cartridge)
    set_permissions(admin, "alice", "view", "submit_directly")
    submit(alice, tape)
    admin.app.state.fleet.workers["main"].tick()
    result = admin.post(
        "/api/accounts/repayments",
        json={
            "request_id": str(uuid4()),
            "user_id": "alice",
            "recipient_id": "administrator",
            "amount_minor": 100,
            "currency": "EUR",
            "note": "Paid extra",
        },
    )
    assert result.status_code == 201
    report = alice.get("/api/accounts").json()
    assert report["balances"][0]["unallocated_owed"] == "-0.800000"
    assert report["cartridge_balances"][0]["owed"] == "0.000000"
