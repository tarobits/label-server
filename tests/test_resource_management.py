from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as accounts

from app.models import AuditEvent, Location, PrinterDevice, ResourceGrant, ResourceOwnership


def apply(client, payload):
    preview = client.post("/api/resource-access/preview", json=payload)
    assert preview.status_code == 200, preview.text
    result = client.post(
        "/api/resource-access/apply",
        json=payload,
        headers={"X-Access-Confirmation": preview.json()["confirmation_token"]},
    )
    assert result.status_code == 200, result.text
    return preview.json()


def test_owner_transfer_direct_grants_and_scoped_preview(accounts):
    admin, alice, bob = accounts
    apply(admin, {"kind": "printer", "identifier": "main", "owner_id": "alice"})
    grants = [
        {"principal_kind": "user", "principal_id": "bob", "permission": "printer.hold_resume"}
    ]
    preview = apply(alice, {"kind": "printer", "identifier": "main", "grants": grants})
    assert preview["affected_users"][0]["id"] == "bob"
    assert set(preview["affected_users"][0]["after"]) == {"printer:main"}
    assert bob.put("/api/printer/automatic-printing", json={"held": True}).status_code == 200
    assert (
        alice.post(
            "/api/resource-access/preview",
            json={
                "kind": "printer",
                "identifier": "main",
                "grants": [
                    {
                        "principal_kind": "role",
                        "principal_id": "member",
                        "permission": "printer.configure",
                    }
                ],
            },
        ).status_code
        == 403
    )
    apply(alice, {"kind": "printer", "identifier": "main", "owner_id": "bob"})
    assert (
        alice.post(
            "/api/resource-access/preview",
            json={"kind": "printer", "identifier": "main", "owner_id": "alice"},
        ).status_code
        == 403
    )
    with admin.app.state.factory() as session:
        assert session.get(PrinterDevice, "main").owner_id == "bob"
        assert len(session.scalars(select(ResourceOwnership)).all()) == 2
        assert session.scalars(
            select(AuditEvent).where(AuditEvent.action == "resource.access_changed")
        ).all()


def test_location_inheritance_preview_cycles_and_stale_receipts(accounts):
    admin, _, bob = accounts
    apply(
        admin,
        {
            "kind": "location",
            "identifier": "building",
            "name": "Building",
            "grants": [
                {
                    "principal_kind": "user",
                    "principal_id": "bob",
                    "permission": "printer.hold_resume",
                }
            ],
        },
    )
    apply(
        admin, {"kind": "location", "identifier": "room", "name": "Room", "parent_id": "building"}
    )
    assert (
        admin.post(
            "/api/resource-access/preview",
            json={"kind": "location", "identifier": "building", "parent_id": "room"},
        ).status_code
        == 422
    )
    body = {"kind": "printer", "identifier": "main", "location_id": "room"}
    preview = admin.post("/api/resource-access/preview", json=body)
    assert preview.status_code == 200, preview.text
    with admin.app.state.factory.begin() as session:
        assert session.get(PrinterDevice, "main").location_id is None
        session.get(Location, "room").name = "Renamed"
    assert (
        admin.post(
            "/api/resource-access/apply",
            json=body,
            headers={"X-Access-Confirmation": preview.json()["confirmation_token"]},
        ).status_code
        == 409
    )
    apply(admin, body)
    assert bob.put("/api/printer/automatic-printing", json={"held": True}).status_code == 200


def test_approve_use_requires_loss_acknowledgment(accounts):
    admin, _, _ = accounts
    cartridge = install(admin, profile(admin)["id"])
    body = {
        "kind": "cartridge",
        "identifier": cartridge["id"],
        "grants": [
            {
                "principal_kind": "role",
                "principal_id": "member",
                "permission": "cartridge.approve_use",
            }
        ],
    }
    preview = admin.post("/api/resource-access/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["owner_loss_warning"]
    headers = {"X-Access-Confirmation": preview.json()["confirmation_token"]}
    assert admin.post("/api/resource-access/apply", json=body, headers=headers).status_code == 422
    assert (
        admin.post(
            "/api/resource-access/apply", json={**body, "accept_owner_loss": True}, headers=headers
        ).status_code
        == 200
    )
    with admin.app.state.factory() as session:
        assert session.scalar(select(ResourceGrant).where(ResourceGrant.scope_kind == "cartridge"))
