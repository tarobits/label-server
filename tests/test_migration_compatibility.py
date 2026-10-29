"""Keep every already-applied revision usable across unreleased migration edits."""

import json

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


@pytest.mark.parametrize(
    "previous", ["e92b4f06a318", "a91e2bf0c463", "merged_a91", "b37c60e14f92", "c84e21d690ab"]
)
def test_upgrade_preserves_history_from_each_applied_migration_shape(tmp_path, previous):
    url = f"sqlite:///{tmp_path / 'compatibility.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "a91e2bf0c463" if previous == "merged_a91" else previous)
    engine = create_engine(url)
    plan = {"estimated_mm": 49, "leader_mm": 24.5}
    with engine.begin() as connection:
        if previous == "merged_a91":
            connection.exec_driver_sql("ALTER TABLE batches ADD COLUMN consumption_source VARCHAR")
        columns = {column["name"] for column in inspect(connection).get_columns("batches")}
        names = [
            "id",
            "cartridge_id",
            "state",
            "created_at",
            "estimated_mm",
            "consumed_mm",
            "shortage_warning",
        ]
        values = ["saved-attempt", "saved-cartridge", "PRINTED", 1, 49, 49, 0]
        if "print_plan" in columns:
            names.append("print_plan")
            values.append(json.dumps(plan))
        if "consumption_source" in columns:
            names.append("consumption_source")
            values.append("reported")
        connection.execute(
            text(
                f"INSERT INTO batches ({','.join(names)}) VALUES ({','.join(':' + str(i) for i in range(len(values)))})"
            ),
            {str(i): value for i, value in enumerate(values)},
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        row = (
            connection.execute(text("SELECT * FROM batches WHERE id='saved-attempt'"))
            .mappings()
            .one()
        )
        assert row["consumed_mm"] == 49
        assert row["consumption_source"] == (
            "reported" if "consumption_source" in columns else None
        )
        assert row["print_plan"] == (json.dumps(plan) if "print_plan" in columns else None)
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "e72f5b3a8109"
        )
    # All historical versions still support the project's schema roundtrip checks.
    command.downgrade(config, "e92b4f06a318")
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
