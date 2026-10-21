"""Production authentication and agreed role/membership authorization acceptance."""

import stat
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.access import AccountPolicy, Action, Resource
from app.auth import COOKIE_NAME, actor_for_user, token_hash
from app.config import Settings
from app.identity import LOCAL_OWNER_ID
from app.main import create_app
from app.models import (
    AccessChangeConfirmation,
    AuthSession,
    LabelTemplate,
    PrinterDevice,
    PrinterGroup,
    RegistrationCode,
    Role,
    User,
    UserGroup,
)

PASSWORD = "a sufficiently long password"


@pytest.fixture
def auth_client(tmp_path: Path) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path / 'accounts.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    application = create_app(Settings(database_url=url), start_worker=False)
    with TestClient(application) as client:
        yield client


def setup_admin(client: TestClient, tmp_path: Path) -> dict:
    response = client.post(
        "/api/auth/setup",
        json={
            "username": "Admin",
            "password": PASSWORD,
            "setup_token": (tmp_path / "auth-setup-token").read_text().strip(),
        },
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


def invite(client: TestClient) -> str:
    response = client.post("/api/admin/registration-codes", json={"name": "Invitation"})
    assert response.status_code == 201, response.text
    return response.json()["code"]


def register_member(client: TestClient, code: str | None, username: str = "member") -> dict:
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "registration_code": code,
        },
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


def login(client: TestClient, username: str = "admin", password: str = PASSWORD) -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


def test_self_password_change_checks_session_csrf_origin_and_current_password(
    auth_client, tmp_path
):
    client = auth_client
    body = {"current_password": PASSWORD, "new_password": "a different secure password"}
    assert client.post("/api/auth/password", json=body).status_code == 401
    setup_admin(client, tmp_path)
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/auth/password", json=body).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert (
        client.post(
            "/api/auth/password", json=body, headers={"Origin": "https://other.example"}
        ).status_code
        == 403
    )
    wrong = client.post("/api/auth/password", json={**body, "current_password": "incorrect"})
    assert wrong.status_code == 400
    assert wrong.json()["detail"][0]["loc"] == ["body", "current_password"]
    assert (
        client.post("/api/auth/password", json={**body, "new_password": "too short"}).status_code
        == 422
    )
    assert client.get("/api/auth/session").json()["user"]["username"] == "admin"
    login(client)


def test_self_password_change_keeps_current_session_and_revokes_only_other_sessions(
    auth_client, tmp_path
):
    client = auth_client
    owner = setup_admin(client, tmp_path)["user"]["id"]
    code = invite(client)
    other, member = TestClient(client.app), TestClient(client.app)
    try:
        login(other)
        member_record = register_member(member, code)
        before = client.cookies.get(COOKIE_NAME)
        changed = client.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": "a different secure password"},
        )
        assert changed.status_code == 204
        assert client.cookies.get(COOKIE_NAME) == before
        assert client.get("/api/auth/session").json()["user"]["id"] == owner
        assert other.get("/api/auth/session").json()["user"] is None
        assert member.get("/api/auth/session").json()["user"]["id"] == member_record["user"]["id"]
        assert (
            other.post(
                "/api/auth/login", json={"username": "admin", "password": PASSWORD}
            ).status_code
            == 401
        )
        login(other, password="a different secure password")
        # Changing one's own password does not require an administrative role.
        assert (
            member.post(
                "/api/auth/password",
                json={
                    "current_password": PASSWORD,
                    "new_password": "a member replacement password",
                },
            ).status_code
            == 204
        )
        with client.app.state.factory() as session:
            user = session.get(User, owner)
            assert user.password_hash != "a different secure password"
    finally:
        other.close()
        member.close()


def preview(client, resource, method, payload=None, identifier=None):
    return client.post(
        "/api/admin/access-preview",
        json={
            "resource": resource,
            "method": method,
            "identifier": identifier,
            "payload": payload or {},
        },
    )


