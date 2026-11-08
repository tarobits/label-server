import pytest
from test_access_security import accounts as accounts
from test_resource_access import seed
from test_resource_management import apply

from app.models import ResourceGrant, Role, User
from app.resource_access import resolve_resource_access


def grant(
    session, scope, scope_id, effect, *, principal="staff", user=False, permission="printer.view"
):
    session.add(
        ResourceGrant(
            principal_kind="user" if user else "role",
            principal_id=principal,
            scope_kind=scope,
            scope_id=scope_id,
            permission=permission,
            effect=effect,
        )
    )
    session.flush()


@pytest.mark.parametrize(
    "scope,scope_id,user_scope,user_scope_id,expected",
    [
        ("printer", "p", "location", "room", False),
        ("printer", "p", "printer", "p", True),
        ("location", "room", "location", "home", False),
        ("location", "home", "location", "room", True),
    ],
)
def test_resource_specificity_precedes_principal_specificity(
    foundation_session, scope, scope_id, user_scope, user_scope_id, expected
):
    session = foundation_session
    seed(session)
    grant(session, scope, scope_id, "deny")
    grant(session, user_scope, user_scope_id, "allow", principal="staff-user", user=True)
    rights = resolve_resource_access(session, session.get(User, "staff-user"))
    assert rights.can("printer", "p", "printer.view") is expected
    assert rights.decisions[("printer", "p")]["printer.view"].allowed is expected


def test_role_conflicts_deny_but_direct_user_allow_and_ownership_win(foundation_session):
    session = foundation_session
    seed(session)
    session.add(Role(id="other-role", name="Other role", permissions=[]))
    session.get(User, "staff-user").role_ids = ["staff", "other-role"]
    grant(session, "printer", "p", "allow")
    grant(session, "printer", "p", "deny", principal="other-role")
    assert not resolve_resource_access(session, session.get(User, "staff-user")).can(
        "printer", "p", "printer.view"
    )
    grant(session, "printer", "p", "allow", principal="staff-user", user=True)
    assert resolve_resource_access(session, session.get(User, "staff-user")).can(
        "printer", "p", "printer.view"
    )
    grant(session, "printer", "p", "deny", principal="owner", user=True)
    assert resolve_resource_access(session, session.get(User, "owner")).can(
        "printer", "p", "printer.view"
    )
    grant(session, "printer", "p", "deny", principal="admin", user=True)
    assert resolve_resource_access(session, session.get(User, "admin")).can(
        "printer", "p", "printer.view"
    )


def test_submission_modes_respect_inherited_priority_and_legacy_roles(foundation_session):
    session = foundation_session
    seed(session)
    session.get(Role, "staff").permissions = [
        {"kind": "destination", "destination_id": "p", "level": "print"}
    ]
    rights = resolve_resource_access(session, session.get(User, "staff-user"))
    assert rights.can("printer", "p", "printer.submit_directly")
    assert not rights.can("printer", "p", "printer.submit_requests")
    grant(
        session,
        "printer",
        "p",
        "allow",
        principal="staff-user",
        user=True,
        permission="printer.submit_requests",
    )
    rights = resolve_resource_access(session, session.get(User, "staff-user"))
    assert rights.can("printer", "p", "printer.submit_requests")
    assert not rights.can("printer", "p", "printer.submit_directly")


def test_location_owner_manages_grants_without_owning_contents(accounts):
    admin, alice, bob = accounts
    apply(admin, {"kind": "location", "identifier": "room", "name": "Room", "owner_id": "alice"})
    apply(admin, {"kind": "printer", "identifier": "main", "location_id": "room"})
    with admin.app.state.factory() as session:
        rights = resolve_resource_access(session, session.get(User, "alice"))
        assert rights.can("location", "room", "location.manage")
        assert not rights.can("printer", "main", "printer.configure")
    assert "room" in alice.get("/api/auth/session").json()["user"]["managed_location_ids"]
    assert (
        alice.post(
            "/api/resource-access/preview",
            json={"kind": "location", "identifier": "new", "name": "New"},
        ).status_code
        == 403
    )
    apply(
        alice,
        {
            "kind": "location",
            "identifier": "room",
            "grants": [
                {
                    "principal_kind": "user",
                    "principal_id": "bob",
                    "permission": "printer.configure",
                    "effect": "allow",
                },
            ],
        },
    )
    assert (
        bob.put(
            "/api/printers/main", json={"name": "Managed by grant", "driver": "mock"}
        ).status_code
        == 200
    )
    apply(alice, {"kind": "location", "identifier": "room", "owner_id": "bob"})
    assert (
        alice.post(
            "/api/resource-access/preview",
            json={"kind": "location", "identifier": "room", "name": "Forbidden"},
        ).status_code
        == 403
    )


