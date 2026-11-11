"""Run with LABEL_TEST_MARIADB_URL pointing at a disposable MariaDB server.

Every test creates and drops its own randomly named database. Nothing in the
database named by the URL is modified. CREATE/DROP DATABASE privileges are needed.
"""

import gzip
import os
import shutil
import sqlite3
import uuid

import pytest
from alembic import command
from alembic.config import Config
from app_client import TestClient
from mock_backend import MockPrinterBackend
from printer_factory import test_printer as printer_factory
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.database_lock import database_owner, lock_name
from app.db import make_engine, session_factory
from app.main import create_app
from app.models import (
    AssetImport,
    Batch,
    BatchReview,
    Cartridge,
    Location,
    PrinterDevice,
    PrinterState,
    State,
    StoredAsset,
    TapeAllocation,
    TapeProfile,
    UsageAdjustment,
    User,
)
from scripts.database_maintenance import backup, restore
from scripts.migrate_database import MigrationError, migrate


@pytest.fixture
def maria_engine(request):
    value = os.environ.get("LABEL_TEST_MARIADB_URL")
    if not value:
        pytest.skip("Set LABEL_TEST_MARIADB_URL to run MariaDB integration tests")
    url = make_url(value)
    admin = make_engine(value)
    name = "label_test_" + uuid.uuid4().hex
    collation = getattr(request, "param", "utf8mb4_nopad_bin")
    assert collation in {"utf8mb4_nopad_bin", "utf8mb4_general_ci", "latin1_swedish_ci"}
    charset = collation.split("_", 1)[0]
    with admin.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE DATABASE `{name}` CHARACTER SET {charset} COLLATE {collation}"
        )
    engine = make_engine(url.set(database=name).render_as_string(hide_password=False))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f"DROP DATABASE `{name}`")
        admin.dispose()


def upgrade(url):
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")


def test_relationship_orphans_stage_before_mariadb_enforcement(maria_engine):
    from migrations.relationships_v1 import VERSION, finalize, violations

    config = Config("alembic.ini")
    config.attributes["database_url"] = maria_engine.url.render_as_string(hide_password=False)
    command.upgrade(config, "19191a0b41a7")
    with maria_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO companion_pins (user_id, pin_hash) VALUES ('missing', 'invalid')")
        )
    command.upgrade(config, "head")
    with maria_engine.connect() as connection:
        assert violations(connection)[0]["table"] == "companion_pins"
        assert (
            connection.scalar(
                text("SELECT completed_at FROM release_migrations WHERE version=:v"), {"v": VERSION}
            )
            is None
        )
    with maria_engine.begin() as connection:
        # Simulate the administrator's explicit credential revocation.
        connection.execute(text("DELETE FROM companion_pins WHERE user_id='missing'"))
    with database_owner(maria_engine, enforce=True), maria_engine.connect() as connection:
        finalize(connection)
        assert not violations(connection)
        assert connection.scalar(
            text("SELECT completed_at FROM release_migrations WHERE version=:v"), {"v": VERSION}
        )
    command.check(config)


