from decimal import Decimal

from conftest import install, job, profile
from sqlalchemy import delete, select
from test_access_security import accounts as accounts

from app.models import (
    Cartridge,
    ReleaseMigration,
    ResourceOwnership,
    TapeAllocation,
    UsageAdjustment,
)


def legacy_inventory(admin):
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    assert (
        admin.put(
            f"/api/cartridges/{cartridge['id']}/price",
            json={"price_minor": 2000, "currency": "EUR"},
        ).status_code
        == 200
    )
    job(admin, tape["id"])
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    with admin.app.state.factory.begin() as session:
        row = session.scalar(select(TapeAllocation))
        original = (row.planned_mm, row.consumed_mm, row.price_minor, row.cost_micros)
        row.recipient_id = row.recipient_name = row.charged_micros = row.cartridge_id = None
        session.get(Cartridge, cartridge["id"]).owner_id = None
        session.execute(delete(ResourceOwnership))
        session.get(ReleaseMigration, "0.13.0").completed_at = None
        session.add(
            UsageAdjustment(
                id="old-payment",
                user_id="administrator",
                username="administrator",
                actor_id="bob",
                actor_name="bob",
                amount_minor=5,
                currency="EUR",
                note="Cash payment",
            )
        )
    return tape, cartridge, worker, original


def draft(cartridge):
    return {
        "resources": [
            {"kind": "printer", "identifier": "main", "owner_id": "bob"},
            {
                "kind": "cartridge",
                "identifier": cartridge["id"],
                "owner_id": "alice",
                "grants": [
                    {
                        "principal_kind": "role",
                        "principal_id": "member",
                        "permission": "cartridge.use",
                    }
                ],
            },
        ],
        "adjustment_recipients": {"old-payment": "alice"},
    }


def test_migration_gates_dispatch_and_preserves_costs_holds_and_recipient_choices(accounts):
    admin, alice, _ = accounts
    tape, cartridge, worker, original = legacy_inventory(admin)
    queued = job(admin, tape["id"])
    assert admin.get("/api/auth/session").json()["migration_required"]
    assert admin.post("/api/queue/print").status_code == 409
    assert admin.post("/api/destinations/main/print").status_code == 409
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert admin.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"
    body = draft(cartridge)
    assert alice.put("/api/migration/draft", json=body).status_code == 403
    assert alice.get("/api/migration").json() == {"required": True}
    assert admin.put("/api/migration/draft", json=body).status_code == 200
    assert admin.get("/api/migration").json()["draft"] == body
    preview = admin.post("/api/migration/preview", json={})
    assert preview.status_code == 200, preview.text
    balance = preview.json()["balances"][0]
    assert balance["recipient_id"] == "alice"  # Never infer the recording operator, Bob.
    assert Decimal(balance["owed"]) == Decimal(original[3]) / 1_000_000 - Decimal("0.05")
    assert preview.json()["adjustments"][0]["cartridge_allocations"] == {cartridge["id"]: "50000"}
    with admin.app.state.factory() as session:
        assert session.get(Cartridge, cartridge["id"]).owner_id is None
        assert session.scalar(select(TapeAllocation)).recipient_id is None
    assert admin.put("/api/printer/automatic-printing", json={"held": True}).status_code == 200
    headers = {"X-Access-Confirmation": preview.json()["confirmation_token"]}
    result = admin.post("/api/migration/complete", json={}, headers=headers)
    assert result.status_code == 200, result.text
    assert admin.post("/api/migration/complete", json={}, headers=headers).status_code == 200
    with admin.app.state.factory() as session:
        row = session.scalar(select(TapeAllocation))
        assert (row.planned_mm, row.consumed_mm, row.price_minor, row.cost_micros) == original
        assert row.recipient_id == "alice" and row.charged_micros == row.cost_micros
        assert session.get(UsageAdjustment, "old-payment").recipient_id == "alice"
        assert session.get(UsageAdjustment, "old-payment").cartridge_allocations == {
            cartridge["id"]: "50000"
        }
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert admin.get("/api/status").json()["automatic_printing_held"]
    assert not admin.get("/api/auth/session").json()["migration_required"]


def test_migration_requires_all_assignments_and_rejects_stale_preview(accounts):
    admin, _, _ = accounts
    _, cartridge, _, _ = legacy_inventory(admin)
    incomplete = draft(cartridge)
    incomplete["adjustment_recipients"] = {}
    admin.put("/api/migration/draft", json=incomplete)
    assert admin.post("/api/migration/preview", json={}).status_code == 422
    body = draft(cartridge)
    admin.put("/api/migration/draft", json=body)
    preview = admin.post("/api/migration/preview", json={})
    assert preview.status_code == 200, preview.text
    body["adjustment_recipients"]["old-payment"] = "bob"
    admin.put("/api/migration/draft", json=body)
    result = admin.post(
        "/api/migration/complete",
        json={},
        headers={"X-Access-Confirmation": preview.json()["confirmation_token"]},
    )
    assert result.status_code == 409
    assert admin.get("/api/migration").json()["required"]
