from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from app_client import TestClient
from mock_backend import MockPrinterBackend

from app.config import Settings
from app.db import make_engine, session_factory
from app.main import create_app
from app.models import PrinterDevice, PrinterState


@pytest.fixture(autouse=True)
def isolated_notification_environment(monkeypatch):
    # Migration tests must never import the developer's live notification channel.
    for name in ("LABEL_NTFY_URL", "LABEL_NTFY_TOPIC", "LABEL_NTFY_TOKEN"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("LABEL_VAPID_SUBJECT", "")
    monkeypatch.delenv("LABEL_VAPID_PRIVATE_KEY_FILE", raising=False)
    monkeypatch.setenv("LABEL_SMTP_SECURITY", "starttls")
    monkeypatch.setenv("LABEL_SMTP_PORT", "587")
    for name in (
        "LABEL_SMTP_HOST",
        "LABEL_SMTP_FROM",
        "LABEL_SMTP_FROM_NAME",
        "LABEL_SMTP_USERNAME",
        "LABEL_SMTP_PASSWORD",
    ):
        monkeypatch.setenv(name, "")


def create_test_app(settings=None, backends=None, start_worker=True, **kwargs):
    from mock_api import router
    from printer_factory import test_printer

    app = create_app(
        settings,
        backends,
        start_worker,
        backend_factory=kwargs.get("backend_factory", test_printer),
    )
    from app.access import LocalOwnerPolicy

    app.state.access_policy = LocalOwnerPolicy()
    from app.identity import LOCAL_OWNER_ID
    from app.models import User

    with app.state.factory.begin() as session:
        if session.get(User, LOCAL_OWNER_ID) is None:
            session.add(
                User(id=LOCAL_OWNER_ID, username="local-test-owner", password_hash="disabled")
            )
    app.include_router(router)
    return app


def seed_test_printer(url: str) -> None:
    engine = make_engine(url)
    with session_factory(engine).begin() as session:
        session.add(PrinterDevice(id="main", name="Mock printer", driver="mock", config={}))
        session.add(PrinterState(id=1, printer_id="main"))
    engine.dispose()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    seed_test_printer(url)
    application = create_test_app(
        Settings(database_url=url), {"main": MockPrinterBackend()}, start_worker=False
    )
    with TestClient(application) as client:
        yield client


def profile(
    client: TestClient,
    name: str = "White",
    threshold: int = 10,
    reminders: bool = False,
    width: float = 24,
) -> dict[str, Any]:
    response = client.post(
        "/api/tape-profiles",
        json={
            "name": name,
            "width_mm": width,
            "auto_print_threshold": threshold,
            "waiting_notification_enabled": reminders,
            "waiting_notification_interval_seconds": 60,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def grant_cartridge(client, cartridge_id, user_id="alice", *permissions):
    from app.models import ResourceGrant

    with client.app.state.factory.begin() as session:
        for permission in permissions or ("view", "use"):
            session.add(
                ResourceGrant(
                    principal_kind="user",
                    principal_id=user_id,
                    scope_kind="cartridge",
                    scope_id=cartridge_id,
                    permission=f"cartridge.{permission}",
                )
            )


def install(client: TestClient, profile_id: str, remaining: float = 8000) -> dict[str, Any]:
    response = client.post(
        "/api/cartridges",
        json={
            "profile_id": profile_id,
            "name": "Cassette 1",
            "nominal_length_mm": 8000,
            "remaining_mm": remaining,
        },
    )
    assert response.status_code == 201, response.text
    cartridge = response.json()
    # Most printing fixtures model shared inventory. Sharing is explicit in 0.13;
    # permission-boundary tests remove or replace these grants as needed.
    from app.models import ResourceGrant

    with client.app.state.factory.begin() as session:
        for permission in ("cartridge.view", "cartridge.use"):
            session.add(
                ResourceGrant(
                    principal_kind="role",
                    principal_id="member",
                    scope_kind="cartridge",
                    scope_id=cartridge["id"],
                    permission=permission,
                )
            )
    response = client.put("/api/printer/active-tape", json={"cartridge_id": cartridge["id"]})
    assert response.status_code == 200, response.text
    return cartridge


def job(client: TestClient, profile_id: str, copies: int = 1) -> dict[str, Any]:
    response = client.post(
        "/api/jobs",
        json={
            "tape_profile": profile_id,
            "copies": copies,
            "data": {"text": "example"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def foundation_session(tmp_path):
    """Isolated storage for the staged resource-access and audit primitives."""
    from app.models import Base

    engine = make_engine(f"sqlite:///{tmp_path / 'foundation.db'}")
    Base.metadata.create_all(engine)
    try:
        with session_factory(engine)() as session:
            yield session
    finally:
        engine.dispose()
