"""Human corrections preserve settlement and keep photo evidence permission scoped."""

import base64
import io
from uuid import uuid4

import pytest
from conftest import install, profile
from PIL import Image
from sqlalchemy import func, select
from test_access_security import accounts as accounts
from test_granular_printer_permissions import set_permissions
from test_retry_funding import body as retry_body
from test_retry_funding import interrupted
from test_review_cartridge import interrupted as uncertain_batch

from app.models import Base, BatchReview, Cartridge, LabelCopy, Notification, State


def photo():
    stream = io.BytesIO()
    picture = Image.new("RGB", (32, 16), "red")
    exif = Image.Exif()
    exif[0x010E] = "private camera metadata"
    picture.save(stream, "JPEG", exif=exif)
    return base64.b64encode(stream.getvalue()).decode()


def report(copy_id, **values):
    return {"request_id": str(uuid4()), "copy_ids": [copy_id], "reason": "Tape ran out", **values}


def test_misprint_preserves_settlement_and_requires_start_permission_for_retry(accounts):
    admin, alice, bob = accounts
    cartridge, original, batch, _, _ = interrupted(accounts)
    copy_id = original["labels"][0]["id"]
    path = f"/api/batches/{batch['id']}"
    before = admin.get(path).json()
    charges = alice.get("/api/accounts").json()["charges"]
    with admin.app.state.factory() as session:
        remaining = session.get(Cartridge, cartridge["id"]).remaining_mm
    payload = report(copy_id, evidence_photo=photo())
    # Activity access alone cannot correct the outcome.
    assert bob.post(path + "/misprints", json=payload).status_code == 403
    set_permissions(admin, "bob", "view", "view_activity", "review")
    response = bob.post(path + "/misprints", json=payload)
    assert response.status_code == 200, response.text
    assert bob.post(path + "/misprints", json=payload).status_code == 200
    assert bob.post(path + "/misprints", json={**payload, "reason": "Different"}).status_code == 409
    after = admin.get(path).json()
    assert after["items"][0]["outcome"] == "failed"
    for key in ("consumed_mm", "consumption_source", "finished_at", "print_plan"):
        assert after[key] == before[key]
    assert alice.get("/api/accounts").json()["charges"] == charges
    with admin.app.state.factory() as session:
        assert session.get(Cartridge, cartridge["id"]).remaining_mm == remaining
        assert session.get(LabelCopy, copy_id).state == State.FAILED
        assert (
            session.scalar(
                select(func.count()).select_from(BatchReview).where(BatchReview.kind == "misprint")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.title == "Misprint reported")
            )
            == 1
        )
    assert bob.post(path + "/retry-offers", json=retry_body([copy_id])).status_code == 403
    set_permissions(admin, "bob", "view", "view_activity", "review", "start_any")
    offered = bob.post(path + "/retry-offers", json=retry_body([copy_id]))
    assert offered.status_code == 201, offered.text
    assert offered.json()[0]["status"] == "pending"
    assert offered.json()[0]["job_id"] is None
    assert alice.get("/api/accounts").json()["charges"] == charges


def test_evidence_is_sanitized_and_follows_current_batch_access(accounts):
    admin, _, bob = accounts
    _, original, batch, _, _ = interrupted(accounts)
    path = f"/api/batches/{batch['id']}"
    payload = report(original["labels"][0]["id"], evidence_photo=photo())
    assert admin.post(path + "/misprints", json=payload).status_code == 200
    record = admin.get(path).json()["reviews"][-1]
    assert "photo" not in record and "evidence_photo" not in record
    image = bob.get(record["photo_url"])
    assert image.status_code == 200
    assert image.headers["cache-control"] == "private, no-store"
    with Image.open(io.BytesIO(image.content)) as decoded:
        assert decoded.format == "JPEG" and decoded.size == (32, 16)
        assert not decoded.getexif()
    set_permissions(admin, "bob", "view", "review")
    assert bob.get(record["photo_url"]).status_code == 403
    assert admin.get(record["photo_url"].replace(batch["id"], "nonexistent")).status_code == 404


@pytest.mark.parametrize(
    "policy,attached,expected",
    [
        ("optional", False, 200),
        ("optional", True, 200),
        ("required", False, 422),
        ("required", True, 200),
        ("disabled", False, 200),
        ("disabled", True, 422),
    ],
)
@pytest.mark.parametrize("kind", ["review", "misprint"])
def test_policy_is_enforced_atomically_for_both_review_paths(
    accounts, policy, attached, expected, kind
):
    admin, _, _ = accounts
    if kind == "misprint":
        _, original, batch, _, _ = interrupted(accounts)
        payload = report(original["labels"][0]["id"])
        suffix = "/misprints"
    else:
        tape = profile(admin, threshold=1)
        install(admin, tape["id"])
        batch, payload = uncertain_batch(admin, tape)
        payload["request_id"] = str(uuid4())
        suffix = "/review"
    setting = admin.put(
        "/api/admin/settings",
        json={"registration_code_required": True, "batch_review_evidence": policy},
    )
    assert setting.status_code == 200, setting.text
    if attached:
        payload["evidence_photo"] = photo()
    path = f"/api/batches/{batch['id']}"
    before = admin.get(path).json()
    result = admin.post(path + suffix, json=payload)
    assert result.status_code == expected, result.text
    after = admin.get(path).json()
    if expected == 422:
        assert after == before
    else:
        assert len(after["reviews"]) == len(before["reviews"]) + 1
        assert admin.post(path + suffix, json=payload).status_code == 200
        assert len(admin.get(path).json()["reviews"]) == len(after["reviews"])


