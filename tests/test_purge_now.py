"""Explicit irreversible purge is scoped, authorized and retryable after failure."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select
from test_access_security import accounts as accounts

from app.models import AuditEvent, DeletedContent, LabelTemplate, TemplateRevision, User


def deleted_template(admin, alice, name):
    created = alice.post(
        "/api/templates",
        json={
            "name": name,
            "document": {
                "width_mm": 24,
                "length_mm": 60,
                "fields": [],
                "elements": [
                    {
                        "id": "title",
                        "kind": "text",
                        "x": 2,
                        "y": 2,
                        "width": 40,
                        "height": 12,
                        "content": "Fixture",
                    },
                ],
            },
        },
    )
    assert created.status_code == 201, created.text
    identifier = created.json()["id"]
    response = admin.delete(f"/api/templates/{identifier}/permanent")
    assert response.status_code == 200, response.text
    return identifier


def purge(client, identifier, confirmation=None):
    return client.post(
        f"/api/admin/trash/templates/{identifier}/purge",
        json={"confirmation": identifier if confirmation is None else confirmation},
    )


def test_purge_requires_admin_csrf_origin_and_exact_confirmation(accounts):
    admin, alice, bob = accounts
    identifier = deleted_template(admin, alice, "Delete explicitly")
    assert purge(alice, identifier).status_code == 403
    assert purge(bob, identifier).status_code == 403
    assert purge(admin, identifier, "different-item").status_code == 422
    csrf = admin.headers.pop("X-CSRF-Token")
    assert purge(admin, identifier).status_code == 403
    admin.headers["X-CSRF-Token"] = csrf
    assert (
        admin.post(
            f"/api/admin/trash/templates/{identifier}/purge",
            json={"confirmation": identifier},
            headers={"Origin": "https://other.example"},
        ).status_code
        == 403
    )
    with admin.app.state.factory() as session:
        assert session.get(LabelTemplate, identifier) is not None
        assert session.get(DeletedContent, ("templates", identifier)).purged_at is None
    assert purge(admin, identifier).status_code == 204


def test_purge_does_not_sweep_other_expired_items_and_retries_do_not_duplicate_audit(accounts):
    admin, alice, _ = accounts
    selected = deleted_template(admin, alice, "Selected")
    untouched = deleted_template(admin, alice, "Unrelated expired item")
    with admin.app.state.factory.begin() as session:
        session.get(DeletedContent, ("templates", untouched)).purge_after = time.time() - 1
    assert purge(admin, selected).status_code == 204
    assert purge(admin, selected).status_code == 204
    assert admin.post(f"/api/admin/trash/templates/{selected}/restore").status_code == 409
    with admin.app.state.factory() as session:
        assert session.get(LabelTemplate, selected) is None
        assert (
            session.scalar(select(TemplateRevision).where(TemplateRevision.template_id == selected))
            is None
        )
        assert session.get(LabelTemplate, untouched) is not None
        assert session.get(DeletedContent, ("templates", untouched)).purged_at is None
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(AuditEvent.action == "content.purged")
                ).all()
            )
            == 1
        )


@pytest.mark.parametrize("stage", ["preview-cleanup", "audit-after-delete"])
def test_failed_purge_rolls_back_deadline_and_content_and_releases_transaction(
    accounts, monkeypatch, stage
):
    from app.audit import action_audit  # noqa: F401
    from app.templates import template_previews  # noqa: F401

    admin, alice, _ = accounts
    identifier = deleted_template(admin, alice, "Retry safely")
    with admin.app.state.factory() as session:
        deadline = session.get(DeletedContent, ("templates", identifier)).purge_after
    with monkeypatch.context() as patch:

        def fail(*args, **kwargs):
            if stage == "audit-after-delete":
                assert args[0].get(LabelTemplate, identifier) is None
            raise RuntimeError("injected purge failure")

        if stage == "preview-cleanup":
            patch.setattr(template_previews, "invalidate_deleted_previews", fail)
        else:
            patch.setattr(action_audit, "record_action", fail)
        with pytest.raises(RuntimeError, match="injected purge failure"):
            purge(admin, identifier)
    with admin.app.state.factory() as session:
        item = session.get(DeletedContent, ("templates", identifier))
        assert item.purged_at is None and item.purge_after == deadline
        assert session.get(LabelTemplate, identifier) is not None
    assert purge(admin, identifier).status_code == 204


def test_concurrent_purge_retries_delete_once_and_leave_service_usable(accounts):
    admin, alice, _ = accounts
    identifier = deleted_template(admin, alice, "Concurrent purge")
    barrier = Barrier(2)

    def invoke():
        barrier.wait(timeout=5)
        return purge(admin, identifier)

    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(invoke) for _ in range(2)]
        assert [request.result(timeout=10).status_code for request in requests] == [204, 204]
    with admin.app.state.factory() as session:
        assert session.get(LabelTemplate, identifier) is None
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(AuditEvent.action == "content.purged")
                ).all()
            )
            == 1
        )
    subsequent = deleted_template(admin, alice, "Subsequent valid operation")
    assert purge(admin, subsequent).status_code == 204


def test_account_purge_removes_held_content_without_purging_another_account(accounts):
    from test_auth import change
    from test_deletion import assets

    admin, alice, bob = accounts
    image, font, template, _ = assets(alice)
    other_image, other_font, other_template, _ = assets(bob)
    image_path = admin.app.state.images.path(image["id"])
    font_path = admin.app.state.fonts.path(font["id"])
    assert change(admin, "users", "DELETE", identifier="alice").status_code == 204
    path = "/api/admin/trash/users/alice/purge"
    assert admin.post(path, json={"confirmation": "alice"}).status_code == 204
    with admin.app.state.factory() as session:
        assert session.get(User, "alice") is None
        assert session.get(User, "bob") is not None
        assert session.get(LabelTemplate, template["id"]) is None
        assert session.get(LabelTemplate, other_template["id"]) is not None
        assert all(item.purged_at is not None for item in session.scalars(select(DeletedContent)))
    assert not image_path.exists()
    assert not font_path.exists()
    with pytest.raises(ValueError, match="deleted"):
        admin.app.state.images.path(image["id"])
    assert admin.app.state.images.path(other_image["id"]).exists()
    assert admin.app.state.fonts.path(other_font["id"]).exists()
    assert admin.post(path, json={"confirmation": "alice"}).status_code == 204
