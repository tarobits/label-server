import pytest
from conftest import install, profile
from sqlalchemy import select
from test_access_security import accounts as accounts
from test_auth import change
from test_printer_controls import controlled
from test_runs import run_body

from app.job_access import reconcile_access_holds
from app.models import AuditEvent, Location, PrinterDevice, PrinterGroup, ResourceGrant, Role


def set_permissions(admin, username, *permissions, destination="main"):
    with admin.app.state.fleet.lock, admin.app.state.factory.begin() as session:
        session.get(Role, f"{username}-access").permissions = [
            {
                "kind": "destination_permissions",
                "destination_id": destination,
                "permissions": [f"printer.{value}" for value in permissions],
            }
        ]
        session.flush()
        reconcile_access_holds(session)


def submit(client, tape, text="Label"):
    return client.post("/api/jobs", json={"tape_profile": tape["id"], "data": {"text": text}})


def test_role_assignment_previews_owner_loss_and_records_cartridge_access_change(accounts):
    admin, alice, _ = accounts
    cartridge = install(admin, profile(admin)["id"])
    with admin.app.state.factory.begin() as session:
        session.add(Role(id="cartridge-approvers", name="Cartridge approvers", permissions=[]))
        session.add(
            ResourceGrant(
                principal_kind="role",
                principal_id="cartridge-approvers",
                scope_kind="cartridge",
                scope_id=cartridge["id"],
                permission="cartridge.approve_use",
            )
        )
    body = {"role_ids": ["member", "alice-access", "cartridge-approvers"], "disabled": False}
    preview = admin.post(
        "/api/admin/access-preview",
        json={"resource": "users", "identifier": "alice", "method": "PUT", "payload": body},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["owner_loss_warning"]
    alice_impact = next(item for item in preview.json()["affected_users"] if item["id"] == "alice")
    assert (
        "cartridge.approve_use" in alice_impact["after"]["cartridge_permissions"][cartridge["id"]]
    )
    assert (
        "cartridge.approve_use"
        not in alice_impact["before"]["cartridge_permissions"][cartridge["id"]]
    )
    changed = admin.put(
        "/api/admin/users/alice",
        json=body,
        headers={"X-Access-Confirmation": preview.json()["confirmation_token"]},
    )
    assert changed.status_code == 200, changed.text
    events = admin.get(
        "/api/audit",
        params={"cartridge": cartridge["id"], "action": "permission.changed", "victim": "alice"},
    ).json()["items"]
    assert any("cartridge.approve_use" in event["fields"]["new_permissions"] for event in events)


def test_view_only_is_not_submission_or_request_permission(accounts):
    admin, alice, _ = accounts
    tape = profile(admin)
    set_permissions(admin, "alice", "view")
    assert alice.get("/api/status").status_code == 200
    assert submit(alice, tape).status_code == 403
    result = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {
                "tape_profile": tape["id"],
                "data": {"text": "Forbidden"},
            },
        },
    )
    assert result.status_code == 403
    assert admin.get("/api/requests").json() == []


def test_submitting_and_starting_are_independent(accounts):
    admin, alice, _ = accounts
    tape = profile(admin)
    install(admin, tape["id"])
    set_permissions(admin, "alice", "view", "submit_directly")
    response = submit(alice, tape)
    assert response.status_code == 201, response.text
    assert alice.post("/api/queue/print").status_code == 403
    set_permissions(admin, "alice", "view", "submit_directly", "start_own")
    response = alice.post("/api/queue/print")
    assert response.status_code == 202, response.text
    assert alice.put("/api/printer/automatic-printing", json={"held": True}).status_code == 403


def test_queue_reader_cannot_edit_cancel_approve_or_start(accounts):
    admin, alice, bob = accounts
    tape = profile(admin)
    set_permissions(admin, "alice", "view", "submit_directly", "submit_requests")
    item = submit(alice, tape).json()
    pending = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {
                "tape_profile": tape["id"],
                "data": {"text": "Needs approval"},
            },
        },
    ).json()
    set_permissions(admin, "bob", "view", "view_queue")
    assert bob.get(f"/api/jobs/{item['id']}").status_code == 200
    assert (
        bob.put(
            f"/api/jobs/{item['id']}/copies", json={"copies": 2, "expected_copies": 1}
        ).status_code
        == 403
    )
    assert bob.delete(f"/api/jobs/{item['id']}").status_code == 403
    assert bob.post("/api/queue/print").status_code == 403
    assert (
        bob.post(
            f"/api/requests/{pending['id']}/approve", json={"expected_revision": 1}
        ).status_code
        == 403
    )


