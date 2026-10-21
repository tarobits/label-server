"""Saved preview tape and durable, authorized WebP template thumbnails."""

import base64
import io
import time

from conftest import install
from PIL import Image
from sqlalchemy import select
from test_access_security import accounts as accounts

from app.deletion import purge_expired
from app.models import DeletedContent
from app.template_previews import TemplatePreviews


def design(tape=None, image=None):
    element = {
        "id": "art",
        "kind": "image" if image else "text",
        "x": 2,
        "y": 2,
        "width": 40,
        "height": 12,
    }
    if image:
        element["image_asset"] = image
    else:
        element["content"] = "Saved preview"
    return {
        "width_mm": 24,
        "length_mm": 60,
        "fields": [],
        "elements": [element],
        "preview_tape": tape,
    }


TAPE = {"id": "yellow", "name": "Black on yellow", "foreground": "#000000", "background": "#ffe100"}


def create(client, document=None, name="Saved colors"):
    response = client.post(
        "/api/templates", json={"name": name, "document": document or design(TAPE)}
    )
    assert response.status_code == 201, response.text
    return response.json()


def png_corner(response):
    content = base64.b64decode(response["png"].split(",", 1)[1])
    return Image.open(io.BytesIO(content)).convert("RGB").getpixel((0, 0))


def test_tape_snapshot_is_saved_in_revisions_but_printing_can_choose_another_profile(client):
    template = create(client)
    assert client.get(f"/api/templates/{template['id']}").json()["document"]["preview_tape"] == TAPE
    revisions = client.get(f"/api/templates/{template['id']}/revisions").json()
    assert revisions[0]["document"]["preview_tape"] == TAPE
    preview = client.post("/api/preview", json={"template_id": template["id"]})
    assert preview.status_code == 200, preview.text
    assert png_corner(preview.json()) == (255, 225, 0)
    other = client.post(
        "/api/tape-profiles",
        json={
            "name": "Blue on white",
            "width_mm": 24,
            "foreground": "#0000ff",
            "background": "#ffffff",
            "auto_print_threshold": 1,
        },
    ).json()
    queued = client.post(
        "/api/jobs",
        json={
            "template": template["id"],
            "tape_profile": other["id"],
            "data": {},
        },
    )
    assert queued.status_code == 201, queued.text
    assert queued.json()["profile_id"] == other["id"]
    install(client, other["id"])
    worker = client.app.state.fleet.workers["main"]
    worker.tick()
    assert len(worker.backend.batches) == 1
    assert client.get(f"/api/jobs/{queued.json()['id']}").json()["status"] == "printed"
    actual = client.post(
        "/api/preview",
        json={
            "template_id": template["id"],
            "foreground": other["foreground"],
            "background": other["background"],
        },
    )
    assert png_corner(actual.json()) == (255, 255, 255)
    duplicate = create(client, template["document"], "Duplicated")
    assert duplicate["document"]["preview_tape"] == TAPE


def test_webp_is_generated_once_and_survives_store_recreation_until_template_changes(
    client, monkeypatch
):
    from app import template_previews

    calls = []
    original = template_previews.render_document

    def render(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(template_previews, "render_document", render)
    template = create(client)
    url = f"/api/templates/{template['id']}/preview.webp"
    first = client.get(url)
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "image/webp"
    assert first.headers["cache-control"] == "private, no-store"
    image = Image.open(io.BytesIO(first.content))
    assert image.format == "WEBP"
    assert image.convert("RGB").getpixel((0, 0)) == (255, 225, 0)
    root = client.app.state.template_previews.root
    saved_file = next(root.glob("*.webp"))
    modified = saved_file.stat().st_mtime_ns
    client.app.state.template_previews = TemplatePreviews(root)
    assert client.get(url).content == first.content
    assert client.get(url).content == first.content
    assert saved_file.stat().st_mtime_ns == modified
    assert len(calls) == 1
    updated = client.put(
        f"/api/templates/{template['id']}",
        json={
            "name": "Changed",
            "document": design({**TAPE, "background": "#ffffff"}),
            "expected_revision": template["revision"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert not saved_file.exists()
    changed = client.get(url)
    assert changed.content != first.content
    assert len(calls) == 2
    assert len(list(root.glob("*.webp"))) == 1


def test_legacy_templates_get_a_cached_black_on_white_thumbnail(client):
    template = create(client, design())
    response = client.get(f"/api/templates/{template['id']}/preview.webp")
    assert response.status_code == 200, response.text
    assert Image.open(io.BytesIO(response.content)).convert("RGB").getpixel((0, 0)) == (
        255,
        255,
        255,
    )


def test_deleted_dependencies_replace_cached_content_and_purge_derived_images(client):
    svg = b'<svg viewBox="0 0 20 20"><path d="M0 0H20V20H0Z"/></svg>'
    uploaded = client.post("/api/image-assets", content=svg).json()
    template = create(client, design(TAPE, uploaded["id"]))
    url = f"/api/templates/{template['id']}/preview.webp"
    first = client.get(url)
    assert first.status_code == 200, first.text
    assert client.delete(f"/api/image-assets/{uploaded['id']}/permanent").status_code == 200
    placeholder = client.get(url)
    assert placeholder.status_code == 200
    assert placeholder.content != first.content
    assert client.post(f"/api/admin/trash/images/{uploaded['id']}/restore").status_code == 204
    assert client.get(url).content == first.content
    assert client.delete(f"/api/image-assets/{uploaded['id']}/permanent").status_code == 200
    with client.app.state.factory.begin() as session:
        item = session.scalar(select(DeletedContent).where(DeletedContent.kind == "images"))
        item.purge_after = time.time() - 1
        purge_expired(session, client.app.state.fonts, client.app.state.images, time.time())
    assert not list(client.app.state.template_previews.root.glob("*.webp"))


def test_cached_thumbnail_rechecks_template_access(accounts):
    admin, alice, _ = accounts
    template = create(admin)
    url = f"/api/templates/{template['id']}/preview.webp"
    assert admin.get(url).status_code == 200
    assert alice.get(url).status_code == 403
    assert admin.delete(f"/api/templates/{template['id']}/permanent").status_code == 200
    assert admin.get(url).status_code == 410
