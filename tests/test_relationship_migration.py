"""Explicit repair, maintenance isolation, and final database enforcement."""

import pytest
from alembic import command
from alembic.config import Config
from app_client import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_access_security import accounts as accounts
from test_auth import setup_admin

from app.config import Settings
from app.db import make_engine, session_factory
from app.main import create_app
from app.models import LabelTemplate, ReleaseMigration, UserGroup
from migrations.relationships_v1 import VERSION, finalize, violations


def database(tmp_path):
    url = f"sqlite:///{tmp_path / 'relationships.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "19191a0b41a7")
    return url, config


def test_clean_upgrade_enforces_keys_and_roundtrips(tmp_path):
    url, config = database(tmp_path)
    command.upgrade(config, "head")
    command.check(config)
    engine = make_engine(url)
    with engine.connect() as connection:
        assert not violations(connection)
        assert connection.scalar(
            text("SELECT completed_at FROM release_migrations WHERE version=:v"), {"v": VERSION}
        )
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text("INSERT INTO companion_pins (user_id, pin_hash) VALUES ('missing', 'invalid')")
        )
    engine.dispose()
    command.downgrade(config, "19191a0b41a7")
    command.upgrade(config, "head")
    command.check(config)


def test_bound_companion_blocks_account_deletion(accounts):
    from test_auth import change, preview

    from app.models import Companion, Location, User

    admin, _, _ = accounts
    with admin.app.state.factory.begin() as session:
        session.add(Location(id="station-location", name="Workshop"))
        session.flush()
        session.add(
            Companion(
                id="bound-station",
                name="Station",
                location_id="station-location",
                bound_user_id="alice",
            )
        )
    assert preview(admin, "users", "DELETE", identifier="alice").status_code == 409
    with admin.app.state.factory.begin() as session:
        assert not session.get_one(User, "alice").disabled
        session.get_one(Companion, "bound-station").bound_user_id = "bob"
    assert change(admin, "users", "DELETE", identifier="alice").status_code == 204


def test_group_deletion_requires_template_reassignment(accounts):
    from test_auth import change, preview

    admin, _, _ = accounts
    with admin.app.state.factory.begin() as session:
        session.add_all(
            [
                UserGroup(id="old-group", name="Old", members=[]),
                UserGroup(id="new-group", name="New", members=[]),
            ]
        )
        session.flush()
        session.add(
            LabelTemplate(
                id="group-template", name="Label", group_id="old-group", scope="group", document={}
            )
        )
    assert preview(admin, "groups", "DELETE", identifier="old-group").status_code == 409
    with admin.app.state.factory.begin() as session:
        session.get_one(LabelTemplate, "group-template").group_id = "new-group"
    assert change(admin, "groups", "DELETE", identifier="old-group").status_code == 204


def test_nonadministrator_cannot_inspect_or_repair_relationships(accounts):
    admin, alice, _ = accounts
    with admin.app.state.factory.begin() as session:
        item = session.get_one(ReleaseMigration, VERSION)
        item.completed_at = None
    admin.app.state.relationship_maintenance = True
    for path in (
        "",
        "/rows?key=label_templates.group_id",
        "/targets?key=label_templates.group_id",
        "/creation?key=label_templates.group_id",
        "/creation/targets?key=label_templates.group_id&kind=user_groups",
    ):
        assert alice.get("/api/migration/relationships" + path).status_code == 403
    for path in ("/creation", "/creation/preview"):
        assert (
            alice.post(
                "/api/migration/relationships" + path,
                json={
                    "key": "label_templates.group_id",
                    "token": "a" * 64,
                    "kind": "user_groups",
                    "values": {"name": "Unauthorized"},
                    "reason": "Unauthorized",
                },
            ).status_code
            == 403
        )
    assert alice.post("/api/migration/relationships/complete", json={}).status_code == 403
    assert (
        alice.post(
            "/api/migration/relationships/repair",
            json={
                "key": "label_templates.group_id",
                "token": "a" * 64,
                "target": "new",
                "reason": "Unauthorized",
            },
        ).status_code
        == 403
    )