def test_request_authorizer_cannot_change_quantities(accounts):
    admin, alice, bob = accounts
    tape = profile(admin)
    pending = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {
                "tape_profile": tape["id"],
                "data": {"text": "Frozen"},
            },
        },
    ).json()
    set_permissions(admin, "bob", "view", "approve_requests")
    assert bob.get(f"/api/requests/{pending['id']}").status_code == 200
    assert (
        bob.put(
            f"/api/requests/{pending['id']}/labels/0/copies",
            json={"copies": 2, "expected_revision": 1},
        ).status_code
        == 403
    )
    result = bob.post(f"/api/requests/{pending['id']}/approve", json={"expected_revision": 1})
    assert result.status_code == 200, result.text
    assert result.json()["labels"][0]["copies"] == 1


def test_swap_permission_does_not_grant_configuration_or_stops(accounts):
    admin, alice, _ = accounts
    tape = profile(admin)
    cartridge = install(admin, tape["id"])
    set_permissions(admin, "alice", "view", "swap_cartridges")
    assert alice.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code == 200
    assert (
        alice.put("/api/printer/active-tape", json={"cartridge_id": cartridge["id"]}).status_code
        == 200
    )
    assert (
        alice.put("/api/printers/main/cartridge-check", json={"enabled": False}).status_code == 403
    )
    assert alice.post("/api/printers/main/stop", json={"mode": "emergency"}).status_code == 403
    assert alice.put("/api/printer/automatic-printing", json={"held": True}).status_code == 403


@pytest.mark.parametrize(
    "mode,permission,other",
    [
        ("after_current", "stop_after_label", "emergency"),
        ("emergency", "emergency_stop", "after_current"),
    ],
)
def test_stop_permissions_are_independent(accounts, mode, permission, other):
    admin, alice, _ = accounts
    controlled(admin)
    tape = profile(admin)
    install(admin, tape["id"])
    assert submit(admin, tape).status_code == 201
    assert admin.post("/api/queue/print").status_code == 202
    set_permissions(admin, "alice", "view", permission)
    assert alice.get("/api/status").json()["pending_flush"] is not None
    assert alice.post("/api/printers/main/stop", json={"mode": other}).status_code == 403
    result = alice.post("/api/printers/main/stop", json={"mode": mode})
    assert result.status_code == 202, result.text
    assert alice.get("/api/status").json()["pending_flush"] is None
    assert alice.put("/api/printer/automatic-printing", json={"held": False}).status_code == 403


def test_start_any_does_not_silently_hold_unselected_work(accounts):
    admin, alice, bob = accounts
    tape = profile(admin)
    install(admin, tape["id"])
    worker = admin.app.state.fleet.workers["main"]
    worker.latest_status = worker.backend.get_status()
    set_permissions(admin, "alice", "view", "submit_directly")
    first = submit(alice, tape, "First").json()
    second = submit(alice, tape, "Second").json()
    set_permissions(admin, "bob", "view", "view_queue", "start_any")
    response = bob.post(
        "/api/destinations/main/print", json={"copy_ids": [first["labels"][0]["id"]]}
    )
    assert response.status_code == 202, response.text
    assert not admin.get("/api/status").json()["automatic_printing_held"]
    assert second["labels"][0]["id"] not in response.json()["requests"][0]["copy_ids"]


