"""Inventory removal preserves accounting and cannot interrupt physical printing."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from conftest import install, job, profile
from sqlalchemy import create_engine, select, text
from test_access_security import accounts as account_fixture
from test_cost_estimates import preview

from app.models import Batch, Cartridge, FlushRequest, PrinterState, Role, State

accounts = account_fixture


def spare(client, tape, **values):
    response = client.post(
        "/api/cartridges",
        json={
            "name": "Spare",
            "profile_id": tape["id"],
            "nominal_length_mm": 8000,
            "price_minor": 2000,
            **values,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def record(client, identifier):
    return next(
        row
        for row in client.get("/api/cartridges?include_archived=true").json()
        if row["id"] == identifier
    )


def test_archive_hides_available_stock_and_quotes_until_restored(client):
    tape = profile(client)
    cartridge = spare(client, tape)
    identifier = cartridge["id"]
    assert preview(client, tape)["cost_estimate"]["quotes"]
    assert client.delete(f"/api/cartridges/{identifier}").status_code == 200
    assert client.get("/api/cartridges").json() == []
    assert record(client, identifier)["archived"]
    assert preview(client, tape)["cost_estimate"]["reason"] == "cartridge"
    assert (
        client.put("/api/printer/active-tape", json={"cartridge_id": identifier}).status_code == 409
    )
    assert (
        client.put(f"/api/cartridges/{identifier}/price", json={"price_minor": 1000}).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/cartridges/{identifier}/remaining", json={"remaining_mm": 1000}
        ).status_code
        == 409
    )
    assert client.delete(f"/api/cartridges/{identifier}").status_code == 200  # Idempotent.
    assert client.post(f"/api/cartridges/{identifier}/restore").status_code == 200
    assert not record(client, identifier)["archived"]
    assert client.get("/api/cartridges").json()[0]["id"] == identifier
    assert preview(client, tape)["cost_estimate"]["quotes"]
    assert (
        client.put("/api/printer/active-tape", json={"cartridge_id": identifier}).status_code == 200
    )


@pytest.mark.parametrize("archived", [False, True])
def test_unused_cartridges_can_be_permanently_deleted(client, archived):
    cartridge = spare(client, profile(client))
    identifier = cartridge["id"]
    if archived:
        client.delete(f"/api/cartridges/{identifier}")
    assert client.delete(f"/api/cartridges/{identifier}/permanent").json() == {"deleted": True}
    with client.app.state.factory() as session:
        assert session.get(Cartridge, identifier) is None
        assert list(session.execute(text("PRAGMA foreign_key_check"))) == []
    assert client.get("/api/cartridges?include_archived=true").json() == []
    assert client.post(f"/api/cartridges/{identifier}/restore").status_code == 404


def test_used_cartridge_can_be_renamed_and_archived_without_losing_usage(client):
    tape = profile(client, threshold=1)
    cartridge = install(client, tape["id"])
    identifier = cartridge["id"]
    client.put(f"/api/cartridges/{identifier}/price", json={"price_minor": 2000})
    job(client, tape["id"])
    client.app.state.fleet.workers["main"].tick()
    before = client.get("/api/usage").json()
    attempt = client.get("/api/batches").json()[0]
    assert client.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code == 200
    assert (
        client.put(f"/api/cartridges/{identifier}", json={"name": "  Finished roll  "}).status_code
        == 200
    )
    assert record(client, identifier)["name"] == "Finished roll"
    assert client.delete(f"/api/cartridges/{identifier}").status_code == 200
    assert record(client, identifier)["delete_blocked_reason"]
    assert client.delete(f"/api/cartridges/{identifier}/permanent").status_code == 409
    assert (
        client.put(f"/api/cartridges/{identifier}", json={"name": "Archive name"}).status_code
        == 200
    )
    after = client.get("/api/usage", params={"cartridge_id": identifier}).json()
    assert after["accounts"] == before["accounts"] and after["users"] == before["users"]
    assert after["entries"][0]["cartridge_id"] == identifier
    assert after["entries"][0]["cartridge_name"] == "Archive name"
    assert client.get(f"/api/batches/{attempt['id']}").json()["cartridge_id"] == identifier


@pytest.mark.parametrize("blocker", ["installed", "printing", "review", "flush", "uncertain"])
def test_archive_and_delete_refuse_in_use_cartridges_without_changing_state(client, blocker):
    tape = profile(client)
    cartridge = spare(client, tape)
    identifier = cartridge["id"]
    with client.app.state.factory.begin() as session:
        if blocker == "installed":
            session.scalar(select(PrinterState)).active_cartridge_id = identifier
        elif blocker in ("printing", "review"):
            session.add(
                Batch(
                    id="in-progress",
                    printer_id="main",
                    cartridge_id=identifier,
                    state=State.PRINTING if blocker == "printing" else State.NEEDS_REVIEW,
                    estimated_mm=100,
                )
            )
        elif blocker == "flush":
            session.add(
                FlushRequest(
                    printer_id="main",
                    destination_id="main",
                    cartridge_id=identifier,
                    copy_ids=["reserved-copy"],
                )
            )
        else:
            session.get(Cartridge, identifier).consumption_uncertain = True
    saved = record(client, identifier)
    assert saved["archive_blocked_reason"] and saved["delete_blocked_reason"]
    for suffix in ("", "/permanent"):
        assert client.delete(f"/api/cartridges/{identifier}{suffix}").status_code == 409
    assert record(client, identifier) == saved
    # Renaming is metadata only, even while a cartridge is in use.
    assert (
        client.put(f"/api/cartridges/{identifier}", json={"name": "Renamed safely"}).status_code
        == 200
    )


def test_completed_queue_history_blocks_permanent_deletion_but_not_archive(client):
    cartridge = spare(client, profile(client))
    with client.app.state.factory.begin() as session:
        session.add(
            FlushRequest(
                printer_id="main",
                destination_id="main",
                cartridge_id=cartridge["id"],
                copy_ids=[],
                completed=True,
            )
        )
    assert client.delete(f"/api/cartridges/{cartridge['id']}").status_code == 200
    assert client.delete(f"/api/cartridges/{cartridge['id']}/permanent").status_code == 409


@pytest.mark.parametrize("name", ["", "   ", "x" * 101, None])
def test_name_validation_is_atomic(client, name):
    cartridge = spare(client, profile(client))
    path = f"/api/cartridges/{cartridge['id']}"
    assert client.put(path, json={"name": name}).status_code == 422
    assert record(client, cartridge["id"])["name"] == "Spare"
    assert client.put(path, json={"name": "Spoof", "remaining_mm": 0}).status_code == 422


def test_inventory_rights_do_not_bypass_installation_locks_or_reveal_printer_identity(accounts):
    admin, alice, bob = accounts
    tape = profile(admin)
    cartridge = install(admin, tape["id"])
    identifier = cartridge["id"]
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "application", "permission": "inventory.manage"}
        ]
        session.get(Role, "bob-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "full"}
        ]
    for path, method, body in [
        (f"/api/cartridges/{identifier}", "PUT", {"name": "Name"}),
        (f"/api/cartridges/{identifier}", "DELETE", None),
        (f"/api/cartridges/{identifier}/restore", "POST", None),
        (f"/api/cartridges/{identifier}/permanent", "DELETE", None),
    ]:
        assert bob.request(method, path, json=body).status_code == 403
    assert alice.delete(f"/api/cartridges/{identifier}").status_code == 409
    assert "main" not in record(alice, identifier)["archive_blocked_reason"]
    assert (
        alice.put(f"/api/cartridges/{identifier}", json={"name": "Inventory name"}).status_code
        == 200
    )
    assert admin.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code == 200
    assert alice.delete(f"/api/cartridges/{identifier}").status_code == 200
    assert alice.post(f"/api/cartridges/{identifier}/restore").status_code == 200
    assert (
        alice.delete(
            f"/api/cartridges/{identifier}/permanent", headers={"X-CSRF-Token": "invalid"}
        ).status_code
        == 403
    )
    assert alice.delete(f"/api/cartridges/{identifier}/permanent").status_code == 200


@pytest.mark.parametrize("action", ["archive", "delete"])
def test_install_and_removal_are_serialized(client, action):
    cartridge = spare(client, profile(client))
    identifier = cartridge["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        installation = pool.submit(
            client.put, "/api/printer/active-tape", json={"cartridge_id": identifier}
        )
        removal = pool.submit(
            client.delete,
            f"/api/cartridges/{identifier}{'/permanent' if action == 'delete' else ''}",
        )
        results = installation.result().status_code, removal.result().status_code
    assert (
        results in [(200, 409), (409, 200)]
        if action == "archive"
        else results in [(200, 409), (404, 200)]
    )
    with client.app.state.factory() as session:
        installed = session.scalar(select(PrinterState)).active_cartridge_id
        stored = session.get(Cartridge, identifier)
        assert not installed or stored is not None and not stored.archived


def test_cartridge_migration_preserves_existing_inventory(tmp_path):
    url = f"sqlite:///{tmp_path / 'cartridge-upgrade.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "f83a6c9d102e")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tape_profiles (id, name, width_mm, foreground, background, auto_print_threshold, waiting_notification_enabled, waiting_notification_interval_seconds, reminder_silenced, reminder_episode, reminder_active) VALUES ('tape', 'White', 24, '#000000', '#ffffff', 10, 0, 86400, 0, 0, 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO cartridges (id, profile_id, name, nominal_length_mm, remaining_mm, consumption_uncertain, price_minor, currency) VALUES ('saved', 'tape', 'Saved cartridge', 8000, 2345, 0, 1234, 'EUR')"
            )
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        row = (
            connection.execute(text("SELECT * FROM cartridges WHERE id = 'saved'")).mappings().one()
        )
        assert row["archived"] == 0 and row["remaining_mm"] == 2345 and row["price_minor"] == 1234
    command.downgrade(config, "f83a6c9d102e")
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