@pytest.mark.parametrize("maria_engine", ["utf8mb4_general_ci", "latin1_swedish_ci"], indirect=True)
@pytest.mark.parametrize("partial", [False, True])
def test_pre3_upgrade_with_different_database_collation(maria_engine, partial):
    config = Config("alembic.ini")
    config.attributes["database_url"] = maria_engine.url.render_as_string(hide_password=False)
    command.upgrade(config, "141415b69cb2")
    factory = session_factory(maria_engine)
    with factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO printers (id, name, driver, config) VALUES ('main', 'Test printer', 'mock', '{}')"
            )
        )
        session.add(TapeProfile(id="profile", name="Tape", width_mm=24))
        session.flush()
        session.add(
            Cartridge(
                id="cartridge",
                profile_id="profile",
                name="Tape",
                nominal_length_mm=8000,
                remaining_mm=7900,
            )
        )
        session.flush()
        session.add(
            Batch(
                id="batch",
                cartridge_id="cartridge",
                state=State.PRINTED,
                estimated_mm=100,
                consumed_mm=99.5,
            )
        )
    if partial:
        # MariaDB commits this DDL before the original CREATE TABLE fails.
        with maria_engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE auth_settings ADD COLUMN batch_review_evidence "
                "VARCHAR(16) NOT NULL DEFAULT 'optional'"
            )
            connection.exec_driver_sql("UPDATE auth_settings SET batch_review_evidence='required'")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    with maria_engine.connect() as connection:
        assert connection.scalar(text("SELECT batch_review_evidence FROM auth_settings")) == (
            "required" if partial else "optional"
        )
        collations = (
            connection.execute(
                text(
                    "SELECT COLLATION_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND "
                    "((TABLE_NAME='batches' AND COLUMN_NAME='id') OR "
                    "(TABLE_NAME='batch_reviews' AND COLUMN_NAME='batch_id'))"
                )
            )
            .scalars()
            .all()
        )
        assert collations == ["utf8mb4_nopad_bin", "utf8mb4_nopad_bin"]
    with factory.begin() as session:
        assert session.get_one(Batch, "batch").consumed_mm == 99.5
        session.add(
            BatchReview(
                id="review",
                request_hash="a" * 64,
                batch_id="batch",
                kind="misprint",
                actor_id="reviewer",
                actor_name="Reviewer 🦊",
                reason="Tape ran out",
                decisions={},
                previous_outcomes={},
            )
        )
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add(
            BatchReview(
                id="invalid",
                request_hash="b" * 64,
                batch_id="missing",
                kind="misprint",
                actor_id="reviewer",
                actor_name="Reviewer",
                reason="Tape ran out",
                decisions={},
                previous_outcomes={},
            )
        )
        session.flush()


def sqlite_source(tmp_path):
    path = tmp_path / "source.db"
    url = f"sqlite:///{path}"
    upgrade(url)
    engine = make_engine(url)
    with session_factory(engine).begin() as session:
        session.add(AssetImport(id="legacy-files-v1"))
        session.add(
            StoredAsset(
                kind="image",
                id="a" * 64,
                details={"id": "a" * 64, "name": "Binary fixture"},
                content=b"\x00\xff\x80image",
                source=b"\x00original",
                checksum="b" * 64,
            )
        )
        session.add(
            User(
                id="alice",
                username="alice",
                password_hash="fixture-hash",
                role_ids=["member"],
                created_at=1731234567.123456,
            )
        )
        session.add(Location(id="parent", name="Work 🦊"))
        session.flush()
        session.add(Location(id="child", name="棚", parent_id="parent"))
        session.add(
            PrinterDevice(
                id="device",
                name="Local printer",
                driver="mock",
                config={"serial": "A", "text": "é 漢字"},
            )
        )
        session.flush()
        session.add(PrinterState(id=1, printer_id="device"))
        session.add(TapeProfile(id="profile", name="Black on white", width_mm=24))
        session.flush()
        session.add(
            Cartridge(
                id="cartridge",
                profile_id="profile",
                name="Shared tape",
                owner_id=None,
                nominal_length_mm=8000,
                remaining_mm=7900.123456,
                price_minor=1499,
            )
        )
        session.flush()
        session.add(
            Batch(
                id="batch",
                printer_id="device",
                cartridge_id="cartridge",
                state=State.PRINTED,
                estimated_mm=100,
                consumed_mm=99.876544,
            )
        )
        session.flush()
        session.add(
            TapeAllocation(
                batch_id="batch",
                user_id="alice",
                username="alice",
                planned_mm=100,
                consumed_mm=99.876544,
                nominal_length_mm=8000,
                price_minor=1499,
                currency="EUR",
                cost_micros="18714367",
                charged_micros="18000000",
                cartridge_id="cartridge",
                recipient_id=None,
            )
        )
        session.add(
            UsageAdjustment(
                id="repayment",
                user_id="alice",
                username="alice",
                actor_id="past-owner",
                actor_name="Past owner",
                amount_minor=100,
                currency="EUR",
                note="Recorded payment",
                recipient_id="past-owner",
                recipient_name="Past owner",
                cartridge_allocations={"cartridge": "1000000"},
            )
        )
    engine.dispose()
    return path


