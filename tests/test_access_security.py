"""Adversarial coverage for account boundaries and shared rendering dependencies."""

import secrets
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from alembic import command
from alembic.config import Config
from conftest import profile, seed_test_printer
from fastapi.testclient import TestClient
from mock_backend import MockPrinterBackend
from printer_factory import test_printer as printer_factory
from sqlalchemy import func, select

from app.auth import COOKIE_NAME, token_hash
from app.config import Settings
from app.main import create_app
from app.models import (
    AuthSession,
    LabelCopy,
    LabelTemplate,
    PrinterDevice,
    PrinterGroup,
    PrinterState,
    PrintJob,
    Role,
    User,
    UserGroup,
)
from app.request_models import PrintRequest

SVG = b'<svg viewBox="0 0 20 20"><path d="M2 2H18V18H2Z"/></svg>'


@pytest.fixture
def accounts(tmp_path: Path) -> Iterator[tuple[TestClient, TestClient, TestClient]]:
    url = f"sqlite:///{tmp_path / 'security.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    seed_test_printer(url)
    app = create_app(
        Settings(database_url=url),
        {"main": MockPrinterBackend()},
        start_worker=False,
        backend_factory=printer_factory,
    )

    def account(client: TestClient, username: str, *, admin: bool = False) -> None:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with app.state.factory.begin() as session:
            session.add(
                User(
                    id=username,
                    username=username,
                    password_hash="unused",
                    role_ids=["administrator"] if admin else ["member", f"{username}-access"],
                )
            )
            session.flush()
            session.add(
                AuthSession(
                    token_hash=token_hash(token),
                    user_id=username,
                    csrf_token=csrf,
                    expires_at=time.time() + 3600,
                )
            )
            if not admin:
                session.add(
                    Role(
                        id=f"{username}-access",
                        name=f"{username} access",
                        permissions=[
                            {"kind": "destination", "destination_id": "main", "level": "request"}
                        ],
                    )
                )
        client.cookies.set(COOKIE_NAME, token)
        client.headers["X-CSRF-Token"] = csrf

    with TestClient(app) as admin:
        account(admin, "administrator", admin=True)
        alice, bob = TestClient(app), TestClient(app)
        account(alice, "alice")
        account(bob, "bob")
        with app.state.factory.begin() as session:
            session.scalar(select(LabelTemplate).where(LabelTemplate.id == "text")).scope = "global"
        try:
            yield admin, alice, bob
        finally:
            alice.close()
            bob.close()


def image_document(identifier: str) -> dict:
    return {
        "elements": [
            {
                "id": "image",
                "kind": "image",
                "x": 2,
                "y": 2,
                "width": 12,
                "height": 12,
                "image_asset": identifier,
            }
        ]
    }


def test_upload_deduplication_does_not_transfer_asset_ownership(accounts) -> None:
    admin, alice, bob = accounts
    first = admin.post("/api/image-assets?name=Private", content=SVG)
    second = alice.post("/api/image-assets?name=Alice", content=SVG)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["owner_id"] == "administrator"
    assert second.json()["owner_id"] == "alice"
    assert alice.post("/api/image-assets", content=SVG).json()["id"] == second.json()["id"]
    assert [a["id"] for a in alice.get("/api/image-assets").json()] == [second.json()["id"]]
    assert bob.get("/api/image-assets").json() == []
    private = first.json()["id"]
    for response in (
        bob.get(f"/api/image-assets/{private}/preview"),
        bob.put(f"/api/image-assets/{private}", json={"name": "Stolen"}),
        bob.delete(f"/api/image-assets/{private}"),
        bob.post(f"/api/image-assets/{private}/restore"),
        bob.delete(f"/api/image-assets/{private}/permanent"),
    ):
        assert response.status_code == 403, response.text
    assert admin.get("/api/image-assets").json()[1]["name"] == "Private"


