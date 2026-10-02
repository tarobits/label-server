from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.printer.mock import MockPrinterBackend


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    application = create_app(Settings(database_url=url), MockPrinterBackend(), start_worker=False)
    with TestClient(application) as client:
        yield client


def profile(
    client: TestClient,
    name: str = "White",
    threshold: int = 10,
    reminders: bool = False,
    width: int = 24,
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