def test_migration_refuses_live_source(tmp_path):
    import fcntl

    from scripts.migrate_database import stopped_source

    source = sqlite_source(tmp_path)
    with source.with_suffix(".worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(MigrationError, match="Stop the main server"), stopped_source(source):
            pytest.fail("A running source must not be copied")


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("UPDATE alembic_version SET version_num='old'", "Upgrade the SQLite database"),
        ("DELETE FROM asset_imports", "Import local assets first"),
        ("UPDATE locations SET parent_id='missing' WHERE id='child'", "broken foreign keys"),
        ("CREATE TABLE unexpected (id INTEGER)", "tables do not match"),
        ("UPDATE batches SET state='PRINTING'", "Printing is still in progress"),
        ("UPDATE users SET username='" + "a" * 129 + "'", "exceeds the MariaDB column limit"),
    ],
)
def test_migration_rejects_invalid_source_before_copying(tmp_path, sql, message):
    from scripts.migrate_database import schema_tables, stopped_source

    source = sqlite_source(tmp_path)
    with sqlite3.connect(source) as connection:
        connection.execute(sql)
    with pytest.raises(MigrationError, match=message), stopped_source(source) as connection:
        schema_tables(connection)


def test_sqlite_copy_checks_all_data_preserves_source_and_refuses_existing_target(
    maria_engine, tmp_path
):
    source = sqlite_source(tmp_path)
    original = source.read_bytes()
    counts = migrate(source, maria_engine, apply=False, backup_dir=tmp_path / "backups")
    assert counts["users"] == 1 and counts["locations"] == 2
    assert inspect(maria_engine).get_table_names() == []
    assert not (tmp_path / "backups").exists()
    assert migrate(source, maria_engine, apply=True, backup_dir=tmp_path / "backups") == counts
    config = Config("alembic.ini")
    config.attributes["database_url"] = maria_engine.url.render_as_string(hide_password=False)
    command.check(config)
    assert source.read_bytes() == original
    saved = next((tmp_path / "backups").glob("*.db"))
    assert saved.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(saved) as snapshot:
        assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    with session_factory(maria_engine)() as session:
        assert session.get_one(StoredAsset, ("image", "a" * 64)).content == b"\x00\xff\x80image"
        assert session.get_one(User, "alice").created_at == 1731234567.123456
        assert session.get_one(Location, "parent").name == "Work 🦊"
        assert session.get_one(PrinterDevice, "device").config["text"] == "é 漢字"
        debt = session.get(TapeAllocation, ("batch", "alice"))
        assert debt is not None
        assert debt.cartridge_id == "cartridge" and debt.recipient_id is None
        assert debt.cost_micros == "18714367" and debt.charged_micros == "18000000"
        repayment = session.get(UsageAdjustment, "repayment")
        assert repayment is not None
        assert repayment.recipient_id == "past-owner"
        assert repayment.cartridge_allocations == {"cartridge": "1000000"}
    with pytest.raises(MigrationError, match="contains application data"):
        migrate(source, maria_engine, apply=True, backup_dir=tmp_path / "backups")


def test_copy_failure_rolls_back_and_empty_schema_can_be_retried(
    maria_engine, tmp_path, monkeypatch
):
    import scripts.migrate_database as migration

    source = sqlite_source(tmp_path)
    original = migration.digest
    calls = 0

    def mismatch(rows):
        nonlocal calls
        calls += 1
        count, checksum = original(rows)
        return count, "incorrect" if count and calls % 2 == 0 else checksum

    monkeypatch.setattr(migration, "digest", mismatch)
    with pytest.raises(MigrationError, match="Verification failed"):
        migrate(source, maria_engine, apply=True, backup_dir=tmp_path / "backups")
    with maria_engine.connect() as connection:
        for table in inspect(connection).get_table_names():
            if table != "alembic_version":
                assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM `{table}`").scalar() == 0
        assert connection.exec_driver_sql("SELECT @@FOREIGN_KEY_CHECKS").scalar() == 1
    monkeypatch.setattr(migration, "digest", original)
    assert migrate(source, maria_engine, apply=True, backup_dir=tmp_path / "backups")["users"] == 1


