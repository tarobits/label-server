from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from conftest import create_test_app as create_app
from conftest import install, job, profile
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.access import Action, Actor, Resource
from app.identity import DEFAULT_PRINTER_ID, LOCAL_OWNER_ID
from app.models import LabelTemplate, Notification, PrintJob, PrintRun
from app.notifications import RoutedNotificationSender


class Policy:
    def __init__(self, denied: Action | None = None):
        self.denied = denied
        self.calls: list[tuple[Actor, Action, Resource]] = []

    def allows(self, actor: Actor, action: Action, resource: Resource) -> bool:
        self.calls.append((actor, action, resource))
        return action != self.denied


def test_client_cannot_choose_actor_or_unknown_destination(client: TestClient) -> None:
    policy = Policy()
    client.app.state.access_policy = policy
    tape = profile(client)
    response = client.post(
        "/api/jobs",
        headers={"X-User": "other", "Authorization": "Bearer invented"},
        json={"tape_profile": tape["id"], "data": {"text": "Owned"}},
    )
    assert response.status_code == 201, response.text
    assert response.json()["owner_id"] == LOCAL_OWNER_ID
    assert response.json()["destination_id"] == DEFAULT_PRINTER_ID
    assert {call[0].id for call in policy.calls} == {LOCAL_OWNER_ID}
    assert any(call[2].kind == "template" for call in policy.calls)
    assert (
        client.post(
            "/api/jobs",
            json={
                "tape_profile": tape["id"],
                "data": {"text": "Owned"},
                "destination_id": "another",
            },
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "path,body,action",
    [
        ("/api/tape-profiles", {"name": "Denied", "width_mm": 24}, Action.WRITE),
        ("/api/templates", {"name": "Denied", "document": {}}, Action.WRITE),
        ("/api/runs/prepare", {}, Action.SUBMIT),
    ],
)
def test_mutation_policy_prevents_unauthorized_changes(
    client: TestClient, path: str, body: dict[str, Any], action: Action
) -> None:
    client.app.state.access_policy = Policy(action)
    assert client.post(path, json=body).status_code == 403
    assert client.get("/api/tape-profiles").json() == []
    assert client.get("/api/runs").json() == []
    assert len(client.get("/api/templates").json()) == 1


def test_policy_covers_asset_uploads_reads_and_printing(client: TestClient) -> None:
    client.app.state.access_policy = Policy(Action.WRITE)
    for kind in ("font", "image"):
        assert client.post(f"/api/{kind}-assets", content=b"invalid").status_code == 403
        assert client.get(f"/api/{kind}-assets").json() == []
    tape = profile_after_policy_reset(client)
    install(client, tape["id"])
    client.app.state.access_policy = Policy(Action.SUBMIT)
    assert (
        client.post(
            "/api/jobs", json={"tape_profile": tape["id"], "data": {"text": "Denied"}}
        ).status_code
        == 403
    )
    assert client.get("/api/jobs").json() == []
    client.app.state.access_policy = Policy(Action.PRINT)
    assert client.post("/api/queue/print").status_code == 403
    client.app.state.access_policy = Policy(Action.READ)
    for endpoint in (
        "/api/status",
        "/api/templates",
        "/api/runs",
        "/api/image-assets",
        "/api/font-assets",
    ):
        assert client.get(endpoint).status_code == 403


def profile_after_policy_reset(client: TestClient) -> dict[str, Any]:
    client.app.state.access_policy = Policy()
    return profile(client)


def test_other_destination_is_never_printed_by_local_worker(client: TestClient) -> None:
    tape = profile(client, threshold=1)
    install(client, tape["id"])
    queued = job(client, tape["id"])
    with client.app.state.factory.begin() as session:
        session.get(PrintJob, queued["id"]).destination_id = "future-printer"
    client.app.state.fleet.workers["main"].tick()
    assert not client.app.state.fleet.workers["main"].backend.batches
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"


def test_notification_routing_does_not_fall_back_to_another_recipient() -> None:
    class Sender:
        def __init__(self) -> None:
            self.sent: list[Notification] = []

        def send(self, notice: Notification) -> None:
            self.sent.append(notice)

    sender = Sender()
    router = RoutedNotificationSender({LOCAL_OWNER_ID: sender})
    notice = Notification(recipient_id=LOCAL_OWNER_ID)
    router.send(notice)
    with pytest.raises(ValueError, match="recipient"):
        router.send(Notification(recipient_id="another-owner"))
    assert sender.sent == [notice]


def test_access_migration_backfills_without_changing_frozen_data(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("LABEL_PRINTER_BACKEND", "brother-pt-p710bt")
    tape = profile(client)
    queued = job(client, tape["id"])
    prepared = client.post(
        "/api/runs/prepare",
        json={
            "request_key": "migration-run",
            "name": "Migration",
            "template": "text",
            "expected_revision": 2,
            "tape_profile": tape["id"],
            "csv_text": "Text\nFrozen\n",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2, "copies": 1}],
        },
    ).json()["run"]
    with client.app.state.factory.begin() as session:
        session.add(Notification(title="Notice", message="Frozen", path="/"))
        manifest = session.get(PrintRun, prepared["id"]).manifest
    settings = client.app.state.settings
    client.__exit__(None, None, None)
    config = Config("alembic.ini")
    config.attributes["database_url"] = settings.database_url
    command.downgrade(config, "b130a210da02")
    command.upgrade(config, "head")
    command.check(config)
    with TestClient(create_app(settings, start_worker=False)) as restarted:
        restored = restarted.get(f"/api/jobs/{queued['id']}").json()
        assert restored["owner_id"] == LOCAL_OWNER_ID
        assert restored["destination_id"] == DEFAULT_PRINTER_ID
        assert restored["template_snapshot"] == queued["template_snapshot"]
        assert restored["labels"] == queued["labels"]
        with restarted.app.state.factory() as session:
            assert session.get(LabelTemplate, "text").scope == "global"
            assert session.get(LabelTemplate, "text").owner_id == LOCAL_OWNER_ID
            run = session.get(PrintRun, prepared["id"])
            assert run.owner_id == LOCAL_OWNER_ID and run.destination_id == DEFAULT_PRINTER_ID
            assert run.manifest == manifest
            assert session.scalar(select(Notification)).recipient_id == LOCAL_OWNER_ID
        response = restarted.post(f"/api/runs/{prepared['id']}/submit")
        assert response.status_code == 200, response.text
        assert response.json()["jobs"][0]["owner_id"] == LOCAL_OWNER_ID


def test_csv_submission_checks_saved_destination_before_creating_jobs(client: TestClient) -> None:
    tape = profile(client)
    response = client.post(
        "/api/runs/prepare",
        json={
            "request_key": "restricted-run",
            "name": "Restricted",
            "template": "text",
            "expected_revision": 2,
            "tape_profile": tape["id"],
            "csv_text": "Text\nFrozen\n",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2, "copies": 1}],
        },
    )
    assert response.status_code == 200, response.text
    identifier = response.json()["run"]["id"]
    with client.app.state.factory.begin() as session:
        session.get(PrintRun, identifier).destination_id = "future-printer"
    assert client.post(f"/api/runs/{identifier}/submit").status_code == 404
    assert client.get("/api/jobs").json() == []
    assert client.get(f"/api/runs/{identifier}").json()["submitted_at"] is None
