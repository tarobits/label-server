"""Historical previews and restores preserve identity, access, and queued output."""

import copy

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, inspect
from test_access_security import SVG, image_document
from test_access_security import accounts as account_fixture
from test_auth import change

from app.db import make_engine

accounts = account_fixture


def create(client, name="Original template", scope="personal", document=None):
    response = client.post(
        "/api/templates",
        json={
            "name": name,
            "scope": scope,
            "document": document
            or {
                "out_of_bounds": "clip",
                "preview_tape": {
                    "id": "saved-tape",
                    "name": "Yellow",
                    "foreground": "#000000",
                    "background": "#ffcc00",
                },
                "elements": [
                    {
                        "id": "text",
                        "kind": "text",
                        "x": 2,
                        "y": 2,
                        "width": 40,
                        "height": 12,
                        "content": name,
                    }
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def update(client, item, name="Edited template", **extra):
    document = copy.deepcopy(item["document"])
    if document["elements"] and document["elements"][0]["kind"] == "text":
        document["elements"][0]["content"] = name
    response = client.put(
        f"/api/templates/{item['id']}",
        json={
            "name": name,
            "scope": item["scope"],
            "group_id": item["group_id"],
            "document": document,
            "expected_revision": item["revision"],
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_history_records_real_editors_and_restores_as_a_new_revision(accounts):
    admin, alice, _ = accounts
    original = create(alice)
    edited = update(admin, original)
    path = f"/api/templates/{original['id']}"
    history = alice.get(f"{path}/revisions").json()
    assert [item["revision"] for item in history] == [2, 1]
    assert history[0]["edited_by"] == {"id": "administrator", "name": "administrator"}
    assert history[1]["edited_by"] == {"id": "alice", "name": "alice"}
    assert history[0]["created_at"] >= history[1]["created_at"] > 0
    preview = alice.get(f"{path}/revisions/1/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["png"] != alice.get(f"{path}/revisions/2/preview").json()["png"]
    assert preview.json()["missing_assets"] == {}
    response = alice.post(f"{path}/revisions/1/restore", json={"expected_revision": 2})
    assert response.status_code == 200, response.text
    restored = response.json()
    assert restored["revision"] == 3
    for field in ("name", "document", "owner_id", "scope", "group_id"):
        assert restored[field] == original[field]
    history = alice.get(f"{path}/revisions").json()
    assert [item["revision"] for item in history] == [3, 2, 1]
    assert history[0]["restored_from_revision"] == 1
    assert history[0]["edited_by"]["id"] == "alice"
    assert history[1]["name"] == edited["name"]
    assert alice.get(f"{path}/revisions/3/preview").json()["png"] == preview.json()["png"]


def test_restore_checks_current_access_conflicts_csrf_and_preserves_sharing(accounts):
    admin, alice, bob = accounts
    original = create(alice)
    edited = update(alice, original)
    path = f"/api/templates/{original['id']}"
    assert bob.get(f"{path}/revisions").status_code == 403
    assert bob.get(f"{path}/revisions/1/preview").status_code == 403
    assert bob.post(f"{path}/revisions/1/restore", json={"expected_revision": 2}).status_code == 403
    assert (
        alice.post(f"{path}/revisions/1/restore", json={"expected_revision": 1}).status_code == 409
    )
    assert (
        alice.post(f"{path}/revisions/999/restore", json={"expected_revision": 2}).status_code
        == 404
    )
    assert alice.get(f"{path}/revisions/999/preview").status_code == 404
    csrf = alice.headers.pop("X-CSRF-Token")
    try:
        assert (
            alice.post(f"{path}/revisions/1/restore", json={"expected_revision": 2}).status_code
            == 403
        )
    finally:
        alice.headers["X-CSRF-Token"] = csrf
    shared = update(admin, edited, scope="global")
    assert bob.get(f"{path}/revisions").status_code == 200
    assert bob.get(f"{path}/revisions/1/preview").status_code == 200
    assert bob.post(f"{path}/revisions/1/restore", json={"expected_revision": 3}).status_code == 403
    restored = admin.post(
        f"{path}/revisions/1/restore", json={"expected_revision": shared["revision"]}
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["scope"] == "global"
    assert restored.json()["owner_id"] == "alice"
    assert len(alice.get(f"{path}/revisions").json()) == 4
    assert admin.delete(path).status_code == 200
    assert (
        admin.post(f"{path}/revisions/1/restore", json={"expected_revision": 4}).status_code == 409
    )


def test_restoring_does_not_change_existing_queued_labels(accounts):
    admin, _, _ = accounts
    original = create(admin)
    tape = admin.post("/api/tape-profiles", json={"name": "White", "width_mm": 24}).json()
    edited = update(admin, original)
    job = admin.post(
        "/api/jobs", json={"template": original["id"], "tape_profile": tape["id"], "data": {}}
    ).json()
    frozen = admin.get(f"/api/jobs/{job['id']}").json()["template_snapshot"]
    assert (
        admin.post(
            f"/api/templates/{original['id']}/revisions/1/restore",
            json={"expected_revision": edited["revision"]},
        ).status_code
        == 200
    )
    assert admin.get(f"/api/jobs/{job['id']}").json()["template_snapshot"] == frozen


def test_history_shares_only_artwork_in_readable_revisions(accounts):
    admin, alice, bob = accounts
    uploaded = admin.post("/api/image-assets?name=Historical-artwork", content=SVG)
    assert uploaded.status_code == 201
    asset = uploaded.json()["id"]
    original = create(admin, scope="global", document=image_document(asset))
    update(admin, original, document={"elements": [], "fields": []})
    path = f"/api/templates/{original['id']}"
    assert alice.get(f"/api/image-assets/{asset}/preview").status_code == 200
    assert alice.get(f"{path}/revisions/1/preview").status_code == 200
    role = change(
        admin,
        "roles",
        "POST",
        {
            "name": "Collaborators",
            "permissions": [{"kind": "application", "permission": "templates.edit_global"}],
        },
    ).json()
    change(admin, "users", "PUT", {"disabled": False, "role_ids": ["member", role["id"]]}, "alice")
    restored = alice.post(f"{path}/revisions/1/restore", json={"expected_revision": 2})
    assert restored.status_code == 200, restored.text
    assert restored.json()["document"] == original["document"]
    private = update(admin, restored.json(), scope="personal")
    assert bob.get(f"/api/image-assets/{asset}/preview").status_code == 403
    assert bob.get(f"{path}/revisions/1/preview").status_code == 403
    assert private["scope"] == "personal"


def test_deleted_artwork_is_previewed_as_missing_and_cannot_be_restored(accounts):
    admin, _, _ = accounts
    asset = admin.post("/api/image-assets?name=Retained-artwork", content=SVG).json()["id"]
    original = create(admin, document=image_document(asset))
    update(admin, original, document={"elements": [], "fields": []})
    assert admin.delete(f"/api/image-assets/{asset}/permanent").status_code == 200
    path = f"/api/templates/{original['id']}"
    preview = admin.get(f"{path}/revisions/1/preview")
    assert preview.status_code == 200
    assert preview.json()["missing_assets"] == {"image": "image"}
    restored = admin.post(f"{path}/revisions/1/restore", json={"expected_revision": 2})
    assert restored.status_code == 422
    assert admin.get(path).json()["revision"] == 2
    assert len(admin.get(f"{path}/revisions").json()) == 2


def test_revision_metadata_migration_preserves_unknown_legacy_history(tmp_path):
    url = f"sqlite:///{tmp_path / 'history.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "da73b8c19e42")
    engine = make_engine(url)
    with engine.begin() as connection:
        metadata = MetaData()
        templates = Table("label_templates", metadata, autoload_with=connection)
        revisions = Table("template_revisions", metadata, autoload_with=connection)
        connection.execute(
            templates.insert().values(
                id="legacy",
                name="Legacy",
                revision=1,
                document={"elements": [], "fields": []},
                archived=False,
                scope="global",
            )
        )
        connection.execute(
            revisions.insert().values(
                template_id="legacy",
                revision=1,
                name="Legacy",
                document={"elements": [], "fields": []},
            )
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        revisions = Table("template_revisions", MetaData(), autoload_with=connection)
        row = connection.execute(revisions.select()).mappings().one()
        assert row["name"] == "Legacy"
        assert row["created_at"] is None
        assert row["edited_by"] is None
        assert row["restored_from_revision"] is None
    command.downgrade(config, "da73b8c19e42")
    assert "edited_by" not in {
        column["name"] for column in inspect(engine).get_columns("template_revisions")
    }
    engine.dispose()
