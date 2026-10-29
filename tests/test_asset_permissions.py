"""Independent font/image sharing, scope creation, collaboration and migration."""

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, select
from test_access_security import accounts as account_fixture
from test_auth import change

from app.db import make_engine
from app.models import Role, UserGroup

accounts = account_fixture
SVG = b'<svg viewBox="0 0 20 20"><rect width="10" height="10"/></svg>'


def permissions(admin, user, *grants):
    with admin.app.state.factory.begin() as session:
        session.get(Role, f"{user}-access").permissions = [
            {"kind": "application", "permission": value} for value in grants
        ]
        # Replace the default personal permissions as well, for exact grant tests.
        session.get(Role, "member").permissions = []


def data(kind):
    return SVG if kind == "images" else Path("app/fonts/NotoSans.ttf").read_bytes()


def endpoint(kind):
    return "/api/image-assets" if kind == "images" else "/api/font-assets"


@pytest.mark.parametrize("kind", ["images", "fonts"])
def test_personal_global_creation_and_management_are_independent(accounts, kind):
    admin, alice, bob = accounts
    path = endpoint(kind)
    original = alice.post(path, content=data(kind)).json()
    assert original["scope"] == "personal"
    assert original["can_edit"] and original["can_delete"] and original["can_share"]
    assert bob.get(path).json() == []
    permissions(admin, "alice", "templates.create_global")
    assert alice.post(path, content=data(kind)).status_code == 403
    assert alice.post(path + "?scope=global", content=data(kind)).status_code == 403
    assert (
        alice.put(f"{path}/{original['id']}/sharing", json={"scope": "global"}).status_code == 403
    )
    # Like templates, ownership allows existing assets to be managed without creation grants.
    assert alice.delete(f"{path}/{original['id']}").status_code == 200
    assert alice.post(f"{path}/{original['id']}/restore").status_code == 200
    permissions(admin, "alice", f"{kind}.create_global")
    shared = alice.post(path + "?scope=global", content=data(kind))
    assert shared.status_code == 201, shared.text
    asset = shared.json()
    assert asset["id"] != original["id"]
    assert [row["id"] for row in bob.get(path).json()] == [asset["id"]]
    assert not bob.get(path).json()[0]["can_edit"]
    assert bob.post(f"{path}/{asset['id']}/restore").status_code == 403
    other = "fonts" if kind == "images" else "images"
    permissions(admin, "bob", f"{other}.edit_global", f"{other}.delete_global")
    assert bob.delete(f"{path}/{asset['id']}").status_code == 403
    permissions(admin, "bob", f"{kind}.edit_global")
    assert bob.post(f"{path}/{asset['id']}/restore").status_code == 200
    assert bob.delete(f"{path}/{asset['id']}").status_code == 403
    assert bob.put(f"{path}/{asset['id']}/sharing", json={"scope": "personal"}).status_code == 403
    permissions(admin, "bob", f"{kind}.delete_global")
    assert bob.post(f"{path}/{asset['id']}/restore").status_code == 403
    assert bob.delete(f"{path}/{asset['id']}").status_code == 200
    assert bob.delete(f"{path}/{asset['id']}/permanent").status_code == 200
    assert bob.get(path).json() == []
    assert alice.post(f"{path}/{asset['id']}/restore").status_code == 404
    assert admin.get(path).json()[0]["id"] == original["id"]


@pytest.mark.parametrize("kind", ["images", "fonts"])
def test_group_rights_are_scoped_to_resource_membership_and_operation(accounts, kind):
    admin, alice, bob = accounts
    path = endpoint(kind)
    permissions(admin, "alice")
    with admin.app.state.factory.begin() as session:
        session.add(
            UserGroup(
                id="team",
                name="Team",
                members=[
                    {
                        "user_id": "alice",
                        "can_create": True,
                        "can_edit_others": True,
                        "can_delete_others": True,
                    },
                    {"user_id": "bob"},
                ],
            )
        )
    assert alice.post(path + "?scope=group&group_id=team", content=data(kind)).status_code == 403
    with admin.app.state.factory.begin() as session:
        group = session.get(UserGroup, "team")
        group.members = [
            {**member, kind: {"can_create": True}} if member["user_id"] == "alice" else member
            for member in group.members
        ]
    response = alice.post(path + "?scope=group&group_id=team", content=data(kind))
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["group_name"] == "Team"
    assert bob.get(path).json()[0]["id"] == asset["id"]
    assert bob.delete(f"{path}/{asset['id']}").status_code == 403
    with admin.app.state.factory.begin() as session:
        group = session.get(UserGroup, "team")
        group.members = [
            member if member["user_id"] == "alice" else {**member, kind: {"can_edit_others": True}}
            for member in group.members
        ]
    assert bob.post(f"{path}/{asset['id']}/restore").status_code == 200
    assert bob.delete(f"{path}/{asset['id']}").status_code == 403
    assert bob.put(f"{path}/{asset['id']}/sharing", json={"scope": "global"}).status_code == 403
    with admin.app.state.factory.begin() as session:
        group = session.get(UserGroup, "team")
        group.members = [
            member
            if member["user_id"] == "alice"
            else {**member, kind: {"can_delete_others": True}}
            for member in group.members
        ]
    assert bob.delete(f"{path}/{asset['id']}").status_code == 200
    assert bob.post(f"{path}/{asset['id']}/restore").status_code == 403
    with admin.app.state.factory.begin() as session:
        group = session.get(UserGroup, "team")
        group.members = [member for member in group.members if member["user_id"] != "bob"]
    assert bob.get(path).json() == []
    assert bob.delete(f"{path}/{asset['id']}/permanent").status_code == 403
    assert alice.get(path).json()[0]["archived"]


