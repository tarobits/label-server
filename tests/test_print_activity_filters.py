from conftest import install, profile
from test_access_security import accounts as accounts
from test_granular_printer_permissions import set_permissions, submit


def test_activity_filters_counts_and_choices_use_authorized_frozen_attempts(accounts):
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    cartridge = install(admin, tape["id"])
    set_permissions(admin, "alice", "view", "submit_directly")
    set_permissions(admin, "bob", "view", "submit_requests")
    submit(alice, tape)
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    pending = bob.post("/api/requests", json={"kind": "job", "input": {"tape_profile": tape["id"], "data": {"text": "Approved"}}}).json()
    response = admin.post(f"/api/requests/{pending['id']}/approve", json={"expected_revision": pending["revision"]})
    assert response.status_code == 200, response.text
    worker.tick()
    all_rows = admin.get("/api/batches/page").json()
    assert all_rows["total"] == 2
    filtered = admin.get(f"/api/batches/page?printer_id=main&cartridge_id={cartridge['id']}&requester_id=bob&authorizer_id=administrator&limit=1").json()
    assert filtered["total"] == 1 and len(filtered["items"]) == 1
    assert admin.get("/api/batches/page?requester_id=alice&authorizer_id=administrator").json()["total"] == 0
    assert admin.get("/api/batches/page?authorizer_id=alice").json()["total"] == 0
    choices = admin.get("/api/batches/filters").json()
    assert {row["id"] for row in choices["requesters"]} == {"alice", "bob"}
    assert {row["id"] for row in choices["authorizers"]} == {"administrator"}
    assert alice.get("/api/batches/filters").json()["requesters"] == [{"id": "alice", "name": "alice"}]
    assert alice.get("/api/batches/page?requester_id=bob").json()["total"] == 0
    set_permissions(admin, "alice", "view_activity")
    assert alice.get("/api/batches/page?requester_id=bob").json()["total"] == 1
    assert alice.get("/api/batches/page?printer_id=main").json()["total"] == 2
    assert [row["id"] for row in alice.get("/api/batches/filters").json()["printers"]] == ["main"]