def test_admin_repairs_then_restart_installs_constraints(tmp_path):
    url, config = database(tmp_path)
    engine = make_engine(url)
    factory = session_factory(engine)
    with factory.begin() as session:
        session.add(UserGroup(id="replacement", name="Replacement", members=[]))
        session.add(
            LabelTemplate(
                id="broken", name="Saved label", group_id="missing", scope="group", document={}
            )
        )
    command.upgrade(config, "head")
    with factory() as session:
        assert session.get_one(LabelTemplate, "broken").group_id == "missing"
        assert session.get_one(ReleaseMigration, VERSION).completed_at is None
    app = create_app(Settings(database_url=url), start_worker=False)
    with TestClient(app) as client:
        assert app.state.relationship_maintenance
        assert client.get("/api/migration/relationships").status_code == 401
        setup_admin(client, tmp_path)
        assert client.get("/api/auth/session").json()["relationship_migration_required"]
        assert client.get("/api/workspace").status_code == 503
        assert client.get("/api/companion/work").status_code == 503
        assert client.post("/api/migration/relationships/complete", json={}).status_code == 409
        state = client.get("/api/migration/relationships").json()
        assert state["relationships"][0]["table"] == "label_templates"
        key = "label_templates.group_id"
        row = client.get("/api/migration/relationships/rows", params={"key": key}).json()[0]
        body = {
            "key": key,
            "token": row["token"],
            "target": "replacement",
            "reason": "Administrator verified the intended group",
        }
        csrf = client.headers.pop("X-CSRF-Token")
        assert client.post("/api/migration/relationships/repair", json=body).status_code == 403
        client.headers["X-CSRF-Token"] = csrf
        assert (
            client.post(
                "/api/migration/relationships/repair", json={**body, "target": "nonexistent"}
            ).status_code
            == 422
        )
        result = client.post("/api/migration/relationships/repair", json=body)
        assert result.status_code == 200, result.text
        assert client.post("/api/migration/relationships/repair", json=body).status_code == 409
        assert client.post("/api/migration/relationships/complete", json={}).json()[
            "restart_required"
        ]
        assert client.get("/api/workspace").status_code == 503
    restarted = create_app(Settings(database_url=url), start_worker=False)
    with TestClient(restarted):
        assert not restarted.state.relationship_maintenance
        with restarted.state.factory() as session:
            assert session.get_one(LabelTemplate, "broken").group_id == "replacement"
            assert session.get_one(ReleaseMigration, VERSION).completed_at
    engine.dispose()
    assert any(
        fk["constrained_columns"] == ["group_id"]
        for fk in inspect(engine).get_foreign_keys("label_templates")
    )
    command.check(config)
    engine.dispose()


def test_finalize_refuses_unrepaired_data_without_partial_constraints(tmp_path):
    url, config = database(tmp_path)
    engine = make_engine(url)
    with session_factory(engine).begin() as session:
        session.add(
            LabelTemplate(
                id="broken", name="Saved label", group_id="missing", scope="group", document={}
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        with pytest.raises(RuntimeError, match="label_templates.group_id"):
            finalize(connection)
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert (
            connection.scalar(text("SELECT group_id FROM label_templates WHERE id='broken'"))
            == "missing"
        )
        assert not any(
            fk["constrained_columns"] == ["group_id"]
            for fk in inspect(connection).get_foreign_keys("label_templates")
        )
    engine.dispose()


def test_sqlite_constraint_failure_rolls_back_rebuilt_tables(tmp_path, monkeypatch):
    import migrations.relationships_v1 as migration

    url, _ = database(tmp_path)
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO release_migrations (version, draft) VALUES (:v, '{}')"),
            {"v": VERSION},
        )
    install = migration.install

    def fail_after_rebuild(connection):
        install(connection)
        raise RuntimeError("Injected failure after DDL")

    monkeypatch.setattr(migration, "install", fail_after_rebuild)
    with engine.connect() as connection:
        with pytest.raises(RuntimeError, match="Injected failure"):
            finalize(connection)
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert (
            connection.scalar(
                text("SELECT completed_at FROM release_migrations WHERE version=:v"), {"v": VERSION}
            )
            is None
        )
        assert not any(
            fk["constrained_columns"] == ["group_id"]
            for fk in inspect(connection).get_foreign_keys("label_templates")
        )
    monkeypatch.setattr(migration, "install", install)
    with engine.connect() as connection:
        finalize(connection)
        assert any(
            fk["constrained_columns"] == ["group_id"]
            for fk in inspect(connection).get_foreign_keys("label_templates")
        )
    engine.dispose()


def test_invalid_credentials_can_only_be_explicitly_revoked(tmp_path):
    url, config = database(tmp_path)
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO companion_pins (user_id, pin_hash) VALUES ('missing', 'invalid')")
        )
    command.upgrade(config, "head")
    with TestClient(create_app(Settings(database_url=url), start_worker=False)) as client:
        owner = setup_admin(client, tmp_path)["user"]["id"]
        key = "companion_pins.user_id"
        row = client.get("/api/migration/relationships/rows", params={"key": key}).json()[0]
        assert row["revoke_only"]
        assert "invalid" not in str(row)
        assert (
            client.get("/api/migration/relationships/creation", params={"key": key}).json()[
                "resources"
            ]
            == {}
        )
        assert (
            client.post(
                "/api/migration/relationships/creation/preview",
                json={
                    "key": key,
                    "token": row["token"],
                    "kind": "users",
                    "values": {"username": "replacement", "password": "replacement-test-password"},
                    "reason": "Cannot transfer credentials",
                },
            ).status_code
            == 422
        )
        body = {
            "key": key,
            "token": row["token"],
            "target": owner,
            "reason": "Owner no longer exists",
        }
        assert client.post("/api/migration/relationships/repair", json=body).status_code == 422
        body.update(target=None, revoke=True)
        assert client.post("/api/migration/relationships/repair", json=body).status_code == 200
        assert client.get("/api/migration/relationships").json()["relationships"] == []
    engine.dispose()