def test_role_location_rules_share_storage_with_resource_editor(accounts):
    admin, _, _ = accounts
    apply(admin, {"kind": "location", "identifier": "room", "name": "Room"})
    payload = {
        "name": "Location staff",
        "permissions": [
            {
                "kind": "location_permissions",
                "location_id": "room",
                "permissions": ["printer.view", "cartridge.view"],
                "denied_permissions": ["cartridge.use"],
            }
        ],
    }
    preview = admin.post(
        "/api/admin/access-preview",
        json={"resource": "roles", "method": "POST", "payload": payload},
    )
    assert preview.status_code == 200, preview.text
    created = admin.post(
        "/api/admin/roles",
        json=payload,
        headers={"X-Access-Confirmation": preview.json()["confirmation_token"]},
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]
    catalog = admin.get("/api/resource-access").json()
    room = next(r for r in catalog["resources"] if r["id"] == "room")
    assert {(g["permission"], g["effect"]) for g in room["grants"]} == {
        ("printer.view", "allow"),
        ("cartridge.view", "allow"),
        ("cartridge.use", "deny"),
    }
    apply(
        admin,
        {
            "kind": "location",
            "identifier": "room",
            "grants": [
                {
                    "principal_kind": "role",
                    "principal_id": role_id,
                    "permission": "cartridge.use",
                    "effect": "allow",
                }
            ],
        },
    )
    role = next(r for r in admin.get("/api/admin/roles").json() if r["id"] == role_id)
    assert role["permissions"] == [
        {
            "kind": "location_permissions",
            "location_id": "room",
            "permissions": ["cartridge.use"],
            "denied_permissions": [],
        }
    ]


def test_explanation_is_scoped_and_denial_audit_keeps_effect(accounts):
    admin, alice, bob = accounts
    apply(
        admin,
        {
            "kind": "location",
            "identifier": "room",
            "name": "Shared room",
            "grants": [
                {
                    "principal_kind": "role",
                    "principal_id": "member",
                    "permission": "printer.hold_resume",
                }
            ],
        },
    )
    apply(
        admin, {"kind": "printer", "identifier": "main", "location_id": "room", "owner_id": "alice"}
    )
    rule = {
        "principal_kind": "user",
        "principal_id": "bob",
        "permission": "printer.hold_resume",
        "effect": "deny",
    }
    apply(alice, {"kind": "printer", "identifier": "main", "grants": [rule]})
    query = {"kind": "printer", "identifier": "main", "user_id": "bob"}
    explanation = alice.get("/api/resource-access/explain", params=query)
    assert explanation.status_code == 200, explanation.text
    decision = next(
        p
        for p in explanation.json()["resources"][0]["permissions"]
        if p["permission"] == "printer.hold_resume"
    )
    assert not decision["allowed"]
    assert any(r["scope_name"] == "Shared room" and not r["winning"] for r in decision["rules"])
    assert (
        bob.put("/api/printer/automatic-printing?printer_id=main", json={"held": True}).status_code
        == 403
    )
    assert (
        bob.get("/api/resource-access/explain", params={**query, "user_id": "alice"}).status_code
        == 403
    )
    event = next(
        e
        for e in admin.get(
            "/api/audit", params={"printer": "main", "action": "permission.changed"}
        ).json()["items"]
        if e["fields"].get("new_denied_permissions")
    )
    assert event["fields"]["new_denied_permissions"] == ["printer.hold_resume"]


def test_invalid_modes_and_invalid_effect_are_rejected(accounts):
    admin, _, _ = accounts
    grants = [
        {"principal_kind": "user", "principal_id": "alice", "permission": f"printer.{mode}"}
        for mode in ("submit_requests", "submit_directly")
    ]
    response = admin.post(
        "/api/resource-access/preview",
        json={"kind": "printer", "identifier": "main", "grants": grants},
    )
    assert response.status_code == 422
    assert (
        admin.post(
            "/api/resource-access/preview",
            json={
                "kind": "printer",
                "identifier": "main",
                "grants": [{**grants[0], "effect": "invalid"}],
            },
        ).status_code
        == 422
    )


