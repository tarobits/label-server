from decimal import Decimal

from conftest import install, profile
from sqlalchemy import delete, select
from test_access_security import accounts as accounts
from test_cost_estimates import preview, set_price
from test_granular_printer_permissions import set_permissions
from test_price_consent import submission

from app.models import BatchItem, ResourceGrant, TapeAllocation


def prepared(accounts, copies=2):
    admin, alice, _ = accounts
    tape = profile(admin, threshold=100)
    cartridge = install(admin, tape["id"])
    set_price(admin, cartridge, 1000)
    set_permissions(admin, "alice", "view", "submit_directly")
    quote = preview(alice, tape, copies)["cost_estimate"]
    response = alice.post("/api/jobs", json=submission(tape, quote, copies))
    assert response.status_code == 201, response.text
    with admin.app.state.factory.begin() as session:
        session.execute(delete(ResourceGrant).where(ResourceGrant.scope_id == cartridge["id"]))
    set_price(admin, cartridge, 5000)
    return cartridge, quote, response.json()


def test_override_is_selected_copy_only_caps_shared_quote_and_records_authorizer(accounts):
    admin, _, _ = accounts
    _, quote, job = prepared(accounts)
    response = admin.post("/api/queue/print")
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "cartridge_use" and len(detail["items"]) == 2
    identifier = detail["items"][0]["copy_id"]
    response = admin.post(
        "/api/queue/print",
        json={
            "copy_ids": [identifier],
            "approve_copy_ids": [identifier],
            "use_confirmations": detail["confirmations"],
        },
    )
    assert response.status_code == 202, response.text
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    assert len(worker.backend.batches) == 1 and len(worker.backend.batches[0]) == 1
    with admin.app.state.factory() as session:
        allocation = session.scalar(select(TapeAllocation))
        assert int(allocation.charged_micros) == int(
            Decimal(quote["quotes"][0]["maximum"]) * 1000000
        )
        assert int(allocation.cost_micros) > int(allocation.charged_micros)
        item = session.scalar(select(BatchItem))
        assert item.attribution["cartridge_authorization"]["actor_id"] == "administrator"
    labels = admin.get(f"/api/jobs/{job['id']}").json()["labels"]
    assert sum(label["state"] == "queued" for label in labels) == 1


def test_override_requires_approve_use_and_rechecks_stale_price(accounts):
    admin, alice, bob = accounts
    cartridge, _, _ = prepared(accounts, 1)
    set_permissions(admin, "bob", "view", "start_any", "view_queue")
    with admin.app.state.factory.begin() as session:
        session.add(
            ResourceGrant(
                principal_kind="user",
                principal_id="bob",
                scope_kind="cartridge",
                scope_id=cartridge["id"],
                permission="cartridge.view",
            )
        )
    assert bob.post("/api/queue/print").status_code == 409
    detail = admin.post("/api/queue/print").json()["detail"]
    identifier = detail["items"][0]["copy_id"]
    body = {
        "copy_ids": [identifier],
        "approve_copy_ids": [identifier],
        "use_confirmations": detail["confirmations"],
    }
    set_price(admin, cartridge, 6000)
    assert admin.post("/api/queue/print", json=body).status_code == 409
    assert bob.post("/api/queue/print", json=body).status_code == 409