def test_private_assets_cannot_be_extracted_through_rendering(accounts) -> None:
    admin, alice, _ = accounts
    image = admin.post("/api/image-assets", content=SVG).json()["id"]
    font = admin.post(
        "/api/font-assets", content=Path("app/fonts/NotoSans.ttf").read_bytes()
    ).json()["id"]
    documents = [
        image_document(image),
        {
            "elements": [
                {
                    "id": "text",
                    "kind": "text",
                    "x": 2,
                    "y": 2,
                    "width": 30,
                    "height": 12,
                    "font": font,
                    "content": "Private font",
                }
            ]
        },
    ]
    for document in documents:
        preview = alice.post("/api/preview", json={"document": document, "destination_id": "main"})
        assert preview.status_code == 403, preview.text
        saved = alice.post(
            "/api/templates",
            json={"name": "Unauthorized", "document": document, "destination_id": "main"},
        )
        assert saved.status_code == 403, saved.text
    assert alice.get("/api/font-assets").json() == []
    assert alice.delete(f"/api/font-assets/{font}").status_code == 403
    assert alice.post(f"/api/font-assets/{font}/restore").status_code == 403


def test_shared_template_grants_asset_read_but_not_library_control(accounts) -> None:
    admin, alice, bob = accounts
    image = admin.post("/api/image-assets", content=SVG).json()["id"]
    with admin.app.state.factory.begin() as session:
        session.add(
            UserGroup(
                id="designers",
                name="Designers",
                members=[
                    {
                        "user_id": "alice",
                        "can_create": False,
                        "can_edit_others": False,
                        "can_delete_others": False,
                    }
                ],
            )
        )
    response = admin.post(
        "/api/templates",
        json={
            "name": "Group art",
            "scope": "group",
            "group_id": "designers",
            "document": image_document(image),
        },
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    assert alice.get("/api/image-assets").json() == []
    preview = alice.get(f"/api/image-assets/{image}/preview")
    assert preview.status_code == 200, preview.text
    assert "no-store" in preview.headers["cache-control"]
    assert bob.get(f"/api/image-assets/{image}/preview").status_code == 403
    assert alice.put(f"/api/image-assets/{image}", json={"name": "Edited"}).status_code == 403
    assert alice.delete(f"/api/image-assets/{image}/permanent").status_code == 403
    with admin.app.state.factory.begin() as session:
        session.get(UserGroup, "designers").members = []
    assert alice.get(f"/api/image-assets/{image}/preview").status_code == 403
    assert alice.get(f"/api/templates/{saved['id']}").status_code == 403


def test_requests_stay_nonexecutable_until_exactly_once_approval(accounts) -> None:
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    body = {"tape_profile": tape["id"], "data": {"text": "Alice's private label"}, "copies": 3}
    assert alice.post("/api/jobs", json=body).status_code == 403
    submitted = alice.post(
        "/api/requests",
        json={"kind": "job", "input": body},
        headers={"Idempotency-Key": "one-request"},
    )
    assert submitted.status_code == 201, submitted.text
    request = submitted.json()
    retried = alice.post(
        "/api/requests",
        json={"kind": "job", "input": body},
        headers={"Idempotency-Key": "one-request"},
    )
    assert retried.json()["id"] == request["id"]
    with admin.app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(PrintJob)) == 0
        assert session.scalar(select(func.count()).select_from(LabelCopy)) == 0
    assert bob.get("/api/requests").json() == []
    assert bob.get(f"/api/requests/{request['id']}").status_code == 403
    assert bob.get(f"/api/requests/{request['id']}/labels/0/preview").status_code == 403
    assert alice.post(f"/api/requests/{request['id']}/approve").status_code == 403
    assert (
        alice.post(
            f"/api/requests/{request['id']}/reject", json={"reason": "Forged approval"}
        ).status_code
        == 403
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(lambda _: admin.post(f"/api/requests/{request['id']}/approve"), range(2))
        )
    assert all(response.status_code == 200 for response in outcomes)
    assert outcomes[0].json()["job_ids"] == outcomes[1].json()["job_ids"]
    queued = outcomes[0].json()["job_ids"][0]
    assert alice.get(f"/api/jobs/{queued}").status_code == 200
    assert bob.get(f"/api/jobs/{queued}").status_code == 403
    assert bob.get(f"/api/jobs/{queued}/preview").status_code == 403
    assert bob.delete(f"/api/jobs/{queued}").status_code == 403
    copies = alice.get(f"/api/jobs/{queued}").json()["labels"]
    assert bob.post("/api/queue/remove", json={"copy_ids": [copies[0]["id"]]}).status_code == 403
    assert bob.get("/api/jobs").json() == []
    assert bob.get("/api/queue/groups").json() == []
    assert bob.get("/api/workspace").json()["total_queued"] == 0
    with admin.app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(PrintJob)) == 1
        assert session.scalar(select(func.count()).select_from(LabelCopy)) == 3


