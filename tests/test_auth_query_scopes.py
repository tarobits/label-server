"""Unknown query parameters must never substitute the target being authorized."""

import pytest
from conftest import install, profile
from test_access_security import accounts as account_fixture

from app.models import PrinterState, Role

accounts = account_fixture


def full_group(admin):
    result = admin.post("/api/printer-groups", json={"name": "Full group", "printer_ids": ["main"]})
    assert result.status_code == 201, result.text
    identifier = result.json()["id"]
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": identifier, "level": "full"}
        ]
    return identifier


@pytest.mark.parametrize("query_name", ["destination_id", "printer_id"])
def test_scoped_full_cannot_substitute_for_inventory_permission(accounts, query_name):
    admin, alice, _ = accounts
    destination = full_group(admin)
    tape = profile(admin)
    cartridge = install(admin, tape["id"])
    query = {query_name: destination}
    cases = [
        ("POST", "/api/tape-profiles", {"name": "Forbidden", "width_mm": 24}),
        ("PUT", f"/api/tape-profiles/{tape['id']}", {"name": "Forbidden", "width_mm": 24}),
        ("DELETE", f"/api/tape-profiles/{tape['id']}", None),
        ("PUT", f"/api/tape-profiles/{tape['id']}/reminder", {"action": "silence"}),
        (
            "POST",
            "/api/cartridges",
            {"profile_id": tape["id"], "name": "Forbidden", "nominal_length_mm": 8000},
        ),
        ("PUT", f"/api/cartridges/{cartridge['id']}/remaining", {"remaining_mm": 1}),
    ]
    for method, path, body in cases:
        response = alice.request(method, path, params=query, json=body)
        assert response.status_code == 403, (path, response.text)
    assert admin.get("/api/tape-profiles").json()[0]["name"] == tape["name"]
    assert admin.get("/api/cartridges").json()[0]["remaining_mm"] == 8000


@pytest.mark.parametrize("query_name", ["destination_id", "printer_id"])
def test_scoped_full_cannot_substitute_for_registration_permission(accounts, query_name):
    admin, alice, _ = accounts
    # Even Full directly on a member does not confer the global registration permission.
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "full"}
        ]
    query = {query_name: "main"}
    assert (
        alice.post("/api/printers", params=query, json={"name": "Unauthorized"}).status_code == 403
    )
    assert (
        alice.post(
            "/api/printer-groups",
            params=query,
            json={"name": "Unauthorized", "printer_ids": ["main"]},
        ).status_code
        == 403
    )
    assert len(admin.get("/api/printers").json()) == 1
    assert not any(item["kind"] == "group" for item in admin.get("/api/destinations").json())


@pytest.mark.parametrize("explicit_printer", [True, False])
def test_group_grant_cannot_replace_physical_target_with_extra_destination(
    accounts, explicit_printer
):
    admin, alice, _ = accounts
    destination = full_group(admin)
    tape = profile(admin)
    cartridge = install(admin, tape["id"])
    query = {"destination_id": destination}
    if explicit_printer:
        query["printer_id"] = "main"
    assert (
        alice.put("/api/printer/active-tape", params=query, json={"cartridge_id": None}).status_code
        == 403
    )
    assert (
        alice.put("/api/printer/automatic-printing", params=query, json={"held": True}).status_code
        == 403
    )
    with admin.app.state.factory() as session:
        state = session.get(PrinterState, 1)
        assert state.active_cartridge_id == cartridge["id"]
        assert not state.automatic_printing_held
    # The allowed group operation still works and does not change the physical hold.
    assert (
        alice.put(
            f"/api/destinations/{destination}/automatic-printing", json={"held": True}
        ).status_code
        == 200
    )
