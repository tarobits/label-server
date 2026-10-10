"""Unavailable group members preserve scoped queues and healthy-member routing."""

from conftest import profile
from test_access_security import accounts as account_fixture
from test_fleet import device, fit, group

from app.models import PrinterDevice, Role

accounts = account_fixture


def group_access(admin, user, destination, level="request"):
    with admin.app.state.factory.begin() as session:
        session.get(Role, f"{user}-access").permissions = [
            {"kind": "destination", "destination_id": destination, "level": level}
        ]


def unavailable(admin, identifier):
    # Simulate a persisted invalid registration without invoking real hardware.
    with admin.app.state.factory.begin() as session:
        session.get(PrinterDevice, identifier).driver = "invalid-test-driver"
    admin.app.state.fleet.workers.pop(identifier)
    admin.app.state.registry._definitions.pop(identifier)
    admin.app.state.registry._backends.pop(identifier)
    admin.app.state.fleet.sync()
    assert identifier in admin.app.state.fleet.configuration_errors


def request_job(client, destination, tape, copies=1):
    return client.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {
                "destination_id": destination,
                "tape_profile": tape["id"],
                "copies": copies,
                "data": {"text": "Group availability"},
            },
        },
    )


def prepare_csv(client, destination, tape):
    return client.post(
        "/api/runs/prepare",
        json={
            "destination_id": destination,
            "request_key": "available-group-csv",
            "name": "Healthy member run",
            "template": "text",
            "expected_revision": 2,
            "tape_profile": tape["id"],
            "csv_text": "Text\nHealthy member",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2}],
        },
    )


def test_group_uses_healthy_second_member_for_rendering_approval_and_printing(accounts):
    admin, alice, _ = accounts
    second = device(admin)
    destination = group(admin, ["main", second])
    group_access(admin, "alice", destination)
    tape = profile(admin, threshold=1)
    fit(admin, second, tape)
    worker = admin.app.state.fleet.workers[second]
    worker.latest_status = worker.backend.get_status()
    unavailable(admin, "main")

    targets = alice.get("/api/destinations").json()
    assert len(targets) == 1
    assert targets[0]["id"] == destination
    assert targets[0]["available"] is True
    assert targets[0]["capabilities"]
    assert alice.get("/api/printers").json() == []
    assert alice.get("/api/printers/status").json() == []
    assert "configuration_error" not in targets[0]
    assert "status" not in targets[0]
    preview = alice.post(
        "/api/preview",
        json={
            "template_id": "text",
            "destination_id": destination,
            "data": {"text": "Healthy member preview"},
        },
    )
    assert preview.status_code == 200, preview.text
    prepared = prepare_csv(alice, destination, tape)
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["valid"] is True
    requested = request_job(alice, destination, tape)
    assert requested.status_code == 201, requested.text
    approved = admin.post(f"/api/requests/{requested.json()['id']}/approve")
    assert approved.status_code == 200, approved.text
    worker.tick()
    job = alice.get(f"/api/jobs/{approved.json()['job_ids'][0]}").json()
    assert job["status"] == "printed"
    assert admin.get("/api/batches").json()[0]["printer_id"] == second


def test_all_unavailable_members_retain_group_queue_and_reject_new_print_intent(accounts):
    admin, alice, bob = accounts
    second = device(admin)
    destination = group(admin, ["main", second])
    group_access(admin, "alice", destination)
    tape = profile(admin, threshold=100)
    requested = request_job(alice, destination, tape, copies=2)
    assert requested.status_code == 201, requested.text
    approved = admin.post(f"/api/requests/{requested.json()['id']}/approve")
    assert approved.status_code == 200, approved.text
    pending = request_job(alice, destination, tape)
    assert pending.status_code == 201, pending.text
    unavailable(admin, "main")
    unavailable(admin, second)

    targets = alice.get("/api/destinations").json()
    assert len(targets) == 1
    target = targets[0]
    assert target["id"] == destination
    assert target["available"] is False
    assert target["capabilities"] is None
    assert sum(queue["queued_copies"] for queue in target["queues"]) == 2
    assert alice.get("/api/workspace").json()["total_queued"] == 2
    assert not any(item["id"] == destination for item in bob.get("/api/destinations").json())
    assert alice.get("/api/printers").json() == []
    assert alice.get("/api/printers/status").json() == []
    assert "configuration_error" not in target

    failed = [
        alice.post("/api/preview", json={"template_id": "text", "destination_id": destination}),
        admin.post(
            "/api/jobs",
            json={
                "destination_id": destination,
                "tape_profile": tape["id"],
                "data": {"text": "Unavailable"},
            },
        ),
        request_job(alice, destination, tape),
        prepare_csv(alice, destination, tape),
        admin.post(f"/api/requests/{pending.json()['id']}/approve"),
    ]
    for response in failed:
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "No configured printer is available at this destination"
    assert alice.get(f"/api/requests/{pending.json()['id']}").json()["status"] == "pending"
    assert alice.get(f"/api/jobs/{approved.json()['job_ids'][0]}").json()["status"] == "queued"
