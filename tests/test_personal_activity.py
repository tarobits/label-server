"""Personal activity never turns a shared physical batch into shared label access."""

from sqlalchemy import select
from test_access_security import accounts as accounts
from test_print_audit import direct, grant, prepare_printer

from app.models import Batch, BatchItem, ResourceGrant, Role, State


def shared_batch(accounts):
    admin, alice, bob = accounts
    grant(admin, "alice", "print")
    grant(admin, "bob", "print")
    tape, worker = prepare_printer(admin, threshold=3)
    first = direct(alice, tape, "Alice private label", copies=1)
    second = direct(bob, tape, "Bob private label", copies=2)
    worker.tick()
    batch = admin.get("/api/batches").json()[0]
    with admin.app.state.factory.begin() as session:
        session.get_one(Role, "alice-access").permissions = []
        session.add(
            ResourceGrant(
                principal_kind="user",
                principal_id="alice",
                scope_kind="cartridge",
                scope_id=batch["cartridge_id"],
                permission="cartridge.view",
                effect="deny",
            )
        )
        saved = session.get_one(Batch, batch["id"])
        saved.error = "PRIVATE ERROR FROM BOB"
        saved.trigger = {"kind": "manual", "actor": {"id": "bob", "name": "Bob private starter"}}
        for item in session.scalars(
            select(BatchItem).where(
                BatchItem.copy_id.in_([copy["id"] for copy in second["labels"]])
            )
        ):
            item.outcome = State.FAILED
        saved.state = State.FAILED
    return batch, first, second


def test_personal_list_detail_preview_filters_and_mutations(accounts):
    admin, alice, bob = accounts
    batch, own, other = shared_batch(accounts)
    identifier = batch["id"]
    for path in ("/api/batches", "/api/batches/page"):
        response = alice.get(path)
        assert response.status_code == 200, response.text
        rows = response.json() if path == "/api/batches" else response.json()["items"]
        assert len(rows) == 1
        row = rows[0]
        assert row["redacted"] and row["state"] == "printed"
        assert row["cartridge_id"] == "" and row["printer_id"] == ""
        assert row["print_plan"] is None and row["trigger"] is None
        assert row["error"] is None and row["estimated_mm"] is None
        assert sum(entry["copies"] for entry in row["attribution_summary"]) == 1
        assert row["payers"] == [{"kind": "user", "id": "alice", "name": "alice"}]
        assert "bob" not in response.text.lower()
    response = alice.get(f"/api/batches/{identifier}")
    assert response.status_code == 200, response.text
    row = response.json()
    assert [item["job_id"] for item in row["items"]] == [own["id"]]
    assert row["items"][0]["text"] == "Alice private label"
    assert row["items"][0]["position"] == 0
    assert row["items"][0]["printer_name"] == "Restricted printer"
    assert row["reviews"] == []
    assert "bob" not in response.text.lower()
    own_url = f"/api/batches/{identifier}/items/{own['labels'][0]['id']}/preview"
    assert alice.get(own_url).status_code == 200
    other_url = f"/api/batches/{identifier}/items/{other['labels'][0]['id']}/preview"
    assert alice.get(other_url).status_code == 404
    assert admin.get(other_url).status_code == 200
    choices = alice.get("/api/batches/filters").json()
    assert choices["printers"] == [] and choices["cartridges"] == []
    assert choices["requesters"] == [{"id": "alice", "name": "alice"}]
    for params in (
        {"requester_id": "bob"},
        {"authorizer_id": "bob"},
        {"printer_id": "main"},
        {"cartridge_id": batch["cartridge_id"]},
    ):
        assert alice.get("/api/batches/page", params=params).json()["total"] == 0
    assert alice.get("/api/batches/page", params={"requester_id": "alice"}).json()["total"] == 1
    assert alice.get(f"/api/batches/{identifier}/reviews/unknown/photo").status_code == 403
    assert (
        alice.post(
            f"/api/batches/{identifier}/review",
            json={"decisions": {own["labels"][0]["id"]: "printed"}, "consumed_mm": 0},
        ).status_code
        == 403
    )
    # An unrelated user does not gain access just by knowing batch and copy IDs.
    with admin.app.state.factory.begin() as session:
        from app.models import PrintJob

        session.get_one(PrintJob, own["id"]).owner_id = "former-user"
    assert alice.get("/api/batches/page").json()["total"] == 0
    assert alice.get(f"/api/batches/{identifier}").status_code == 403
    assert alice.get(own_url).status_code == 403


def test_activity_grant_restores_full_batch_but_revocation_redacts_it(accounts):
    admin, alice, _ = accounts
    batch, _, _ = shared_batch(accounts)
    grant(admin, "alice", "full")
    row = alice.get(f"/api/batches/{batch['id']}").json()
    assert not row["redacted"]
    assert len(row["items"]) == 3
    assert row["error"] == "PRIVATE ERROR FROM BOB"
    grant(admin, "alice", "none")
    row = alice.get(f"/api/batches/{batch['id']}").json()
    assert row["redacted"] and len(row["items"]) == 1


def test_personal_batch_hides_restricted_printers_inside_change_snapshots(accounts):
    import copy

    admin, alice, _ = accounts
    batch, own, _ = shared_batch(accounts)
    change = {
        "id": "move",
        "source_id": "private-source",
        "target_id": "main",
        "source": {"id": "private-source", "name": "Private source name"},
        "target": {"id": "main", "name": "Private target name"},
        "previous_assignment": {"id": "private-previous", "name": "Private previous name"},
    }
    with admin.app.state.factory.begin() as session:
        item = session.get_one(BatchItem, (batch["id"], own["labels"][0]["id"]))
        item.attribution = {**copy.deepcopy(item.attribution), "destination_changes": [change]}
    for path in ("/api/batches", "/api/batches/page", f"/api/batches/{batch['id']}"):
        response = alice.get(path)
        assert response.status_code == 200, response.text
        for private in (
            "private-source",
            "private-previous",
            "Private source name",
            "Private target name",
            "Private previous name",
        ):
            assert private not in response.text
    full = admin.get(f"/api/batches/{batch['id']}").json()
    assert full["items"][0]["attribution"]["destination_changes"] == [change]
