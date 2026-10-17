"""One-time legacy notification imports use only temporary databases and fake settings."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, inspect, select

from app.db import make_engine, session_factory
from app.models import Notification, NotificationEndpoint, User

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIORITIES = {
    "general": 3,
    "empty_tape": 4,
    "printer_blocked": 4,
    "batch_review": 4,
    "tape_waiting": 3,
    "approval_digest": 3,
}


def migration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config.attributes["database_url"] = url
    command.upgrade(config, "f63d84b29a10")
    return config, url


def existing_user(url):
    engine = make_engine(url)
    try:
        with session_factory(engine).begin() as session:
            session.add(
                User(
                    id="legacy-administrator",
                    username="Legacy administrator",
                    password_hash="unused-test-password",
                    role_ids=["administrator"],
                )
            )
    finally:
        engine.dispose()


def endpoints(url):
    engine = make_engine(url)
    try:
        with session_factory(engine)() as session:
            return list(session.scalars(select(NotificationEndpoint)))
    finally:
        engine.dispose()


def test_existing_installation_imports_legacy_fake_environment_once(tmp_path, monkeypatch):
    config, url = migration(tmp_path, monkeypatch)
    existing_user(url)
    monkeypatch.setenv("LABEL_NTFY_URL", "https://ntfy.invalid/legacy/")
    monkeypatch.setenv("LABEL_NTFY_TOPIC", "fake-legacy-topic")
    monkeypatch.setenv("LABEL_NTFY_TOKEN", "fake-test-token")
    command.upgrade(config, "head")
    imported = endpoints(url)
    assert len(imported) == 1
    endpoint = imported[0]
    assert endpoint.name == "Imported administrator notifications"
    assert endpoint.url == "https://ntfy.invalid/legacy"
    assert endpoint.topic == "fake-legacy-topic"
    assert endpoint.token == "fake-test-token"
    assert endpoint.enabled
    assert endpoint.destination_ids == []
    assert endpoint.all_printers
    assert endpoint.priorities == DEFAULT_PRIORITIES
    assert set(endpoint.kinds) == {
        "general",
        "empty_tape",
        "printer_blocked",
        "batch_review",
        "tape_waiting",
        "approval_digest",
    }
    assert endpoint.revision == 2
    # Running an already-applied upgrade cannot recreate or replace configuration.
    monkeypatch.setenv("LABEL_NTFY_TOPIC", "different-fake-topic")
    command.upgrade(config, "head")
    assert [value.topic for value in endpoints(url)] == ["fake-legacy-topic"]


def test_existing_installation_can_import_legacy_fake_dotenv(tmp_path, monkeypatch):
    config, url = migration(tmp_path, monkeypatch)
    existing_user(url)
    # Unset the isolated environment entries so only this temporary .env is consulted.
    for name in ("LABEL_NTFY_URL", "LABEL_NTFY_TOPIC", "LABEL_NTFY_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "LABEL_NTFY_URL=http://ntfy.invalid:8080\n"
        "LABEL_NTFY_TOPIC=fake-dotenv-topic\n"
        "LABEL_NTFY_TOKEN=fake-dotenv-token\n"
    )
    command.upgrade(config, "head")
    imported = endpoints(url)
    assert len(imported) == 1
    assert imported[0].topic == "fake-dotenv-topic"
    assert imported[0].token == "fake-dotenv-token"


def test_fresh_installation_never_imports_an_environment_channel(tmp_path, monkeypatch):
    config, url = migration(tmp_path, monkeypatch)
    monkeypatch.setenv("LABEL_NTFY_URL", "https://ntfy.invalid")
    monkeypatch.setenv("LABEL_NTFY_TOPIC", "fake-fresh-topic")
    monkeypatch.setenv("LABEL_NTFY_TOKEN", "fake-fresh-token")
    command.upgrade(config, "head")
    assert endpoints(url) == []


def test_notification_tables_downgrade_and_upgrade_without_reimporting_config(
    tmp_path, monkeypatch
):
    config, url = migration(tmp_path, monkeypatch)
    existing_user(url)
    command.upgrade(config, "head")
    engine = make_engine(url)
    try:
        assert {"notification_endpoints", "notification_deliveries"}.issubset(
            inspect(engine).get_table_names()
        )
        assert "routed_at" in {
            column["name"] for column in inspect(engine).get_columns("notifications")
        }
        command.downgrade(config, "f63d84b29a10")
        assert "notification_endpoints" not in inspect(engine).get_table_names()
        assert "notification_deliveries" not in inspect(engine).get_table_names()
        assert "routed_at" not in {
            column["name"] for column in inspect(engine).get_columns("notifications")
        }
        command.upgrade(config, "head")
        assert {"notification_endpoints", "notification_deliveries"}.issubset(
            inspect(engine).get_table_names()
        )
        assert "routed_at" in {
            column["name"] for column in inspect(engine).get_columns("notifications")
        }
        assert endpoints(url) == []
        with session_factory(engine)() as session:
            assert session.get(User, "legacy-administrator") is not None
    finally:
        engine.dispose()


def test_destination_only_migration_preserves_scope_and_cancels_old_pending_deliveries(
    tmp_path, monkeypatch
):
    config, url = migration(tmp_path, monkeypatch)
    command.upgrade(config, "a73b159dc820")
    engine = make_engine(url)
    try:
        metadata = MetaData()
        old_endpoints = Table("notification_endpoints", metadata, autoload_with=engine)
        old_deliveries = Table("notification_deliveries", metadata, autoload_with=engine)
        old_notices = Table("notifications", metadata, autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(
                old_notices.insert(),
                [
                    {
                        "id": "old-" + suffix,
                        "title": "Old",
                        "message": "Old",
                        "path": "/",
                        "created_at": 1,
                        "next_attempt_at": 1,
                        "attempts": 0,
                        "cancelled": False,
                        "routed_at": 1,
                        "delivered_at": 2 if suffix == "done" else None,
                    }
                    for suffix in ("pending", "done")
                ],
            )
            for identifier, destinations, roles, revision in (
                ("all", [], ["administrator"], 3),
                ("selected", ["legacy-printer", "legacy-group"], [], 7),
            ):
                connection.execute(
                    old_endpoints.insert(),
                    {
                        "id": identifier,
                        "name": identifier,
                        "url": "https://ntfy.invalid",
                        "topic": identifier,
                        "token": "preserved-secret",
                        "enabled": True,
                        "destination_ids": destinations,
                        "role_ids": roles,
                        "minimum_level": "full",
                        "kinds": ["empty_tape"],
                        "revision": revision,
                        "created_at": 1,
                    },
                )
                for suffix, delivered_at in (("pending", None), ("done", 2)):
                    connection.execute(
                        old_deliveries.insert(),
                        {
                            "id": identifier + suffix,
                            "notification_id": "old-" + suffix,
                            "endpoint_id": identifier,
                            "endpoint_revision": revision,
                            "endpoint_name": identifier,
                            "attempts": 1,
                            "next_attempt_at": 3,
                            "delivered_at": delivered_at,
                            "cancelled": False,
                        },
                    )
        command.upgrade(config, "c91d8e5a206b")
        columns = {
            column["name"] for column in inspect(engine).get_columns("notification_endpoints")
        }
        assert "all_printers" in columns
        assert not {"role_ids", "minimum_level"} & columns
        with session_factory(engine)() as session:
            all_channel = session.get(NotificationEndpoint, "all")
            selected = session.get(NotificationEndpoint, "selected")
            assert all_channel.all_printers is True and all_channel.destination_ids == []
            assert all_channel.revision == 4
            assert selected.all_printers is False
            assert selected.destination_ids == ["legacy-printer", "legacy-group"]
            assert selected.revision == 8
            assert all_channel.token == selected.token == "preserved-secret"
            assert all_channel.priorities == selected.priorities == DEFAULT_PRIORITIES
            assert session.get(Notification, "old-pending").cancelled
            assert session.get(Notification, "old-done").delivered_at == 2
            assert not session.get(Notification, "old-done").cancelled
        deliveries = Table("notification_deliveries", MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            rows = list(connection.execute(select(deliveries)).mappings())
            assert all(row["cancelled"] for row in rows if row["delivered_at"] is None)
            assert all(not row["cancelled"] for row in rows if row["delivered_at"] is not None)
            assert all(row["delivered_at"] == 2 for row in rows if row["id"].endswith("done"))
        # Idempotent re-upgrade cannot broaden selected IDs or increment revisions again.
        command.upgrade(config, "c91d8e5a206b")
        assert {channel.id: channel.revision for channel in endpoints(url)} == {
            "all": 4,
            "selected": 8,
        }
        command.downgrade(config, "a73b159dc820")
        command.upgrade(config, "c91d8e5a206b")
    finally:
        engine.dispose()
