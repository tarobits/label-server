"""Creation is reviewed, constrained, audited, and separate from orphan repair."""

import pytest
from alembic import command
from app_client import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_auth import setup_admin
from test_relationship_migration import database

from app.billing_models import BillingGrant
from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.models import (
    AuditEvent,
    Cartridge,
    Companion,
    CompanionPrinter,
    LabelTemplate,
    Location,
    PrinterDevice,
    PrinterState,
    TapeProfile,
    User,
    UserGroup,
)

CASES = [
    (
        "users",
        "printers.owner_id",
        {"username": "replacement", "password": "replacement-test-password"},
    ),
    ("user_groups", "label_templates.group_id", {"name": "Replacement"}),
    ("locations", "printers.location_id", {"name": "Replacement"}),
    ("tape_profiles", "cartridges.profile_id", {"name": "Replacement", "width_mm": 12}),
    (
        "cartridges",
        "printer_state.active_cartridge_id",
        {
            "name": "Replacement",
            "profile_id": "profile",
            "nominal_length_mm": 8000,
            "remaining_mm": 2000,
        },
    ),
    ("printers", "printer_state.printer_id", {"name": "Replacement", "usb_serial": "REPLACEMENT"}),
    (
        "companions",
        "companion_printers.companion_id",
        {"name": "Replacement", "location_id": "location"},
    ),
    ("billing_accounts", "billing_grants.account_id", {"name": "Replacement"}),
]


@pytest.fixture(params=CASES, ids=[case[0] for case in CASES])
def migration(request, tmp_path):
    kind, key, values = request.param
    url, config = database(tmp_path)
    engine = make_engine(url)
    # Simulate corruption imported before enforcement; never disable FKs in the app.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        with Session(connection) as session:
            printer = PrinterDevice(
                id="printer",
                name="Existing",
                driver="brother-pt-p710bt",
                config={"usb_serial": "EXISTING"},
            )
            session.add_all(
                [
                    printer,
                    Location(id="location", name="Existing location"),
                    TapeProfile(id="profile", name="Existing tape", width_mm=12),
                ]
            )
            session.flush()
            if kind == "users":
                printer.owner_id = "missing"
            elif kind == "locations":
                printer.location_id = "missing"
            elif kind == "user_groups":
                session.add(
                    LabelTemplate(name="Broken", scope="group", group_id="missing", document={})
                )
            elif kind == "tape_profiles":
                session.add(
                    Cartridge(
                        name="Broken",
                        profile_id="missing",
                        nominal_length_mm=8000,
                        remaining_mm=2000,
                    )
                )
            elif kind in {"printers", "cartridges"}:
                session.add(
                    PrinterState(
                        printer_id="missing" if kind == "printers" else "printer",
                        active_cartridge_id="missing" if kind == "cartridges" else None,
                    )
                )
            elif kind == "companions":
                session.add(
                    CompanionPrinter(printer_id="printer", companion_id="missing", local_id="local")
                )
            else:
                session.add(
                    BillingGrant(
                        account_id="missing",
                        principal_kind="role",
                        principal_id="administrator",
                        permission="view",
                        effect="allow",
                    )
                )
            session.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
    engine.dispose()
    command.upgrade(config, "head")
    app = create_app(Settings(database_url=url, check_for_updates=False), start_worker=False)
    with TestClient(app) as client:
        setup_admin(client, tmp_path)
        row = client.get("/api/migration/relationships/rows", params={"key": key}).json()[0]
        yield (
            client,
            {
                "key": key,
                "token": row["token"],
                "kind": kind,
                "values": values,
                "reason": "Verified replacement details",
            },
        )


def test_create_review_confirm_and_assign(migration):
    client, body = migration
    base = "/api/migration/relationships"
    assert (
        client.get(base + "/creation", params={"key": body["key"]}).json()["parent"] == body["kind"]
    )
    assert client.post(base + "/creation", json=body).status_code == 409
    with client.app.state.factory() as session:
        before = session.scalar(text(f"SELECT count(*) FROM {body['kind']}"))
    preview = client.post(base + "/creation/preview", json=body)
    assert preview.status_code == 200, preview.text
    with client.app.state.factory() as session:
        assert session.scalar(text(f"SELECT count(*) FROM {body['kind']}")) == before
    headers = {"X-Access-Confirmation": preview.json()["confirmation_token"]}
    altered = {**body, "reason": "Different reason"}
    assert client.post(base + "/creation", json=altered, headers=headers).status_code == 409
    created = client.post(base + "/creation", json=body, headers=headers)
    assert created.status_code == 201, created.text
    assert client.post(base + "/creation", json=body, headers=headers).status_code == 409
    assert client.get(base).json()["relationships"]  # Creation never silently reassigns.
    with client.app.state.factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "migration.resource_created")
            )
            == 1
        )
        if body["kind"] == "users":
            user = session.get(User, created.json()["id"])
            assert user.role_ids == [] and user.password_hash != body["values"]["password"]
        if body["kind"] == "user_groups":
            assert session.get(UserGroup, created.json()["id"]).members == []
        if body["kind"] == "companions":
            assert session.get(Companion, created.json()["id"]).key_hash is None
    repaired = client.post(
        base + "/repair",
        json={
            "key": body["key"],
            "token": body["token"],
            "target": created.json()["id"],
            "reason": "Assign verified replacement",
        },
    )
    assert repaired.status_code == 200, repaired.text
    assert not client.get(base).json()["relationships"]
    assert client.get("/api/workspace").status_code == 503
    assert not client.app.state.fleet.workers


def test_creation_rejects_injected_fields_and_requires_csrf(migration):
    client, body = migration
    path = "/api/migration/relationships/creation/preview"
    injected = {**body, "values": {**body["values"], "role_ids": ["administrator"]}}
    assert client.post(path, json=injected).status_code == 422
    assert client.post(path, json={**body, "kind": "batches"}).status_code == 422
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post(path, json=body).status_code == 403
    client.headers["X-CSRF-Token"] = csrf


def test_resource_validation_and_stale_reference(migration):
    client, body = migration
    invalid = {
        "users": {"password": "short"},
        "user_groups": {"name": " "},
        "locations": {"name": " "},
        "tape_profiles": {"media_family": "fixed_label"},
        "cartridges": {"remaining_mm": 9000},
        "printers": {"driver": "not-a-driver"},
        "companions": {"location_id": "does-not-exist"},
        "billing_accounts": {"name": " "},
    }
    path = "/api/migration/relationships/creation/preview"
    response = client.post(
        path, json={**body, "values": {**body["values"], **invalid[body["kind"]]}}
    )
    assert response.status_code == 422, response.text
    assert "replacement-test-password" not in response.text
    assert client.post(path, json={**body, "token": "0" * 64}).status_code == 409