def test_rejected_requests_never_create_jobs_and_retries_cannot_approve(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin)
    response = alice.post(
        "/api/requests",
        json={"kind": "job", "input": {"tape_profile": tape["id"], "data": {"text": "Rejected"}}},
    )
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    rejected = admin.post(
        f"/api/requests/{identifier}/reject", json={"reason": "Wrong destination"}
    )
    assert rejected.status_code == 200
    again = admin.post(f"/api/requests/{identifier}/reject", json={"reason": "Do not overwrite"})
    assert again.json()["reason"] == "Wrong destination"
    assert admin.post(f"/api/requests/{identifier}/approve").status_code == 409
    with admin.app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(PrintJob)) == 0


def test_csv_request_keys_are_private_and_approval_preserves_all_rows(accounts) -> None:
    admin, alice, bob = accounts
    tape = profile(admin)
    body = {
        "request_key": "same-key",
        "name": "Private CSV",
        "template": "text",
        "expected_revision": 2,
        "tape_profile": tape["id"],
        "csv_text": "Text\nFirst\nSecond\n",
        "mapping": {"text": "Text"},
        "rows": [{"source_row": 2, "copies": 2}, {"source_row": 3, "copies": 1}],
    }
    first = alice.post("/api/runs/prepare", json=body)
    second = bob.post("/api/runs/prepare", json={**body, "csv_text": "Text\nSecret\nOther\n"})
    assert first.status_code == second.status_code == 200
    run = first.json()["run"]
    assert run["id"] != second.json()["run"]["id"]
    assert bob.get(f"/api/runs/{run['id']}").status_code == 403
    assert bob.get(f"/api/runs/{run['id']}/rows/0/preview").status_code == 403
    assert bob.delete(f"/api/runs/{run['id']}").status_code == 403
    assert alice.post(f"/api/runs/{run['id']}/submit").status_code == 403
    result = alice.post("/api/requests", json={"kind": "run", "run_id": run["id"]})
    assert result.status_code == 201, result.text
    identifier = result.json()["id"]
    assert alice.delete(f"/api/runs/{run['id']}").status_code == 409
    assert (
        alice.post("/api/requests", json={"kind": "run", "run_id": run["id"]}).json()["id"]
        == identifier
    )
    approved = admin.post(f"/api/requests/{identifier}/approve")
    assert approved.status_code == 200, approved.text
    assert (
        admin.post(f"/api/requests/{identifier}/approve").json()["job_ids"]
        == approved.json()["job_ids"]
    )
    jobs = [
        alice.get(f"/api/jobs/{identifier}").json() for identifier in approved.json()["job_ids"]
    ]
    assert [job["payload"]["text"] for job in jobs] == ["First", "Second"]
    assert [len(job["labels"]) for job in jobs] == [2, 1]


