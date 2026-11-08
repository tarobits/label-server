from conftest import install, profile
from sqlalchemy import delete
from test_access_security import accounts as accounts
from test_granular_printer_permissions import set_permissions, submit
from test_resource_management import apply

from app.models import Cartridge, ResourceGrant


def grant(admin, identifier, user, *permissions):
    with admin.app.state.factory.begin() as session:
        session.execute(
            delete(ResourceGrant).where(
                ResourceGrant.scope_kind == "cartridge", ResourceGrant.scope_id == identifier
            )
        )
        for permission in permissions:
            session.add(
                ResourceGrant(
                    principal_kind="user",
                    principal_id=user,
                    scope_kind="cartridge",
                    scope_id=identifier,
                    permission=f"cartridge.{permission}",
                )
            )


def test_private_cartridge_is_hidden_and_notes_permission_cannot_change_price(accounts):
    admin, alice, bob = accounts
    cartridge = install(admin, profile(admin)["id"])
    grant(admin, cartridge["id"], "alice", "view", "edit_notes")
    assert bob.get("/api/cartridges").json() == []
    path = f"/api/cartridges/{cartridge['id']}"
    assert bob.put(path + "/notes", json={"notes": "forbidden"}).status_code == 403
    assert alice.put(path + "/notes", json={"notes": "Keep dry"}).status_code == 200
    assert alice.put(path + "/price", json={"price_minor": 2}).status_code == 403
    assert alice.put(path, json={"name": "Rename"}).status_code == 403
    assert alice.delete(path).status_code == 403
    assert alice.get("/api/cartridges").json()[0]["notes"] == "Keep dry"


def test_use_is_enforced_for_manual_and_automatic_dispatch_and_live_revocation(accounts):
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    set_permissions(admin, "alice", "view", "submit_directly", "start_own")
    grant(admin, cartridge["id"], "alice", "view")
    queued = submit(alice, tape).json()
    assert alice.post("/api/queue/print").status_code == 409
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    assert not worker.backend.batches
    grant(admin, cartridge["id"], "alice", "view", "use")
    assert alice.post("/api/queue/print").status_code == 202
    grant(admin, cartridge["id"], "alice", "view")
    worker.tick()
    assert not worker.backend.batches
    grant(admin, cartridge["id"], "alice", "view", "use")
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert alice.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"


def test_installation_location_requires_confirmed_impact_and_allows_declining(accounts):
    admin, alice, _ = accounts
    cartridge = install(admin, profile(admin)["id"])
    apply(admin, {"kind": "location", "identifier": "room", "name": "Packing room"})
    apply(admin, {"kind": "printer", "identifier": "main", "location_id": "room"})
    set_permissions(admin, "alice", "view", "swap_cartridges")
    body = {"cartridge_id": cartridge["id"]}
    preview = alice.put("/api/printer/active-tape", json=body)
    assert preview.status_code == 409, preview.text
    assert preview.json()["detail"]["code"] == "cartridge_location"
    assert (
        alice.put("/api/printer/active-tape", json={**body, "move_location": False}).status_code
        == 200
    )
    with admin.app.state.factory() as session:
        assert session.get(Cartridge, cartridge["id"]).location_id is None
    confirmation = preview.json()["detail"]["confirmation"]
    response = alice.put(
        "/api/printer/active-tape",
        json={**body, "move_location": True, "location_confirmation": confirmation},
    )
    assert response.status_code == 200, response.text
    with admin.app.state.factory() as session:
        assert session.get(Cartridge, cartridge["id"]).location_id == "room"
    assert (
        alice.put(f"/api/cartridges/{cartridge['id']}/price", json={"price_minor": 1}).status_code
        == 403
    )