def test_database_backup_restore_and_corruption_guard(maria_engine, tmp_path):
    migrate(
        sqlite_source(tmp_path), maria_engine, apply=True, backup_dir=tmp_path / "sqlite-backups"
    )
    path = tmp_path / "database.json.gz"
    with database_owner(maria_engine, enforce=True), maria_engine.connect() as connection:
        backup(connection, path)
        assert path.stat().st_mode & 0o777 == 0o600
        connection.exec_driver_sql("UPDATE users SET username='changed'")
        connection.exec_driver_sql("ALTER TABLE users ADD COLUMN new_column TEXT")
        connection.commit()
        corrupt = tmp_path / "corrupt.gz"
        with gzip.open(path, "rt") as source, gzip.open(corrupt, "wt") as target:
            target.write(source.read().replace('"fixture-hash"', '"tampered"'))
        with pytest.raises(ValueError, match="checksum"):
            restore(connection, corrupt)
        assert connection.exec_driver_sql("SELECT username FROM users").scalar() == "changed"
        restore(connection, path)
        assert connection.exec_driver_sql("SELECT username FROM users").scalar() == "alice"
        assert connection.exec_driver_sql("SELECT content, source FROM stored_assets").one() == (
            b"\x00\xff\x80image",
            b"\x00original",
        )
        assert "new_column" not in {c["name"] for c in inspect(connection).get_columns("users")}


def test_updater_bridge_holds_database_lock_and_restores_without_exposing_rows(
    maria_engine, tmp_path
):
    from argparse import Namespace
    from pathlib import Path

    from scripts.update import RemoteDatabase

    migrate(
        sqlite_source(tmp_path), maria_engine, apply=True, backup_dir=tmp_path / "sqlite-backups"
    )
    env = {
        **os.environ,
        "LABEL_DATABASE_URL": maria_engine.url.render_as_string(hide_password=False),
    }
    args = Namespace(install_dir=Path(__file__).resolve().parents[1])
    remote = RemoteDatabase(args, env)
    path = tmp_path / "remote-backup.gz"
    try:
        with pytest.raises(RuntimeError, match="Another server"):
            with database_owner(maria_engine):
                pytest.fail("Updater must exclude the server")
        remote.perform("backup", path)
        config = Config("alembic.ini")
        config.attributes.update(
            database_url=env["LABEL_DATABASE_URL"], database_owner=int(remote.owner)
        )
        command.upgrade(config, "head")
        with maria_engine.begin() as connection:
            connection.exec_driver_sql("UPDATE users SET username='changed'")
        remote.perform("restore", path)
    finally:
        remote.close()
    with database_owner(maria_engine), maria_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT username FROM users").scalar() == "alice"
        assert connection.exec_driver_sql("SELECT content, source FROM stored_assets").one() == (
            b"\x00\xff\x80image",
            b"\x00original",
        )


def test_database_ownership_excludes_other_hosts_and_fails_closed_after_loss(maria_engine):
    other = make_engine(maria_engine.url.render_as_string(hide_password=False))
    try:
        with database_owner(maria_engine, enforce=True):
            with pytest.raises(RuntimeError, match="Another server"):
                with database_owner(other):
                    pytest.fail("Two owners")
            with maria_engine.connect() as owner:
                identifier = owner.scalar(
                    text("SELECT IS_USED_LOCK(:name)"), {"name": lock_name(maria_engine)}
                )
            with other.connect() as admin:
                admin.exec_driver_sql(f"KILL {int(identifier)}")
            with pytest.raises(RuntimeError, match="ownership was lost"):
                with maria_engine.connect() as connection:
                    connection.exec_driver_sql("SELECT 1")
    finally:
        other.dispose()


