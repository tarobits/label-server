"""Existing accounts and notification endpoints survive the upgrade."""

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, inspect, select

from app.db import make_engine


def test_email_upgrade_preserves_existing_data_and_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'email-migration.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "a18d6c93b204")
    engine = make_engine(url)
    with engine.begin() as connection:
        users = Table("users", MetaData(), autoload_with=connection)
        endpoints = Table("notification_endpoints", MetaData(), autoload_with=connection)
        connection.execute(
            users.insert().values(
                id="existing-user",
                username="existing",
                password_hash="unchanged-hash",
                disabled=False,
                role_ids=["member"],
                created_at=1,
            )
        )
        connection.execute(
            endpoints.insert().values(
                id="existing-endpoint",
                name="Operations",
                url="https://ntfy.invalid",
                topic="operations",
                token="test-token",
                enabled=True,
                destination_ids=[],
                all_printers=True,
                kinds=["empty_tape"],
                priorities={"empty_tape": 4},
                revision=3,
                created_at=1,
            )
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        users = Table("users", MetaData(), autoload_with=connection)
        endpoints = Table("notification_endpoints", MetaData(), autoload_with=connection)
        user = connection.execute(select(users)).mappings().one()
        assert user["email"] is None and user["password_hash"] == "unchanged-hash"
        endpoint = connection.execute(select(endpoints)).mappings().one()
        assert endpoint["transport"] == "ntfy" and endpoint["email"] == ""
        assert endpoint["owner_id"] is None and endpoint["revision"] == 3
        assert endpoint["printer_kinds"] == {}
        assert endpoint["printer_priorities"] == {}
        assert endpoint["token"] == "test-token" and endpoint["enabled"]
        assert "recovery_tokens" in inspect(connection).get_table_names()
    with engine.begin() as connection:
        connection.execute(
            endpoints.insert().values(
                id="email-endpoint",
                name="Email",
                transport="email",
                email="user@example.invalid",
                url="",
                topic="",
                token="",
                enabled=True,
                destination_ids=[],
                all_printers=False,
                kinds=["general"],
                priorities={},
                revision=1,
                created_at=1,
            )
        )
    command.downgrade(config, "a18d6c93b204")
    with engine.connect() as connection:
        assert "recovery_tokens" not in inspect(connection).get_table_names()
        old_endpoints = Table("notification_endpoints", MetaData(), autoload_with=connection)
        assert not connection.execute(
            select(old_endpoints.c.enabled).where(old_endpoints.c.id == "email-endpoint")
        ).scalar_one()
    engine.dispose()