def test_activity_access_does_not_authorize_batch_review(accounts):
    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    set_permissions(admin, "alice", "view", "submit_directly")
    assert submit(alice, tape).status_code == 201
    worker = admin.app.state.fleet.workers["main"]
    worker.backend.fail_after = 0
    worker.tick()
    batch = admin.get("/api/batches").json()[0]
    set_permissions(admin, "alice", "view", "view_activity")
    assert alice.get(f"/api/batches/{batch['id']}").status_code == 200
    assert (
        alice.post(
            f"/api/batches/{batch['id']}/review", json={"consumed_mm": 0, "decisions": {}}
        ).status_code
        == 403
    )
    set_permissions(admin, "alice", "view", "review")
    detail = alice.get(f"/api/batches/{batch['id']}")
    assert detail.status_code == 200
    result = alice.post(
        f"/api/batches/{batch['id']}/review",
        json={
            "consumed_mm": 0,
            "decisions": {item["copy_id"]: "cancelled" for item in detail.json()["items"]},
        },
    )
    assert result.status_code == 200, result.text


def test_location_and_direct_grants_take_effect_and_revoke_without_login(accounts):
    admin, alice, _ = accounts
    set_permissions(admin, "alice", "view")
    with admin.app.state.factory.begin() as session:
        session.add(Location(id="room", name="Room"))
        session.flush()
        session.get(PrinterDevice, "main").location_id = "room"
        session.add(
            ResourceGrant(
                principal_kind="user",
                principal_id="alice",
                scope_kind="location",
                scope_id="room",
                permission="printer.hold_resume",
            )
        )
    assert alice.put("/api/printer/automatic-printing", json={"held": True}).status_code == 200
    with admin.app.state.factory.begin() as session:
        session.delete(session.scalar(select(ResourceGrant)))
    assert alice.put("/api/printer/automatic-printing", json={"held": False}).status_code == 403


def test_role_editor_previews_granular_effects_and_rejects_stale_location_state(accounts):
    admin, alice, _ = accounts
    payload = {
        "name": "alice access",
        "permissions": [
            {
                "kind": "destination_permissions",
                "destination_id": "main",
                "permissions": ["printer.view", "printer.swap_cartridges"],
            }
        ],
    }
    preview = admin.post(
        "/api/admin/access-preview",
        json={
            "resource": "roles",
            "identifier": "alice-access",
            "method": "PUT",
            "payload": payload,
        },
    )
    assert preview.status_code == 200, preview.text
    effect = next(item for item in preview.json()["affected_users"] if item["id"] == "alice")
    assert effect["after"]["destination_permissions"]["main"] == [
        "printer.swap_cartridges",
        "printer.view",
    ]
    assert effect["changed"]
    with admin.app.state.factory.begin() as session:
        session.add(Location(id="new", name="New"))
    result = admin.put(
        "/api/admin/roles/alice-access",
        json=payload,
        headers={"X-Access-Confirmation": preview.json()["confirmation_token"]},
    )
    assert result.status_code == 409
    change(admin, "roles", "PUT", payload, "alice-access")
    response = alice.get("/api/auth/session").json()["user"]
    assert response["destination_permissions"]["main"] == [
        "printer.swap_cartridges",
        "printer.view",
    ]
    assert response["destination_levels"] == {}
    assert response["printer_ids"] == ["main"]


def test_group_only_permissions_do_not_confer_physical_controls(accounts):
    admin, alice, _ = accounts
    with admin.app.state.factory.begin() as session:
        session.add(PrinterGroup(id="group", name="Group", printer_ids=["main"]))
    set_permissions(admin, "alice", "view", "hold_resume", destination="group")
    assert (
        alice.put("/api/destinations/group/automatic-printing", json={"held": True}).status_code
        == 200
    )
    assert alice.put("/api/printer/automatic-printing", json={"held": True}).status_code == 403
    response = admin.post(
        "/api/admin/access-preview",
        json={
            "resource": "roles",
            "method": "POST",
            "payload": {
                "name": "Invalid",
                "permissions": [
                    {
                        "kind": "destination_permissions",
                        "destination_id": "group",
                        "permissions": ["printer.emergency_stop"],
                    }
                ],
            },
        },
    )
    assert response.status_code == 422


