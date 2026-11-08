import json

from conftest import install, profile
from test_access_security import accounts as accounts

from app.models import ResourceGrant


def test_inventory_actions_record_success_denial_and_failure_without_payload_leaks(accounts):
    admin, alice, _ = accounts
    cartridge = install(admin, profile(admin)["id"])
    path = f"/api/cartridges/{cartridge['id']}"
    assert (
        admin.put(path + "/price", json={"price_minor": 2000, "currency": "EUR"}).status_code == 200
    )
    assert admin.put(path + "/notes", json={"notes": "Private maintenance note"}).status_code == 200
    assert admin.put(path + "/remaining", json={"remaining_mm": 5000}).status_code == 200
    assert alice.put(path + "/price", json={"price_minor": 1}).status_code == 403
    assert admin.put(path + "/price", json={"price_minor": -1}).status_code == 422
    entries = admin.get("/api/audit", params={"cartridge": cartridge["id"]}).json()["items"]
    price = [entry for entry in entries if entry["action"] == "cartridge.price_changed"]
    assert {entry["outcome"] for entry in price} == {"succeeded", "denied", "failed"}
    success = next(entry for entry in price if entry["outcome"] == "succeeded")
    assert (
        success["fields"]["new_price_minor"] == 2000
        and success["fields"]["old_price_minor"] is None
    )
    denied = next(entry for entry in price if entry["outcome"] == "denied")
    assert denied["fields"]["actor_id"] == "alice" and denied["fields"]["status_code"] == 403
    assert "Private maintenance note" not in json.dumps(entries)
    assert any(
        entry["action"] == "cartridge.remaining_corrected"
        and entry["fields"]["new_remaining_mm"] == 5000
        for entry in entries
    )


def test_printer_auditor_sees_swap_but_no_private_cartridge_identity(accounts):
    admin, _, bob = accounts
    with admin.app.state.factory.begin() as session:
        session.add(
            ResourceGrant(
                principal_kind="user",
                principal_id="bob",
                scope_kind="printer",
                scope_id="main",
                permission="printer.view_audit",
            )
        )
    cartridge = admin.post(
        "/api/cartridges",
        json={
            "profile_id": profile(admin)["id"],
            "name": "Private cartridge",
            "nominal_length_mm": 8000,
        },
    ).json()
    assert (
        admin.put("/api/printer/active-tape", json={"cartridge_id": cartridge["id"]}).status_code
        == 200
    )
    response = bob.get("/api/audit", params={"printer": "main", "action": "cartridge.swapped"})
    assert response.status_code == 200, response.text
    entry = response.json()["items"][0]
    assert entry["restricted_details"]
    assert cartridge["id"] not in json.dumps(response.json())
    assert "Private cartridge" not in json.dumps(response.json())