def test_group_destination_grant_does_not_grant_direct_printer_access(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin)
    with admin.app.state.factory.begin() as session:
        session.add(PrinterDevice(id="second", name="Other printer", driver="mock", config={}))
        session.add(PrinterState(printer_id="second"))
        session.add(PrinterGroup(id="pair", name="Both printers", printer_ids=["main", "second"]))
    admin.app.state.fleet.sync()
    body = {
        "kind": "job",
        "input": {"destination_id": "pair", "tape_profile": tape["id"], "data": {"text": "Pair"}},
    }
    assert {destination["id"] for destination in alice.get("/api/destinations").json()} == {"main"}
    assert alice.get("/api/status?printer_id=second").status_code == 403
    assert alice.post("/api/requests", json=body).status_code == 403
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "pair", "level": "request"}
        ]
    response = alice.post("/api/requests", json=body)
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = []
    assert alice.get(f"/api/requests/{identifier}").status_code == 200
    assert admin.post(f"/api/requests/{identifier}/approve").status_code == 409
    with admin.app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(PrintJob)) == 0


def test_revoking_a_grant_during_rendering_prevents_saved_submission(accounts, monkeypatch) -> None:
    import app.submissions

    admin, alice, _ = accounts
    tape = profile(admin)
    entered, released = Event(), Event()
    original = app.submissions.render_document

    def paused_render(*args, **kwargs):
        entered.set()
        assert released.wait(5), "Test did not release rendering"
        return original(*args, **kwargs)

    monkeypatch.setattr(app.submissions, "render_document", paused_render)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            alice.post,
            "/api/requests",
            json={
                "kind": "job",
                "input": {"tape_profile": tape["id"], "data": {"text": "Revoked"}},
            },
        )
        try:
            assert entered.wait(5), "Request never reached unlocked rendering"
            with admin.app.state.fleet.lock, admin.app.state.factory.begin() as session:
                session.get(Role, "alice-access").permissions = []
        finally:
            released.set()
        response = pending.result(timeout=5)
    assert response.status_code in (403, 409), response.text
    with admin.app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(PrintRequest)) == 0
        assert session.scalar(select(func.count()).select_from(PrintJob)) == 0


def test_pending_image_request_protects_its_frozen_asset_from_deletion(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin)
    identifier = alice.post("/api/image-assets", content=SVG).json()["id"]
    response = alice.post(
        "/api/requests",
        json={"kind": "image", "input": {"image_asset": identifier, "tape_profile": tape["id"]}},
    )
    assert response.status_code == 201, response.text
    assert alice.delete(f"/api/image-assets/{identifier}/permanent").status_code == 409
    assert alice.delete(f"/api/image-assets/{identifier}").status_code == 200
    assert alice.get(f"/api/requests/{response.json()['id']}/labels/0/preview").status_code == 200


def test_request_key_collision_between_labels_and_csv_returns_conflict(accounts) -> None:
    admin, alice, _ = accounts
    tape = profile(admin)
    first = alice.post(
        "/api/requests",
        headers={"Idempotency-Key": "shared-key"},
        json={"kind": "job", "input": {"tape_profile": tape["id"], "data": {"text": "First"}}},
    )
    assert first.status_code == 201, first.text
    prepared = alice.post(
        "/api/runs/prepare",
        json={
            "request_key": "csv-key",
            "name": "CSV",
            "template": "text",
            "expected_revision": 2,
            "tape_profile": tape["id"],
            "csv_text": "Text\nCSV\n",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2, "copies": 1}],
        },
    )
    assert prepared.status_code == 200, prepared.text
    body = {"kind": "run", "run_id": prepared.json()["run"]["id"]}
    collision = alice.post("/api/requests", headers={"Idempotency-Key": "shared-key"}, json=body)
    assert collision.status_code == 409, collision.text
    submitted = alice.post("/api/requests", headers={"Idempotency-Key": "different-key"}, json=body)
    assert submitted.status_code == 201, submitted.text
    assert (
        alice.post(
            "/api/requests", headers={"Idempotency-Key": "shared-key"}, json=body
        ).status_code
        == 409
    )
    assert len(alice.get("/api/requests").json()) == 2


