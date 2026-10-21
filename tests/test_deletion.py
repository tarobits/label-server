"""Authoritative deletion, dependency placeholders, and recoverable retention."""

import time

import pytest
from conftest import install, profile
from sqlalchemy import select
from test_access_security import SVG
from test_access_security import accounts as account_fixture
from test_auth import PASSWORD, change, login, preview

from app.auth import hash_password, token_hash
from app.deletion import RETENTION_SECONDS, purge_expired
from app.models import (
    AccessChangeConfirmation,
    AuthSession,
    DeletedContent,
    LabelTemplate,
    RegistrationCode,
    Role,
    TemplateRevision,
    User,
    UserGroup,
)
from app.render import FONT_DIR

accounts = account_fixture


def assets(alice):
    image = alice.post("/api/image-assets?name=Published%20image", content=SVG)
    font = alice.post("/api/font-assets", content=(FONT_DIR / "NotoSans.ttf").read_bytes())
    assert image.status_code == font.status_code == 201
    document = {
        "width_mm": 24,
        "length_mm": 60,
        "fields": [],
        "elements": [
            {
                "id": "picture",
                "kind": "image",
                "x": 2,
                "y": 2,
                "width": 12,
                "height": 12,
                "image_asset": image.json()["id"],
            },
            {
                "id": "caption",
                "kind": "text",
                "x": 16,
                "y": 2,
                "width": 40,
                "height": 12,
                "content": "Hello",
                "font": font.json()["id"],
            },
        ],
    }
    own = alice.post("/api/templates", json={"name": "Published design", "document": document})
    assert own.status_code == 201, own.text
    return image.json(), font.json(), own.json(), document


def test_account_deletion_holds_all_content_and_restoration_recovers_it(accounts):
    admin, alice, bob = accounts
    image, font, own, document = assets(alice)
    group = change(
        admin,
        "groups",
        "POST",
        {
            "name": "Designers",
            "members": [
                {"user_id": "alice", "can_create": True},
                {"user_id": "bob"},
            ],
        },
    ).json()
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "print"}
        ]
        session.get(LabelTemplate, own["id"]).scope = "global"
        session.add(
            RegistrationCode(
                id="used-invitation",
                name="Used",
                token_hash=token_hash("used-code"),
                expires_at=time.time() + 3600,
                redeemed_at=time.time(),
                redeemed_by="alice",
            )
        )
        session.add(
            AccessChangeConfirmation(
                token_hash="alice-receipt",
                actor_id="alice",
                request_hash="old",
                state_hash="old",
                expires_at=time.time() + 60,
            )
        )
    dependent = admin.post("/api/templates", json={"name": "Other design", "document": document})
    assert dependent.status_code == 201, dependent.text
    tape = profile(admin, threshold=1)
    install(admin, tape["id"])
    jobs = []
    for client, template in ((alice, own), (admin, dependent.json())):
        queued = client.post(
            "/api/jobs", json={"template": template["id"], "tape_profile": tape["id"], "data": {}}
        )
        assert queued.status_code == 201, queued.text
        jobs.append(queued.json())

    reviewed = preview(admin, "users", "DELETE", identifier="alice")
    assert reviewed.status_code == 200, reviewed.text
    impact = next(item for item in reviewed.json()["affected_users"] if item["id"] == "alice")
    assert impact["before"] is not None and impact["after"] is None
    assert alice.get("/api/templates").status_code == 200
    assert admin.app.state.images.path(image["id"]).is_file()
    assert (
        admin.delete(
            "/api/admin/users/alice",
            headers={
                "X-Access-Confirmation": reviewed.json()["confirmation_token"],
            },
        ).status_code
        == 204
    )

    assert alice.get("/api/templates").status_code == 401
    assert admin.get(f"/api/templates/{own['id']}").status_code == 410
    assert len(admin.get(f"/api/templates/{dependent.json()['id']}").json()["asset_notices"]) == 2
    assert admin.get("/api/image-assets").json() == []
    assert admin.get("/api/font-assets").json() == []
    assert admin.get(f"/api/image-assets/{image['id']}/preview").status_code == 404
    rendered = admin.post("/api/preview", json={"template_id": dependent.json()["id"]})
    assert rendered.status_code == 200, rendered.text
    assert 'aria-label="Missing image"' in rendered.json()["svg"]
    assert 'aria-label="Missing font"' in rendered.json()["svg"]
    assert len(rendered.json()["warnings"]) == 2
    assert (
        admin.post(
            "/api/jobs",
            json={
                "template": dependent.json()["id"],
                "tape_profile": tape["id"],
                "data": {},
            },
        ).status_code
        == 422
    )
    holds = admin.get("/api/access-holds").json()
    assert {hold["job_id"] for hold in holds} == {job["id"] for job in jobs}
    assert admin.post(f"/api/access-holds/{jobs[1]['id']}/release").status_code == 409
    worker = admin.app.state.fleet.workers["main"]
    worker.tick()
    assert not worker.backend.batches
    assert admin.app.state.images.path(image["id"], include_deleted=True).is_file()
    assert admin.app.state.fonts.path(font["id"], include_deleted=True).is_file()
    with admin.app.state.factory() as session:
        assert session.get(User, "alice").disabled
        assert session.scalar(select(AuthSession).where(AuthSession.user_id == "alice")) is None
        assert session.get(AccessChangeConfirmation, "alice-receipt") is None
        assert session.get(RegistrationCode, "used-invitation").redeemed_at is not None
        assert session.get(UserGroup, group["id"]).members == [
            {
                "user_id": "bob",
                "can_create": False,
                "can_edit_others": False,
                "can_delete_others": False,
            }
        ]
    trash = admin.get("/api/admin/trash").json()
    assert {item["kind"] for item in trash} == {"users", "templates", "images", "fonts"}
    assert all(item["purge_after"] - item["deleted_at"] == RETENTION_SECONDS for item in trash)
    assert admin.post(f"/api/admin/trash/images/{image['id']}/restore").status_code == 409

    change(admin, "users", "RESTORE", identifier="alice")
    assert admin.get("/api/admin/trash").json() == []
    assert admin.get(f"/api/templates/{dependent.json()['id']}").json()["asset_notices"] == []
    assert admin.get(f"/api/templates/{own['id']}").status_code == 200
    assert admin.get(f"/api/image-assets/{image['id']}/preview").status_code == 200
    assert alice.get("/api/templates").status_code == 401  # Old sessions stay revoked.
    assert len(admin.get("/api/access-holds").json()) == 2
    worker.tick()
    assert not worker.backend.batches
    for job in jobs:
        restored = admin.get(f"/api/jobs/{job['id']}").json()
        assert restored["template_snapshot"] == job["template_snapshot"]
        assert admin.post(f"/api/access-holds/{job['id']}/release").status_code == 200
    worker.tick()
    assert len(worker.backend.batches) == 1


