"""Shared inventory exposes operational flags without restricted printer identities."""

import pytest
from conftest import install, job, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture

from app.models import Batch, FlushRequest, PrinterDevice, Role, State

accounts = account_fixture


def inventory(client):
    response = client.get("/api/cartridges")
    assert response.status_code == 200, response.text
    return {cartridge["id"]: cartridge for cartridge in response.json()}


@pytest.mark.parametrize("active_state", [State.PRINTING, State.NEEDS_REVIEW])
def test_inventory_only_user_sees_actual_installation_and_locks_without_printer_identity(
    accounts, active_state
):
    admin, member, _ = accounts
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "application", "permission": "inventory.manage"}
        ]
        session.get(PrinterDevice, "main").name = "Restricted bench printer"
    tape = profile(admin)
    mounted = install(admin, tape["id"])
    response = admin.post(
        "/api/cartridges",
        json={
            "profile_id": tape["id"],
            "name": "Unused spare",
            "nominal_length_mm": 8000,
        },
    )
    assert response.status_code == 201, response.text
    spare = response.json()
    with admin.app.state.factory.begin() as session:
        session.add(
            Batch(
                id="restricted-active-batch",
                printer_id="main",
                cartridge_id=mounted["id"],
                state=active_state,
                estimated_mm=80,
            )
        )

    session_user = member.get("/api/auth/session").json()["user"]
    assert "inventory.manage" in session_user["permissions"]
    assert session_user["destination_levels"] == {}
    for endpoint in ("/api/printers", "/api/printers/status", "/api/destinations", "/api/batches"):
        assert member.get(endpoint).json() == []
    assert member.get("/api/status?printer_id=main").status_code == 403
    records = inventory(member)
    assert records[mounted["id"]]["installed"] is True
    assert records[mounted["id"]]["estimate_locked"] is True
    assert records[spare["id"]]["installed"] is False
    assert records[spare["id"]]["estimate_locked"] is False
    payload = member.get("/api/cartridges").text
    assert "Restricted bench printer" not in payload
    assert "restricted-active-batch" not in payload
    for record in records.values():
        assert not {"printer_id", "printer_name", "destination_id", "batch_id"} & record.keys()
    assert (
        member.put(
            f"/api/cartridges/{mounted['id']}/remaining", json={"remaining_mm": 7000}
        ).status_code
        == 409
    )
    # A busy inaccessible printer must not prevent managing an unused spare.
    assert (
        member.put(
            f"/api/cartridges/{spare['id']}/remaining", json={"remaining_mm": 7000}
        ).status_code
        == 200
    )

    with admin.app.state.factory.begin() as session:
        session.get(Batch, "restricted-active-batch").state = State.PRINTED
    records = inventory(member)
    assert records[mounted["id"]]["installed"] is True
    assert records[mounted["id"]]["estimate_locked"] is False
    assert (
        member.put(
            f"/api/cartridges/{mounted['id']}/remaining", json={"remaining_mm": 7000}
        ).status_code
        == 200
    )
    # Inventory permission does not grant physical installation/removal access.
    assert (
        member.put(
            "/api/printer/active-tape?printer_id=main", json={"cartridge_id": None}
        ).status_code
        == 403
    )
    response = admin.put("/api/printer/active-tape?printer_id=main", json={"cartridge_id": None})
    assert response.status_code == 200, response.text
    records = inventory(member)
    assert records[mounted["id"]]["installed"] is False
    assert records[mounted["id"]]["estimate_locked"] is False


def test_pending_flush_blocks_removal_but_does_not_lock_estimate_correction(client):
    tape = profile(client)
    mounted = install(client, tape["id"])
    queued = job(client, tape["id"])
    with client.app.state.factory.begin() as session:
        session.add(
            FlushRequest(
                printer_id="main",
                destination_id="main",
                cartridge_id=mounted["id"],
                copy_ids=[copy["id"] for copy in queued["labels"]],
            )
        )
    records = inventory(client)
    assert records[mounted["id"]]["installed"] is True
    assert records[mounted["id"]]["estimate_locked"] is False
    assert (
        client.put(
            f"/api/cartridges/{mounted['id']}/remaining", json={"remaining_mm": 7000}
        ).status_code
        == 200
    )
    with client.app.state.factory() as session:
        assert session.scalar(select(FlushRequest)).completed is False
    assert client.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code == 409