def test_invalid_evidence_and_copy_selection_do_not_change_outcomes(accounts):
    admin, _, _ = accounts
    _, original, batch, failed, _ = interrupted(accounts)
    copy_id = original["labels"][0]["id"]
    path = f"/api/batches/{batch['id']}"
    before = admin.get(path).json()
    for payload, status in (
        (report(copy_id, evidence_photo="not base64"), 422),
        (report(copy_id, evidence_photo=base64.b64encode(b"not an image").decode()), 422),
        (report(copy_id, copy_ids=[copy_id, copy_id]), 422),
        (report(copy_id, copy_ids=["foreign-copy"]), 404),
        (report(copy_id, copy_ids=failed), 409),
        (report(copy_id, reason="   "), 422),
    ):
        assert admin.post(path + "/misprints", json=payload).status_code == status
        assert admin.get(path).json() == before


def test_settings_policy_preserved_for_older_clients_and_admin_only(accounts):
    admin, _, bob = accounts
    assert admin.get("/api/admin/settings").json()["batch_review_evidence"] == "optional"
    assert (
        bob.put(
            "/api/admin/settings",
            json={"registration_code_required": True, "batch_review_evidence": "disabled"},
        ).status_code
        == 403
    )
    assert (
        admin.put(
            "/api/admin/settings",
            json={"registration_code_required": True, "batch_review_evidence": "required"},
        ).status_code
        == 200
    )
    response = admin.put("/api/admin/settings", json={"registration_code_required": True})
    assert response.json()["batch_review_evidence"] == "required"
    assert (
        admin.put(
            "/api/admin/settings",
            json={"registration_code_required": True, "batch_review_evidence": "unknown"},
        ).status_code
        == 422
    )


def test_photo_limits_and_normalization(client):
    from fastapi import HTTPException

    from app.printing.batch_reviews import normalize_photo

    with client.app.state.factory() as session:
        for size, format in [((8193, 1), "PNG"), ((8, 8), "GIF")]:
            stream = io.BytesIO()
            Image.new("RGB", size, "red").save(stream, format)
            with pytest.raises(HTTPException) as error:
                normalize_photo(session, base64.b64encode(stream.getvalue()).decode())
            assert error.value.status_code == 422
        with pytest.raises(HTTPException):
            normalize_photo(session, base64.b64encode(b"x" * 5_000_001).decode())
        stream = io.BytesIO()
        Image.new("RGBA", (3000, 1500), (255, 0, 0, 0)).save(stream, "PNG")
        result = normalize_photo(session, base64.b64encode(stream.getvalue()).decode())
        assert result is not None
        with Image.open(io.BytesIO(base64.b64decode(result))) as decoded:
            assert decoded.size == (2048, 1024)
            assert decoded.mode == "RGB"
            assert decoded.getpixel((0, 0)) == (255, 255, 255)


def test_evidence_retention_blocks_destructive_downgrade(accounts):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateTable

    from scripts.database_maintenance import encode

    admin, _, _ = accounts
    _, original, batch, _, _ = interrupted(accounts)
    payload = report(original["labels"][0]["id"], evidence_photo=photo())
    assert admin.post(f"/api/batches/{batch['id']}/misprints", json=payload).status_code == 200
    with admin.app.state.factory() as session:
        connection = session.connection()
        url = str(connection.engine.url)
        row = connection.execute(
            text("SELECT * FROM batch_reviews WHERE id=:id"), {"id": payload["request_id"]}
        ).one()
        # Native backup records can serialize the evidence without a binary codec.
        assert encode({"row": list(row)})
    assert "LONGTEXT" in str(
        CreateTable(Base.metadata.tables["batch_reviews"]).compile(dialect=dialect())
    )
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    with pytest.raises(RuntimeError, match="audit evidence"):
        command.downgrade(config, "141415b69cb2")
    # Newer migrations may already have downgraded before the evidence guard
    # stops the operation. Restore the current schema before using its API.
    command.upgrade(config, "head")
    assert admin.get(f"/api/batches/{batch['id']}").json()["reviews"][-1]["photo_url"]


def test_large_uncertain_batch_review_keeps_complete_evidence_record(client):
    from conftest import job

    tape = profile(client, threshold=1)
    install(client, tape["id"])
    job(client, tape["id"], copies=1000)
    job(client, tape["id"], copies=1)
    worker = client.app.state.fleet.workers["main"]
    worker.backend.fail_after = 0
    worker.tick()
    batch = client.get("/api/batches").json()[0]
    path = f"/api/batches/{batch['id']}"
    items = client.get(path).json()["items"]
    assert len(items) == 1001
    response = client.post(
        path + "/review",
        json={
            "decisions": {item["copy_id"]: "failed" for item in items},
            "consumed_mm": 50,
            "evidence_photo": photo(),
        },
    )
    assert response.status_code == 200, response.text
    assert len(client.get(path).json()["reviews"][0]["decisions"]) == 1001