def test_confirmed_access_changes_are_audited_and_scoped_but_previews_are_not(accounts):
    admin, alice, bob = accounts
    payload = {
        "name": "alice access",
        "permissions": [
            {
                "kind": "destination_permissions",
                "destination_id": "main",
                "permissions": ["printer.view", "printer.view_audit"],
            }
        ],
    }
    preview = admin.post(
        "/api/admin/access-preview",
        json={
            "resource": "roles",
            "identifier": "alice-access",
            "method": "PUT",
            "payload": payload,
        },
    )
    assert preview.status_code == 200
    with admin.app.state.factory() as session:
        assert session.scalars(select(AuditEvent)).all() == []
    response = admin.put(
        "/api/admin/roles/alice-access",
        json=payload,
        headers={
            "X-Access-Confirmation": preview.json()["confirmation_token"],
        },
    )
    assert response.status_code == 200, response.text
    result = alice.get(
        "/api/audit", params={"printer": "main", "action": "permission.changed", "victim": "alice"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1
    entry = result.json()["items"][0]
    assert entry["fields"]["new_permissions"] == ["printer.view", "printer.view_audit"]
    assert entry["fields"]["actor_id"] == "administrator"
    assert alice.get("/api/audit", params={"action": "access.changed"}).json()["total"] == 0
    assert bob.get("/api/audit").status_code == 403
    assert admin.get("/api/audit", params={"action": "access.changed"}).json()["total"] == 1
    assert (
        admin.get("/api/audit", params={"action": "audit.viewed", "actor": "alice"}).json()["total"]
        == 2
    )
    set_permissions(admin, "alice", "view")
    assert alice.get("/api/audit").status_code == 403


def test_global_audit_role_does_not_confer_printer_controls(accounts):
    admin, alice, _ = accounts
    change(
        admin,
        "roles",
        "PUT",
        {
            "name": "alice access",
            "permissions": [
                {"kind": "application", "permission": "audit.view_all"},
            ],
        },
        "alice-access",
    )
    response = alice.get("/api/audit", params={"action": "access.changed"})
    assert response.status_code == 200 and response.json()["total"] == 1
    assert alice.put("/api/printer/automatic-printing", json={"held": True}).status_code == 403


def test_queue_and_history_read_permissions_do_not_leak_into_each_other(accounts):
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    set_permissions(admin, "alice", "view", "submit_directly")
    item = submit(alice, tape).json()
    set_permissions(admin, "bob", "view", "view_activity")
    assert bob.get(f"/api/jobs/{item['id']}").status_code == 403
    assert bob.get("/api/jobs").json() == []
    admin.app.state.fleet.workers["main"].tick()
    assert bob.get(f"/api/jobs/{item['id']}").status_code == 200
    assert bob.get(f"/api/jobs/{item['id']}/preview").status_code == 200
    set_permissions(admin, "bob", "view", "view_queue")
    assert bob.get(f"/api/jobs/{item['id']}").status_code == 403
    assert bob.get("/api/jobs").json() == []


def test_csv_run_history_uses_activity_permission_and_keeps_drafts_private(accounts):
    admin, alice, bob = accounts
    body = run_body(admin)
    install(admin, body["tape_profile"])
    set_permissions(admin, "alice", "view", "submit_directly")
    response = alice.post("/api/runs/prepare", json=body)
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    detail = f"/api/runs/{run['id']}"
    preview = f"{detail}/rows/0/preview"
    set_permissions(admin, "bob", "view", "view_queue", "view_activity")
    assert bob.get(detail).status_code == 403
    assert bob.get("/api/runs").json() == []
    assert alice.post(f"{detail}/submit").status_code == 200
    set_permissions(admin, "bob", "view", "view_activity")
    assert bob.get(detail).status_code == 403
    assert bob.get(preview).status_code == 403
    assert bob.get("/api/runs").json() == []
    set_permissions(admin, "bob", "view", "view_queue")
    assert bob.get(detail).status_code == 200
    assert bob.get("/api/runs").json()[0]["id"] == run["id"]
    admin.app.state.fleet.workers["main"].tick()
    assert bob.get(detail).status_code == 403
    assert bob.get(preview).status_code == 403
    assert bob.get("/api/runs").json() == []
    set_permissions(admin, "bob", "view", "view_activity")
    assert bob.get(detail).status_code == 200
    assert bob.get(preview).status_code == 200
    assert bob.get("/api/runs").json()[0]["id"] == run["id"]