@pytest.mark.parametrize("kind", ["images", "fonts"])
def test_scope_changes_preserve_bytes_and_never_rescope_duplicate_uploads(accounts, kind):
    admin, alice, bob = accounts
    path = endpoint(kind)
    original = alice.post(path, content=data(kind)).json()
    store = admin.app.state.images if kind == "images" else admin.app.state.fonts
    saved = store.path(original["id"]).read_bytes()
    shared = admin.put(f"{path}/{original['id']}/sharing", json={"scope": "global"})
    assert shared.status_code == 200, shared.text
    assert shared.json()["id"] == original["id"]
    assert store.path(original["id"]).read_bytes() == saved
    assert bob.get(path).json()[0]["id"] == original["id"]
    duplicate = alice.post(path, content=data(kind))
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] != original["id"]
    assert store.metadata(original["id"])["scope"] == "global"
    assert duplicate.json()["scope"] == "personal"
    assert (
        admin.put(f"{path}/{original['id']}/sharing", json={"scope": "personal"}).status_code == 200
    )
    assert bob.get(path).json() == []
    for query in (
        "?scope=global&group_id=team",
        "?scope=group",
        "?scope=group&group_id=missing",
        "?scope=invalid",
    ):
        assert admin.post(path + query, content=data(kind)).status_code == 422
    assert (
        admin.put(
            f"{path}/{original['id']}/sharing", json={"scope": "personal", "owner_id": "bob"}
        ).status_code
        == 422
    )


def test_asset_permission_migration_keeps_existing_content_private(tmp_path):
    config = Config("alembic.ini")
    config.attributes["database_url"] = f"sqlite:///{tmp_path / 'assets.db'}"
    command.upgrade(config, "d91e6a27b430")
    engine = make_engine(config.attributes["database_url"])
    with engine.begin() as connection:
        roles = Table("roles", MetaData(), autoload_with=connection)
        connection.execute(
            roles.insert(),
            [
                {
                    "id": "uploader",
                    "name": "Uploader",
                    "permissions": [{"kind": "application", "permission": "assets.write"}],
                    "protected": False,
                },
                {"id": "viewer", "name": "Viewer", "permissions": [], "protected": False},
            ],
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        values = dict(connection.execute(select(roles.c.id, roles.c.permissions)).all())
    assert {grant["permission"] for grant in values["uploader"]} == {
        "images.create_personal",
        "fonts.create_personal",
    }
    assert values["viewer"] == []
    from app.image_assets import ImageStore

    store = ImageStore(tmp_path / "images")
    item = store.add(SVG)
    metadata_path = store.root / f"{item['id']}.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("scope")
    metadata.pop("group_id")
    metadata_path.write_text(json.dumps(metadata))
    assert store.metadata(item["id"])["scope"] == "personal"
    assert store.metadata(item["id"])["group_id"] is None
    engine.dispose()


@pytest.mark.parametrize("kind", ["images", "fonts"])
def test_used_assets_remain_available_to_readers_and_cannot_be_removed_by_owner(accounts, kind):
    admin, alice, bob = accounts
    path = endpoint(kind)
    asset = alice.post(path, content=data(kind)).json()
    element = (
        {"kind": "image", "image_asset": asset["id"]}
        if kind == "images"
        else {"kind": "text", "font": asset["id"], "content": "Saved text"}
    )
    template = admin.post(
        "/api/templates",
        json={
            "name": "Shared label",
            "scope": "global",
            "document": {
                "elements": [{"id": "asset", "x": 2, "y": 2, "width": 20, "height": 8, **element}]
            },
        },
    )
    assert template.status_code == 201, template.text
    assert bob.get(path).json() == []
    assert bob.post("/api/preview", json={"template_id": template.json()["id"]}).status_code == 200
    assert alice.delete(f"{path}/{asset['id']}/permanent").status_code == 409
    assert alice.delete(f"{path}/{asset['id']}").status_code == 200
    assert bob.post("/api/preview", json={"template_id": template.json()["id"]}).status_code == 200


def test_admin_role_and_group_updates_preserve_separate_asset_grants(accounts):
    admin, alice, _ = accounts
    role = change(
        admin,
        "roles",
        "POST",
        {
            "name": "Global images",
            "permissions": [
                {"kind": "application", "permission": "images.create_global"},
                {"kind": "application", "permission": "fonts.delete_global"},
            ],
        },
    )
    assert role.status_code == 201, role.text
    updated = change(
        admin, "users", "PUT", {"disabled": False, "role_ids": [role.json()["id"]]}, "alice"
    )
    assert updated.status_code == 200, updated.text
    assert set(alice.get("/api/auth/session").json()["user"]["permissions"]) == {
        "images.create_global",
        "fonts.delete_global",
    }
    assert alice.post("/api/image-assets?scope=global", content=SVG).status_code == 201
    assert alice.post("/api/font-assets?scope=global", content=data("fonts")).status_code == 403
    group = change(
        admin,
        "groups",
        "POST",
        {
            "name": "Artwork",
            "members": [{"user_id": "alice", "images": {"can_create": True}}],
        },
    )
    assert group.status_code == 201, group.text
    member = alice.get("/api/user-groups").json()[0]
    assert member["images"]["can_create"] is True
    assert member["fonts"]["can_create"] is False
    assert member["can_create"] is False