def test_pre1_schema_upgrades_existing_inventory_and_grants(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.db import make_engine

    url = f"sqlite:///{tmp_path / 'pre1.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "121313f47a90")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO locations (id, name, parent_id) VALUES ('legacy', 'Legacy', NULL)")
        )
        connection.execute(
            text(
                "INSERT INTO resource_grants (principal_kind, principal_id, scope_kind, scope_id, permission) VALUES ('user', 'legacy-user', 'location', 'legacy', 'cartridge.use')"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT owner_id FROM locations WHERE id='legacy'")).scalar()
            is None
        )
        assert (
            connection.execute(text("SELECT effect FROM resource_grants")).scalar_one() == "allow"
        )
    engine.dispose()


def test_location_graph_includes_descendants_and_hides_unrelated_resources(accounts):
    admin, alice, _ = accounts
    apply(
        admin,
        {"kind": "location", "identifier": "building", "name": "Building", "owner_id": "alice"},
    )
    apply(
        admin,
        {
            "kind": "location",
            "identifier": "room",
            "name": "Room",
            "parent_id": "building",
            "grants": [
                {"principal_kind": "role", "principal_id": "member", "permission": "printer.view"}
            ],
        },
    )
    apply(admin, {"kind": "printer", "identifier": "main", "location_id": "room"})
    response = alice.get(
        "/api/resource-access/explain", params={"location_id": "building", "user_id": "bob"}
    )
    assert response.status_code == 200, response.text
    assert any(item["id"] == "main" for item in response.json()["resources"])
    unrelated = admin.post(
        "/api/printers", json={"name": "Private elsewhere", "driver": "mock"}
    ).json()
    response = alice.get("/api/resource-access/explain", params={"user_id": "bob"})
    assert unrelated["id"] not in response.text
    response = admin.get("/api/resource-access/explain", params={"user_id": "bob"})
    assert {"main", "building", "room", unrelated["id"]} <= {
        item["id"] for item in response.json()["resources"]
    }
    response = admin.get(
        "/api/resource-access/explain", params={"location_id": "building", "user_id": "bob"}
    )
    assert {item["id"] for item in response.json()["resources"]} == {"main", "building", "room"}


def test_deleting_location_owner_releases_ownership_but_preserves_grants(accounts):
    from sqlalchemy import select
    from test_auth import change

    from app.models import Location, ResourceGrant

    admin, _, _ = accounts
    apply(
        admin,
        {
            "kind": "location",
            "identifier": "room",
            "name": "Room",
            "owner_id": "alice",
            "grants": [
                {"principal_kind": "user", "principal_id": "bob", "permission": "cartridge.use"},
            ],
        },
    )
    result = change(admin, "users", "DELETE", identifier="alice")
    assert result.status_code == 204, result.text
    with admin.app.state.factory() as session:
        assert session.get(Location, "room").owner_id is None
        assert (
            session.scalar(
                select(ResourceGrant).where(ResourceGrant.scope_id == "room")
            ).principal_id
            == "bob"
        )
    events = admin.get("/api/audit", params={"action": "location.ownership_changed"}).json()[
        "items"
    ]
    assert events[0]["fields"]["old_owner_id"] == "alice"


def test_request_survives_promotion_to_direct_submission(accounts):
    from conftest import install, profile
    from test_job_access_holds import set_level

    admin, alice, _ = accounts
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    pending = alice.post(
        "/api/requests",
        json={
            "kind": "job",
            "input": {"tape_profile": tape["id"], "data": {"text": "Already requested"}},
        },
    )
    assert pending.status_code == 201, pending.text
    set_level(admin, "alice", "print")
    accepted = admin.post(
        f"/api/requests/{pending.json()['id']}/approve", json={"expected_revision": 1}
    )
    assert accepted.status_code == 200, accepted.text
    admin.app.state.fleet.workers["main"].tick()
    assert alice.get(f"/api/jobs/{accepted.json()['job_ids'][0]}").json()["status"] == "printed"
    assert (
        alice.post(
            "/api/requests",
            json={
                "kind": "job",
                "input": {"tape_profile": tape["id"], "data": {"text": "New request"}},
            },
        ).status_code
        == 403
    )


@pytest.mark.parametrize("source", ["resource", "role"])
def test_downgrade_refuses_to_discard_denials(tmp_path, source):
    from alembic import command
    from alembic.config import Config

    from app.db import make_engine, session_factory

    url = f"sqlite:///{tmp_path / 'denials.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = make_engine(url)
    with session_factory(engine).begin() as session:
        if source == "resource":
            session.add(
                ResourceGrant(
                    principal_kind="user",
                    principal_id="example",
                    scope_kind="printer",
                    scope_id="example",
                    permission="printer.view",
                    effect="deny",
                )
            )
        else:
            session.add(
                Role(
                    name="Example deny",
                    permissions=[
                        {
                            "kind": "destination_permissions",
                            "destination_id": "example",
                            "permissions": [],
                            "denied_permissions": ["printer.view"],
                        }
                    ],
                )
            )
    with pytest.raises(RuntimeError, match="Remove explicit permission denials"):
        command.downgrade(config, "121313f47a90")
    engine.dispose()
