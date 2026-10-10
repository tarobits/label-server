"""Exercise scoped permissions through real HTTP operations and frozen jobs."""

from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture

from app.models import LabelCopy, PrinterDevice, PrinterState, Role, State, UserGroup

accounts = account_fixture


def grant(client, user, destination, level):
    with client.app.state.factory.begin() as session:
        session.get(Role, f"{user}-access").permissions = [
            {"kind": "destination", "destination_id": destination, "level": level}
        ]


def group(admin):
    result = admin.post(
        "/api/printer-groups", json={"name": "Distribution", "printer_ids": ["main"]}
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def test_group_only_printing_uses_group_default_and_cannot_operate_individual_printer(accounts):
    admin, alice, bob = accounts
    destination = group(admin)
    grant(admin, "alice", destination, "print")
    grant(admin, "bob", destination, "print")
    tape = profile(admin, threshold=100)
    install(admin, tape["id"])
    admin.app.state.fleet.workers["main"].latest_status = admin.app.state.fleet.workers[
        "main"
    ].backend.get_status()
    assert alice.get("/api/printers").json() == []
    assert alice.get("/api/printers/status").json() == []
    destinations = alice.get("/api/destinations").json()
    assert len(destinations) == 1
    assert destinations[0]["id"] == destination
    assert destinations[0]["capabilities"]
    own = alice.post("/api/jobs", json={"tape_profile": tape["id"], "data": {"text": "Own"}})
    assert own.status_code == 201, own.text
    assert own.json()["destination_id"] == destination
    other = bob.post(
        "/api/jobs",
        json={"destination_id": destination, "tape_profile": tape["id"], "data": {"text": "Other"}},
    ).json()
    assert alice.post("/api/destinations/main/print").status_code == 403
    assert (
        alice.put(
            f"/api/destinations/{destination}/automatic-printing", json={"held": True}
        ).status_code
        == 403
    )
    assert (
        alice.post(
            f"/api/destinations/{destination}/print", json={"copy_ids": [other["labels"][0]["id"]]}
        ).status_code
        == 409
    )
    result = alice.post(
        f"/api/destinations/{destination}/print", json={"copy_ids": [own.json()["labels"][0]["id"]]}
    )
    assert result.status_code == 202, result.text
    assert not alice.get("/api/destinations").json()[0]["automatic_printing_held"]
    with admin.app.state.factory() as session:
        assert not session.get(PrinterState, 1).automatic_printing_held
    admin.app.state.fleet.workers["main"].tick()
    assert alice.get(f"/api/jobs/{own.json()['id']}").json()["status"] == "printed"
    assert bob.get(f"/api/jobs/{other['id']}").json()["status"] == "queued"


def test_group_full_can_edit_existing_group_but_additions_require_direct_full(accounts):
    admin, alice, _ = accounts
    destination = group(admin)
    grant(admin, "alice", destination, "full")
    renamed = alice.put(
        f"/api/printer-groups/{destination}", json={"name": "Renamed", "printer_ids": ["main"]}
    )
    assert renamed.status_code == 200, renamed.text
    assert alice.put("/api/printers/main", json={"name": "Forbidden"}).status_code == 403
    with admin.app.state.factory.begin() as session:
        session.add(PrinterDevice(id="second", name="Second", driver="mock", config={}))
        session.add(PrinterState(printer_id="second"))
    admin.app.state.fleet.sync()
    body = {"name": "Renamed", "printer_ids": ["main", "second"]}
    assert alice.put(f"/api/printer-groups/{destination}", json=body).status_code == 403
    with admin.app.state.factory.begin() as session:
        role = session.get(Role, "alice-access")
        role.permissions = [
            *role.permissions,
            {"kind": "destination", "destination_id": "second", "level": "full"},
        ]
    assert alice.put(f"/api/printer-groups/{destination}", json=body).status_code == 200


def test_template_collaboration_permissions_are_independent_and_owners_can_edit_without_printers(
    accounts,
):
    admin, alice, bob = accounts
    with admin.app.state.factory.begin() as session:
        session.add(
            UserGroup(
                id="shared",
                name="Shared",
                members=[
                    {
                        "user_id": "alice",
                        "can_create": True,
                        "can_edit_others": False,
                        "can_delete_others": False,
                    },
                    {
                        "user_id": "bob",
                        "can_create": False,
                        "can_edit_others": True,
                        "can_delete_others": False,
                    },
                ],
            )
        )
    body = {
        "name": "Shared label",
        "scope": "group",
        "group_id": "shared",
        "document": {"elements": []},
    }
    assert bob.post("/api/templates", json=body).status_code == 403
    created = alice.post("/api/templates", json=body)
    assert created.status_code == 201, created.text
    identifier = created.json()["id"]
    updated = bob.put(f"/api/templates/{identifier}", json={**body, "expected_revision": 1})
    assert updated.status_code == 200, updated.text
    assert bob.delete(f"/api/templates/{identifier}").status_code == 403
    with admin.app.state.factory.begin() as session:
        session.get(UserGroup, "shared").members = []
        session.get(Role, "alice-access").permissions = []
    assert alice.get("/api/destinations").json() == []
    assert alice.get(f"/api/templates/{identifier}").json()["can_edit"]
    preview = alice.post("/api/preview", json={"template_id": identifier})
    assert preview.status_code == 200, preview.text
    own_update = alice.put(f"/api/templates/{identifier}", json={**body, "expected_revision": 2})
    assert own_update.status_code == 200, own_update.text
    assert alice.delete(f"/api/templates/{identifier}").status_code == 200


def test_own_queued_copies_can_be_cancelled_while_other_copies_require_review(accounts):
    admin, alice, _ = accounts
    grant(admin, "alice", "main", "print")
    tape = profile(admin)
    queued = alice.post(
        "/api/jobs",
        json={
            "destination_id": "main",
            "tape_profile": tape["id"],
            "copies": 2,
            "data": {"text": "Partial"},
        },
    ).json()
    with admin.app.state.factory.begin() as session:
        copies = list(
            session.scalars(
                select(LabelCopy)
                .where(LabelCopy.job_id == queued["id"])
                .order_by(LabelCopy.ordinal)
            )
        )
        copies[0].state = State.NEEDS_REVIEW
        session.get(Role, "alice-access").permissions = []
    response = alice.post("/api/queue/remove", json={"copy_ids": [queued["labels"][1]["id"]]})
    assert response.status_code == 200, response.text
    result = alice.get(f"/api/jobs/{queued['id']}").json()
    assert [copy["state"] for copy in result["labels"]] == ["needs_review", "cancelled"]