def test_physical_moderator_reviews_group_batch_without_group_access(accounts) -> None:
    admin, alice, bob = accounts
    tape = profile(admin, threshold=1)
    with admin.app.state.factory.begin() as session:
        session.add(PrinterDevice(id="second", name="Other printer", driver="mock", config={}))
        session.add(PrinterState(printer_id="second"))
        session.add(PrinterGroup(id="pair", name="Both printers", printer_ids=["main", "second"]))
        session.add(
            Role(
                id="operator",
                name="Operator",
                permissions=[
                    {"kind": "destination", "destination_id": "main", "level": "moderator"}
                ],
            )
        )
        session.get(User, "alice").role_ids = ["member", "operator"]
        session.get(Role, "bob-access").permissions = [
            {"kind": "destination", "destination_id": "pair", "level": "moderator"}
        ]
    admin.app.state.fleet.sync()
    cartridge = admin.post(
        "/api/cartridges",
        json={"profile_id": tape["id"], "name": "White", "nominal_length_mm": 8000},
    ).json()
    assert (
        admin.put(
            "/api/printer/active-tape?printer_id=main", json={"cartridge_id": cartridge["id"]}
        ).status_code
        == 200
    )
    submitted = admin.post(
        "/api/jobs",
        json={
            "destination_id": "pair",
            "tape_profile": tape["id"],
            "data": {"text": "Restricted group"},
        },
    )
    assert submitted.status_code == 201, submitted.text
    worker = admin.app.state.fleet.workers["main"]
    worker.backend.fail_after = 0
    worker.tick()
    batch = admin.get("/api/batches").json()[0]
    assert batch["state"] == "needs_review"
    body = {"decisions": {submitted.json()["labels"][0]["id"]: "cancelled"}, "consumed_mm": 0}
    assert alice.get(f"/api/batches/{batch['id']}").status_code == 200
    preview = f"/api/batches/{batch['id']}/items/{submitted.json()['labels'][0]['id']}/preview"
    assert alice.get(preview).status_code == 200
    assert bob.get(preview).status_code == 403
    assert bob.get(f"/api/batches/{batch['id']}").status_code == 403
    denied = bob.post(f"/api/batches/{batch['id']}/review", json=body)
    assert denied.status_code == 403, denied.text
    assert admin.get(f"/api/jobs/{submitted.json()['id']}").json()["status"] == "needs_review"
    assert alice.post(f"/api/batches/{batch['id']}/review", json=body).status_code == 200


def test_moderator_cannot_read_or_submit_foreign_drafts_but_can_approve_requests(accounts) -> None:
    admin, alice, bob = accounts
    tape = profile(admin)
    with admin.app.state.factory.begin() as session:
        session.get(Role, "bob-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "moderator"}
        ]
    image = alice.post("/api/image-assets", content=SVG).json()["id"]
    template = alice.post(
        "/api/templates", json={"name": "Private art", "document": image_document(image)}
    )
    assert template.status_code == 201, template.text
    prepared = alice.post(
        "/api/runs/prepare",
        json={
            "request_key": "private-draft",
            "name": "Private CSV",
            "template": template.json()["id"],
            "expected_revision": 1,
            "tape_profile": tape["id"],
            "csv_text": "Row\nOne\n",
            "mapping": {},
            "rows": [{"source_row": 2, "copies": 1}],
        },
    )
    assert prepared.status_code == 200, prepared.text
    run = prepared.json()["run"]["id"]
    assert bob.get("/api/runs").json() == []
    assert bob.get(f"/api/runs/{run}").status_code == 403
    assert bob.get(f"/api/runs/{run}/rows/0/preview").status_code == 403
    assert bob.delete(f"/api/runs/{run}").status_code == 403
    assert bob.post(f"/api/runs/{run}/submit").status_code == 403
    assert bob.get(f"/api/image-assets/{image}/preview").status_code == 403
    submitted = alice.post("/api/requests", json={"kind": "run", "run_id": run})
    assert submitted.status_code == 201, submitted.text
    identifier = submitted.json()["id"]
    assert bob.get(f"/api/requests/{identifier}/labels/0/preview").status_code == 200
    approved = bob.post(f"/api/requests/{identifier}/approve")
    assert approved.status_code == 200, approved.text
    assert bob.get(f"/api/runs/{run}").status_code == 200