@pytest.mark.parametrize("kind", ["images", "fonts", "templates"])
def test_admin_can_delete_referenced_content_and_restore_within_hold(accounts, kind):
    admin, alice, _ = accounts
    image, font, own, _ = assets(alice)
    identifier = {"images": image["id"], "fonts": font["id"], "templates": own["id"]}[kind]
    path = {"images": "image-assets", "fonts": "font-assets", "templates": "templates"}[kind]
    if kind != "images":
        assert alice.delete(f"/api/{path}/{identifier}/permanent").status_code == 403
    else:
        assert alice.delete(f"/api/{path}/{identifier}/permanent").status_code == 409
    deleted = admin.delete(f"/api/{path}/{identifier}/permanent")
    assert deleted.status_code == 200, deleted.text
    assert admin.get("/api/admin/trash").json()[0]["identifier"] == identifier
    assert alice.post(f"/api/admin/trash/{kind}/{identifier}/restore").status_code == 403
    assert admin.post(f"/api/admin/trash/{kind}/{identifier}/restore").status_code == 204
    assert admin.get(f"/api/templates/{own['id']}").json()["asset_notices"] == []


def test_expired_deletions_purge_bytes_and_revisions_but_keep_dependency_notices(accounts):
    admin, alice, _ = accounts
    image, font, own, document = assets(alice)
    dependent = admin.post("/api/templates", json={"name": "Keep dependent", "document": document})
    assert dependent.status_code == 201, dependent.text
    change(admin, "users", "DELETE", identifier="alice")
    with admin.app.state.factory.begin() as session:
        session.add(
            RegistrationCode(
                name="Spent",
                token_hash=token_hash("spent"),
                redeemed_by="alice",
                redeemed_at=time.time(),
                expires_at=time.time() + 3600,
            )
        )
    with admin.app.state.fleet.lock, admin.app.state.factory.begin() as session:
        for item in session.scalars(select(DeletedContent)):
            item.purge_after = time.time() - 1
    assert preview(admin, "users", "RESTORE", identifier="alice").status_code == 409
    with admin.app.state.fleet.lock, admin.app.state.factory.begin() as session:
        purge_expired(session, admin.app.state.fonts, admin.app.state.images, time.time())
        purge_expired(session, admin.app.state.fonts, admin.app.state.images, time.time())
    with admin.app.state.factory() as session:
        assert session.get(User, "alice") is None
        assert session.get(LabelTemplate, own["id"]) is None
        assert (
            session.scalar(
                select(TemplateRevision).where(TemplateRevision.template_id == own["id"])
            )
            is None
        )
        spent = session.scalar(select(RegistrationCode))
        assert spent.redeemed_at is not None and spent.redeemed_by is None
        assert all(item.purged_at is not None for item in session.scalars(select(DeletedContent)))
    assert not list(admin.app.state.images.root.glob(f"{image['id']}.*"))
    assert not list(admin.app.state.fonts.root.glob(f"{font['id']}.*"))
    assert len(admin.get(f"/api/templates/{dependent.json()['id']}").json()["asset_notices"]) == 2
    assert admin.post(f"/api/admin/trash/images/{image['id']}/restore").status_code == 409