def change(client, resource, method, payload=None, identifier=None):
    reviewed = preview(client, resource, method, payload, identifier)
    assert reviewed.status_code == 200, reviewed.text
    endpoint = f"/api/admin/{resource}" + (f"/{identifier}" if identifier else "")
    if method == "RESTORE":
        endpoint += "/restore"
    response = client.request(
        "POST" if method == "RESTORE" else method,
        endpoint,
        json=payload or {},
        headers={
            "X-Access-Confirmation": reviewed.json()["confirmation_token"],
        },
    )
    assert response.status_code in (200, 201, 204), response.text
    return response


def destinations(client):
    with client.app.state.factory.begin() as session:
        session.add_all(
            [
                PrinterDevice(id="first", name="First", driver="brother-pt-p710bt", config={}),
                PrinterDevice(id="second", name="Second", driver="brother-pt-p710bt", config={}),
                PrinterGroup(id="station", name="Station", printer_ids=["first", "second"]),
            ]
        )


def permission(destination, level):
    return {"kind": "destination", "destination_id": destination, "level": level}


def test_first_run_requires_secret_and_claims_old_records(auth_client, tmp_path):
    client = auth_client
    token = tmp_path / "auth-setup-token"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert client.get("/api/auth/session").json()["setup_required"]
    assert client.get("/api/templates").status_code == 401
    assert (
        client.post(
            "/api/auth/setup",
            json={"username": "admin", "password": PASSWORD, "setup_token": "bad"},
        ).status_code
        == 403
    )
    result = setup_admin(client, tmp_path)
    assert result["user"]["id"] == LOCAL_OWNER_ID
    assert result["user"]["is_admin"]
    assert result["user"]["role_ids"] == ["administrator"]
    assert result["user"]["username"] == "admin"
    assert not token.exists()
    with client.app.state.factory() as session:
        assert session.get(LabelTemplate, "text").owner_id == LOCAL_OWNER_ID
        user = session.get(User, LOCAL_OWNER_ID)
        assert user.password_hash != PASSWORD
        assert not hasattr(User, "is_admin")
        record = session.scalar(select(AuthSession))
        assert record.token_hash == token_hash(client.cookies[COOKIE_NAME])
        assert record.token_hash != client.cookies[COOKIE_NAME]
    assert (
        client.post(
            "/api/auth/setup",
            json={"username": "second", "password": PASSWORD, "setup_token": "bad"},
        ).status_code
        == 409
    )