def test_main_server_auth_queue_and_database_assets_use_mariadb(maria_engine, tmp_path):
    upgrade(maria_engine.url.render_as_string(hide_password=False))
    with session_factory(maria_engine).begin() as session:
        session.add(PrinterDevice(id="main", name="Printer", driver="mock", config={}))
        session.add(PrinterState(id=1, printer_id="main"))
    app = create_app(
        Settings(
            database_url=maria_engine.url.render_as_string(hide_password=False),
            data_dir=tmp_path / "state",
        ),
        {"main": MockPrinterBackend()},
        start_worker=False,
        backend_factory=printer_factory,
    )
    with TestClient(app) as client:
        token = (tmp_path / "state/auth-setup-token").read_text().strip()
        response = client.post(
            "/api/auth/setup",
            json={"username": "owner", "password": "fixture-password-long", "setup_token": token},
        )
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        profile = client.post(
            "/api/tape-profiles", json={"name": "Unicode 🦊", "width_mm": 24}
        ).json()
        cartridge = client.post(
            "/api/cartridges",
            json={
                "profile_id": profile["id"],
                "name": "Owner's cartridge",
                "nominal_length_mm": 8000,
            },
        ).json()
        assert (
            client.put(
                "/api/printer/active-tape?printer_id=main",
                json={"cartridge_id": cartridge["id"], "move_location": False},
            ).status_code
            == 200
        )
        job = client.post(
            "/api/jobs",
            json={"tape_profile": profile["id"], "data": {"text": "Hello"}, "copies": 2},
        )
        assert job.status_code == 201, job.text
        assert client.get(f"/api/jobs/{job.json()['id']}").status_code == 200
        started = client.post("/api/queue/print?printer_id=main")
        assert started.status_code == 202, started.text
        app.state.fleet.workers["main"].tick()
        assert client.get(f"/api/jobs/{job.json()['id']}").json()["status"] == "printed"
        assert client.get("/api/batches?requester=local-owner").status_code == 200
        from test_avatars import picture

        from app.render import FONT_DIR

        image = client.post("/api/image-assets", content=picture())
        font = client.post("/api/font-assets", content=(FONT_DIR / "NotoSans.ttf").read_bytes())
        assert image.status_code == font.status_code == 201
        assert client.put("/api/auth/avatar", content=picture()).status_code == 200
        avatar = client.get("/api/auth/avatar").content
        document = {
            "elements": [
                {
                    "id": "image1",
                    "kind": "image",
                    "image_asset": image.json()["id"],
                    "x": 45,
                    "y": 1,
                    "width": 10,
                    "height": 8,
                },
                {
                    "id": "text1",
                    "kind": "text",
                    "font": font.json()["id"],
                    "content": "Database assets",
                    "x": 1,
                    "y": 1,
                    "width": 40,
                    "height": 8,
                },
            ]
        }
        before = client.post("/api/preview", json={"document": document})
        assert before.status_code == 200, before.text
        shutil.rmtree(app.state.settings.state_directory / "cache")
        assert client.post("/api/preview", json={"document": document}).json() == before.json()
        assert client.get("/api/auth/avatar").content == avatar
        assert not (app.state.settings.state_directory / "assets").exists()
        invitation = client.post("/api/admin/registration-codes", json={"name": "Test invitation"})
        assert invitation.status_code == 201, invitation.text
        assert client.post("/api/auth/logout").status_code == 204
        login = client.post(
            "/api/auth/login", json={"username": "owner", "password": "fixture-password-long"}
        )
        assert login.status_code == 200, login.text
    assert not (tmp_path / "state/auth-setup-token").exists()


def test_binary_packet_limit_is_checked_before_restore_changes_tables(maria_engine, tmp_path):
    migrate(
        sqlite_source(tmp_path), maria_engine, apply=True, backup_dir=tmp_path / "source-backups"
    )
    path = tmp_path / "backup.gz"
    with database_owner(maria_engine, enforce=True), maria_engine.connect() as connection:
        backup(connection, path)
        previous = int(
            connection.exec_driver_sql("SELECT @@global.max_allowed_packet").scalar_one()
        )
        connection.exec_driver_sql("SET GLOBAL max_allowed_packet=1024")
    # Session limits are inherited when opening a new connection.
    maria_engine.dispose()
    try:
        with maria_engine.connect() as connection:
            with pytest.raises(ValueError, match="max_allowed_packet"):
                restore(connection, path)
            assert connection.exec_driver_sql("SELECT username FROM users").scalar_one() == "alice"
            assert (
                connection.exec_driver_sql("SELECT content FROM stored_assets").scalar_one()
                == b"\x00\xff\x80image"
            )
    finally:
        with maria_engine.connect() as connection:
            connection.exec_driver_sql(f"SET GLOBAL max_allowed_packet={previous}")
        maria_engine.dispose()