def test_deletion_requires_current_admin_preview_and_csrf_and_preserves_last_admin(accounts):
    admin, alice, _ = accounts
    assert alice.delete("/api/admin/users/bob").status_code == 403
    assert (
        admin.delete("/api/admin/users/alice", headers={"X-CSRF-Token": "bad"}).status_code == 403
    )
    assert admin.delete("/api/admin/users/alice").status_code == 409
    assert preview(admin, "users", "DELETE", identifier="administrator").status_code == 409
    reviewed = preview(admin, "users", "DELETE", identifier="alice").json()
    assert (
        admin.delete(
            "/api/admin/users/bob",
            headers={
                "X-Access-Confirmation": reviewed["confirmation_token"],
            },
        ).status_code
        == 409
    )
    with admin.app.state.factory.begin() as session:
        session.get(User, "bob").disabled = True
    assert (
        admin.delete(
            "/api/admin/users/alice",
            headers={
                "X-Access-Confirmation": reviewed["confirmation_token"],
            },
        ).status_code
        == 409
    )


def test_admin_can_delete_self_when_another_enabled_admin_remains(accounts):
    admin, _, bob = accounts
    with admin.app.state.factory.begin() as session:
        session.get(User, "bob").role_ids = ["administrator"]
        session.get(User, "administrator").password_hash = hash_password(PASSWORD)
    change(admin, "users", "DELETE", identifier="administrator")
    assert admin.get("/api/admin/users").status_code == 401
    assert admin.get("/api/auth/session").json()["user"] is None
    change(bob, "users", "RESTORE", identifier="administrator")
    assert login(admin, "administrator")["user"]["is_admin"]


def test_restoring_account_does_not_restore_an_independently_deleted_asset(accounts):
    admin, alice, _ = accounts
    image, font, _, _ = assets(alice)
    assert admin.delete(f"/api/font-assets/{font['id']}/permanent").status_code == 200
    change(admin, "users", "DELETE", identifier="alice")
    change(admin, "users", "RESTORE", identifier="alice")
    assert [item["identifier"] for item in admin.get("/api/admin/trash").json()] == [font["id"]]
    assert admin.app.state.images.path(image["id"]).is_file()
    with pytest.raises(ValueError, match="deleted"):
        admin.app.state.fonts.path(font["id"])


def test_template_can_replace_deleted_assets_without_rewriting_frozen_jobs(accounts):
    admin, alice, _ = accounts
    image, font, own, document = assets(alice)
    tape = profile(admin)
    queued = admin.post(
        "/api/jobs", json={"template": own["id"], "tape_profile": tape["id"], "data": {}}
    )
    assert queued.status_code == 201, queued.text
    for path, identifier in (("image-assets", image["id"]), ("font-assets", font["id"])):
        assert admin.delete(f"/api/{path}/{identifier}/permanent").status_code == 200
    replacement = admin.post("/api/image-assets", content=SVG).json()["id"]
    document["elements"][0]["image_asset"] = replacement
    document["elements"][1]["font"] = "Noto Sans"
    fixed = admin.put(
        f"/api/templates/{own['id']}",
        json={
            "name": own["name"],
            "document": document,
            "expected_revision": own["revision"],
        },
    )
    assert fixed.status_code == 200, fixed.text
    assert admin.get(f"/api/templates/{own['id']}").json()["asset_notices"] == []
    assert (
        admin.post(
            "/api/jobs",
            json={
                "template": own["id"],
                "tape_profile": tape["id"],
                "data": {},
            },
        ).status_code
        == 201
    )
    assert (
        admin.get(f"/api/jobs/{queued.json()['id']}").json()["template_snapshot"]
        == queued.json()["template_snapshot"]
    )
    assert admin.post(f"/api/access-holds/{queued.json()['id']}/release").status_code == 409