def test_session_csrf_origin_expiry_and_logout(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    csrf = client.headers.pop("X-CSRF-Token")
    assert (
        client.post("/api/tape-profiles", json={"name": "White", "width_mm": 24}).status_code == 403
    )
    client.headers["X-CSRF-Token"] = csrf
    assert (
        client.post(
            "/api/tape-profiles",
            headers={"Origin": "https://attacker.invalid"},
            json={"name": "White", "width_mm": 24},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/login",
            headers={"Origin": "https://attacker.invalid"},
            json={"username": "admin", "password": PASSWORD},
        ).status_code
        == 403
    )
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/templates").status_code == 401
    login(client)
    with client.app.state.factory.begin() as session:
        session.scalar(select(AuthSession)).expires_at = time.time() - 1
    assert client.get("/api/auth/session").json()["user"] is None
    assert client.get("/api/templates").status_code == 401


def test_registration_never_grants_administrator(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    assert (
        client.post(
            "/api/auth/register", json={"username": "member", "password": PASSWORD}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/admin/registration-codes",
            json={"name": "Forbidden", "role_ids": ["administrator"]},
        ).status_code
        == 422
    )
    code = invite(client)
    result = register_member(client, code)
    assert not result["user"]["is_admin"]
    assert result["user"]["permissions"] == ["assets.write", "templates.create_personal"]
    assert result["user"]["destination_levels"] == {}
    assert client.get("/api/admin/users").status_code == 403
    assert (
        client.post(
            "/api/auth/register",
            json={"username": "another", "password": PASSWORD, "registration_code": code},
        ).status_code
        == 400
    )


def test_registration_applies_independent_permissions_for_each_template_group(
    auth_client, tmp_path
):
    client = auth_client
    setup_admin(client, tmp_path)
    flags = [
        {"can_create": False, "can_edit_others": False, "can_delete_others": False},
        {"can_create": True, "can_edit_others": False, "can_delete_others": False},
        {"can_create": False, "can_edit_others": True, "can_delete_others": False},
        {"can_create": False, "can_edit_others": False, "can_delete_others": True},
        {"can_create": True, "can_edit_others": True, "can_delete_others": True},
    ]
    groups = [
        change(client, "groups", "POST", {"name": f"Team {index}", "members": []}).json()
        for index in range(len(flags))
    ]
    expected = {group["id"]: rights for group, rights in zip(groups, flags, strict=True)}
    created = client.post(
        "/api/admin/registration-codes",
        json={"name": "Team access", "group_ids": list(expected), "group_permissions": expected},
    )
    assert created.status_code == 201, created.text
    assert created.json()["group_permissions"] == expected
    assert client.get("/api/admin/registration-codes").json()[0]["group_permissions"] == expected
    result = register_member(client, created.json()["code"])
    assert result["user"]["group_memberships"] == expected
    with client.app.state.factory() as session:
        for group in groups:
            assert session.get(UserGroup, group["id"]).members == [
                {"user_id": result["user"]["id"], **expected[group["id"]]}
            ]


def test_legacy_registration_codes_keep_create_only_template_access(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    group = change(client, "groups", "POST", {"name": "Legacy team"}).json()
    response = client.post(
        "/api/admin/registration-codes", json={"name": "Legacy invite", "group_ids": [group["id"]]}
    )
    assert response.status_code == 201, response.text
    expected = {"can_create": True, "can_edit_others": False, "can_delete_others": False}
    assert response.json()["group_permissions"] == {group["id"]: expected}
    # Existing codes acquire an empty permissions map when the database is upgraded.
    with client.app.state.factory.begin() as session:
        session.get(RegistrationCode, response.json()["id"]).group_permissions = {}
    result = register_member(client, response.json()["code"])
    assert result["user"]["group_memberships"] == {group["id"]: expected}


@pytest.mark.parametrize("invalid", ["unselected", "unknown", "extra-permission", "duplicate"])
def test_registration_group_permissions_validate_references_and_rights(
    auth_client, tmp_path, invalid
):
    client = auth_client
    setup_admin(client, tmp_path)
    group = change(client, "groups", "POST", {"name": "Selected team"}).json()
    body = {
        "name": "Invalid invitation",
        "group_ids": [group["id"]],
        "group_permissions": {group["id"]: {"can_create": True}},
    }
    if invalid == "unselected":
        body["group_ids"] = []
    elif invalid == "unknown":
        body["group_ids"] = ["unknown"]
        body["group_permissions"] = {"unknown": {"can_create": True}}
    elif invalid == "extra-permission":
        body["group_permissions"] = {group["id"]: {"is_admin": True}}
    else:
        body["group_ids"] = [group["id"], group["id"]]
    assert client.post("/api/admin/registration-codes", json=body).status_code == 422
    assert client.get("/api/admin/registration-codes").json() == []


def test_deleting_group_removes_its_registration_code_permissions(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    removed = change(client, "groups", "POST", {"name": "Removed team"}).json()
    retained = change(client, "groups", "POST", {"name": "Remaining team"}).json()
    rights = {"can_create": False, "can_edit_others": True, "can_delete_others": False}
    response = client.post(
        "/api/admin/registration-codes",
        json={
            "name": "Shared invitation",
            "group_ids": [removed["id"], retained["id"]],
            "group_permissions": {removed["id"]: rights, retained["id"]: rights},
        },
    )
    assert response.status_code == 201, response.text
    change(client, "groups", "DELETE", identifier=removed["id"])
    code = client.get("/api/admin/registration-codes").json()[0]
    assert code["group_ids"] == [retained["id"]]
    assert code["group_permissions"] == {retained["id"]: rights}
    result = register_member(client, response.json()["code"])
    assert result["user"]["group_memberships"] == {retained["id"]: rights}


def test_open_registration_and_revoked_codes(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    value = client.post("/api/admin/registration-codes", json={"name": "Revoked"}).json()
    assert client.delete(f"/api/admin/registration-codes/{value['id']}").status_code == 204
    assert (
        client.post(
            "/api/auth/register",
            json={"username": "revoked", "password": PASSWORD, "registration_code": value["code"]},
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/admin/settings",
            json={
                "registration_code_required": False,
                "approval_notification_debounce_seconds": 30,
            },
        ).status_code
        == 200
    )
    assert not register_member(client, None)["user"]["is_admin"]


def test_administrator_role_is_universal_protected_and_required(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    assert (
        preview(
            client, "roles", "PUT", {"name": "Weakened", "permissions": []}, "administrator"
        ).status_code
        == 409
    )
    assert preview(client, "roles", "DELETE", identifier="administrator").status_code == 409
    assert (
        preview(
            client, "users", "PUT", {"disabled": False, "role_ids": []}, LOCAL_OWNER_ID
        ).status_code
        == 409
    )
    assert (
        preview(
            client,
            "users",
            "PUT",
            {"disabled": True, "role_ids": ["administrator"]},
            LOCAL_OWNER_ID,
        ).status_code
        == 409
    )
    destinations(client)
    result = client.get("/api/auth/session").json()["user"]
    assert result["destination_levels"] == {"first": "full", "second": "full", "station": "full"}
    with client.app.state.factory() as session:
        actor = actor_for_user(session, session.get(User, LOCAL_OWNER_ID))
        policy = AccountPolicy({})
        assert policy.can_destination(actor, "not-enumerated-yet", "full")
        assert policy.allows(
            actor,
            Action.READ,
            Resource("template", "foreign", "someone", scope="group", group_id="not-a-member"),
        )


def test_role_grants_combine_by_maximum_without_group_expansion(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    destinations(client)
    reader = change(
        client,
        "roles",
        "POST",
        {
            "name": "Requests",
            "permissions": [permission("first", "request"), permission("station", "full")],
        },
    ).json()
    printer = change(
        client,
        "roles",
        "POST",
        {
            "name": "Printing",
            "permissions": [permission("first", "print"), permission("second", "none")],
        },
    ).json()
    member = change(
        client,
        "users",
        "POST",
        {"username": "member", "password": PASSWORD, "role_ids": [reader["id"], printer["id"]]},
    ).json()
    with client.app.state.factory() as session:
        actor = actor_for_user(session, session.get(User, member["id"]))
        policy = AccountPolicy({"first": None, "second": None, "station": None})
        assert policy.can_destination(actor, "first", "print")
        assert not policy.can_destination(actor, "first", "moderator")
        assert policy.can_destination(actor, "station", "full")
        assert not policy.can_destination(actor, "second")
        with pytest.raises(TypeError):
            actor.destination_levels["second"] = "full"


@pytest.mark.parametrize(
    "level,requesting,printing,moderating,configuring",
    [
        ("none", False, False, False, False),
        ("request", True, False, False, False),
        ("print", True, True, False, False),
        ("moderator", True, True, True, False),
        ("full", True, True, True, True),
    ],
)
def test_all_five_scope_levels(level, requesting, printing, moderating, configuring):
    from app.access import Actor

    actor = Actor(id="member", destination_levels={"printer": level})
    policy = AccountPolicy({"printer": None})
    for minimum, permitted in (
        ("request", requesting),
        ("print", printing),
        ("moderator", moderating),
        ("full", configuring),
    ):
        assert policy.can_destination(actor, "printer", minimum) is permitted
    assert policy.allows(actor, Action.READ, Resource("job", "id", "member", "revoked"))
    assert policy.allows(actor, Action.DELETE, Resource("job", "id", "member", "revoked"))


def test_independent_group_membership_and_owner_rights(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    member = change(
        client, "users", "POST", {"username": "member", "password": PASSWORD, "role_ids": []}
    ).json()
    group = change(
        client,
        "groups",
        "POST",
        {
            "name": "Shared",
            "members": [
                {
                    "user_id": member["id"],
                    "can_create": False,
                    "can_edit_others": True,
                    "can_delete_others": False,
                }
            ],
        },
    ).json()
    with client.app.state.factory() as session:
        actor = actor_for_user(session, session.get(User, member["id"]))
        policy = AccountPolicy({})
        assert not actor.permissions and not actor.destination_levels
        assert not actor.group_memberships[group["id"]].can_create
        target = Resource("template", "id", "another", scope="group", group_id=group["id"])
        assert policy.allows(actor, Action.READ, target)
        assert policy.allows(actor, Action.WRITE, target)
        assert not policy.allows(actor, Action.DELETE, target)
        own = Resource("template", "own", member["id"], scope="group", group_id="left-group")
        assert all(
            policy.allows(actor, action, own)
            for action in (Action.READ, Action.WRITE, Action.DELETE)
        )


def test_preview_required_bound_to_payload_and_rejects_stale_expired_confirmation(
    auth_client, tmp_path
):
    client = auth_client
    setup_admin(client, tmp_path)
    body = {"name": "New role", "permissions": []}
    assert client.post("/api/admin/roles", json=body).status_code == 409
    first = preview(client, "roles", "POST", body).json()
    assert (
        client.post(
            "/api/admin/roles",
            json={**body, "name": "Changed"},
            headers={"X-Access-Confirmation": first["confirmation_token"]},
        ).status_code
        == 409
    )
    change(client, "roles", "POST", {"name": "Concurrent role", "permissions": []})
    assert (
        client.post(
            "/api/admin/roles",
            json=body,
            headers={"X-Access-Confirmation": first["confirmation_token"]},
        ).status_code
        == 409
    )
    fresh = preview(client, "roles", "POST", body).json()
    with client.app.state.factory.begin() as session:
        session.get(
            AccessChangeConfirmation, token_hash(fresh["confirmation_token"])
        ).expires_at = time.time() - 1
    assert (
        client.post(
            "/api/admin/roles",
            json=body,
            headers={"X-Access-Confirmation": fresh["confirmation_token"]},
        ).status_code
        == 409
    )
    with client.app.state.factory() as session:
        assert session.scalar(select(Role).where(Role.name == "New role")) is None


def test_preview_includes_unchanged_overlap_and_changes_nothing_until_confirmation(
    auth_client, tmp_path
):
    client = auth_client
    setup_admin(client, tmp_path)
    destinations(client)
    lower = change(
        client, "roles", "POST", {"name": "Lower", "permissions": [permission("first", "request")]}
    ).json()
    higher = change(
        client, "roles", "POST", {"name": "Higher", "permissions": [permission("first", "full")]}
    ).json()
    member = change(
        client,
        "users",
        "POST",
        {"username": "member", "password": PASSWORD, "role_ids": [lower["id"], higher["id"]]},
    ).json()
    body = {"name": "Lower", "permissions": [permission("first", "print")]}
    proposed = preview(client, "roles", "PUT", body, lower["id"]).json()
    impact = next(user for user in proposed["affected_users"] if user["id"] == member["id"])
    assert impact["before"]["destination_levels"]["first"] == "full"
    assert impact["after"]["destination_levels"]["first"] == "full"
    assert not impact["changed"]
    with client.app.state.factory() as session:
        assert session.get(Role, lower["id"]).permissions[0]["level"] == "request"
    assert (
        client.put(
            f"/api/admin/roles/{lower['id']}",
            json=body,
            headers={"X-Access-Confirmation": proposed["confirmation_token"]},
        ).status_code
        == 200
    )


def test_disable_and_password_reset_revoke_sessions(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    other = TestClient(client.app)
    try:
        member = register_member(other, invite(client))["user"]
        token = other.cookies[COOKIE_NAME]
        change(client, "users", "PUT", {"disabled": True, "role_ids": ["member"]}, member["id"])
        assert other.get("/api/templates").status_code == 401
        with client.app.state.factory() as session:
            assert session.get(AuthSession, token_hash(token)) is None
        change(
            client,
            "users",
            "PUT",
            {"disabled": False, "role_ids": ["member"], "password": "a completely new password"},
            member["id"],
        )
        assert (
            other.post(
                "/api/auth/login", json={"username": "member", "password": PASSWORD}
            ).status_code
            == 401
        )
        assert login(other, "member", "a completely new password")["user"]["id"] == member["id"]
    finally:
        other.close()


def test_authentication_attempts_are_throttled(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    for _ in range(10):
        assert (
            client.post(
                "/api/auth/login", json={"username": "unknown", "password": PASSWORD}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login", json={"username": "unknown", "password": PASSWORD}
        ).status_code
        == 429
    )


def test_one_code_cannot_be_redeemed_concurrently(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    code = invite(client)

    def redeem(username):
        other = TestClient(client.app)
        try:
            return other.post(
                "/api/auth/register",
                json={"username": username, "password": PASSWORD, "registration_code": code},
            ).status_code
        finally:
            other.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(redeem, ("first-member", "second-member"))) == [201, 400]
    with client.app.state.factory() as session:
        assert len(list(session.scalars(select(User)))) == 2


def test_group_roles_and_registration_admin_escalation_are_rejected(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    assert (
        client.post(
            "/api/admin/groups", json={"name": "Bad", "role_ids": ["administrator"], "members": []}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/admin/users",
            json={"username": "bad", "password": PASSWORD, "is_admin": True, "role_ids": []},
        ).status_code
        == 422
    )


def test_existing_sessions_see_role_changes_immediately(auth_client, tmp_path):
    client = auth_client
    setup_admin(client, tmp_path)
    destinations(client)
    role = change(
        client,
        "roles",
        "POST",
        {
            "name": "Scoped printing",
            "permissions": [permission("first", "print")],
        },
    ).json()
    member = change(
        client,
        "users",
        "POST",
        {
            "username": "member",
            "password": PASSWORD,
            "role_ids": [role["id"]],
        },
    ).json()
    other = TestClient(client.app)
    try:
        login(other, member["username"])
        assert (
            other.get("/api/auth/session").json()["user"]["destination_levels"]["first"] == "print"
        )
        change(client, "roles", "PUT", {"name": "Scoped printing", "permissions": []}, role["id"])
        assert other.get("/api/auth/session").json()["user"]["destination_levels"] == {}
    finally:
        other.close()


def test_role_migration_preserves_accounts_without_granting_new_moderation(tmp_path):
    import sqlalchemy as sa

    from app.db import make_engine, session_factory

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "b7d49210cf36")
    engine = make_engine(url)
    with engine.begin() as connection:
        meta = sa.MetaData()
        roles = sa.Table("roles", meta, autoload_with=connection)
        users = sa.Table("users", meta, autoload_with=connection)
        groups = sa.Table("user_groups", meta, autoload_with=connection)
        devices = sa.Table("printers", meta, autoload_with=connection)
        grants = sa.Table("printer_grants", meta, autoload_with=connection)
        connection.execute(
            roles.insert(),
            [
                {
                    "id": "read-only",
                    "name": "Read only",
                    "permissions": ["print.manage", "printers.manage"],
                },
                {
                    "id": "printing",
                    "name": "Printing",
                    "permissions": ["print.submit", "print.direct"],
                },
            ],
        )
        for identifier, role_ids, administrator in (
            ("admin", [], True),
            ("viewer", ["read-only"], False),
            ("printer", ["printing"], False),
            ("editor", ["member"], False),
        ):
            connection.execute(
                users.insert().values(
                    id=identifier,
                    username=identifier,
                    password_hash="unused",
                    is_admin=administrator,
                    disabled=False,
                    role_ids=role_ids,
                    created_at=1,
                )
            )
        connection.execute(
            groups.insert().values(
                id="sharing", name="Sharing", user_ids=["viewer", "printer", "editor"], role_ids=[]
            )
        )
        connection.execute(
            devices.insert().values(id="first", name="First", driver="brother-pt-p710bt", config={})
        )
        connection.execute(
            grants.insert().values(subject_type="group", subject_id="sharing", printer_id="first")
        )
    engine.dispose()
    command.upgrade(config, "head")
    command.check(config)
    engine = make_engine(url)
    try:
        with session_factory(engine)() as session:
            assert actor_for_user(session, session.get(User, "admin")).is_admin
            assert (
                actor_for_user(session, session.get(User, "viewer")).destination_levels["first"]
                == "none"
            )
            assert (
                actor_for_user(session, session.get(User, "printer")).destination_levels["first"]
                == "print"
            )
            assert (
                actor_for_user(session, session.get(User, "editor")).destination_levels["first"]
                == "request"
            )
            memberships = {
                member["user_id"]: member for member in session.get(UserGroup, "sharing").members
            }
            assert not memberships["viewer"]["can_create"]
            assert not memberships["printer"]["can_edit_others"]
            assert memberships["editor"]["can_delete_others"]
    finally:
        engine.dispose()
