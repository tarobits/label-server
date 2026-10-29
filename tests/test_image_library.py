import io

import pytest
from conftest import profile
from PIL import Image
from test_access import Policy
from test_images import SVG, document, upload

from app.access import Action
from app.image_assets import ImageStore
from app.models import LabelTemplate, PrintJob, PrintRun, TemplateRevision


@pytest.mark.parametrize("kind", ["svg", "bitmap"])
def test_library_preview_is_bounded_png_with_transparency_and_original_aspect(client, kind):
    if kind == "svg":
        data = b'<svg viewBox="0 0 800 200"><rect width="400" height="200" fill="red"/></svg>'
    else:
        output = io.BytesIO()
        source = Image.new("RGBA", (800, 200))
        source.paste((255, 0, 0, 255), (0, 0, 400, 200))
        source.save(output, "PNG")
        data = output.getvalue()
    identifier = upload(client, data)
    for size, bounds in [("thumbnail", (240, 180)), ("large", (960, 720))]:
        url = f"/api/image-assets/{identifier}/preview?size={size}"
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        image = Image.open(io.BytesIO(response.content))
        assert image.width <= bounds[0] and image.height <= bounds[1]
        assert image.width / image.height == 4
        assert image.getpixel((0, 0)) == (255, 0, 0, 255)
        assert image.getpixel((image.width - 1, 0))[3] == 0
        assert client.get(url).content == response.content
    assert client.get(f"/api/image-assets/{identifier}/preview?size=huge").status_code == 422
    assert client.get("/api/image-assets/invalid/preview").status_code == 404


def test_rename_is_persistent_without_changing_artwork_or_content_identity(client):
    identifier = upload(client)
    store = client.app.state.images
    original = store.path(identifier).read_bytes()
    response = client.put(f"/api/image-assets/{identifier}", json={"name": "  New name  "})
    assert response.status_code == 200
    assert response.json()["name"] == "New name"
    assert response.json()["id"] == identifier
    assert ImageStore(store.root).metadata(identifier)["name"] == "New name"
    assert store.path(identifier).read_bytes() == original
    assert upload(client) == identifier
    assert store.metadata(identifier)["name"] == "New name"
    for name in ["", "  ", "x" * 121]:
        assert client.put(f"/api/image-assets/{identifier}", json={"name": name}).status_code == 422
    assert client.put("/api/image-assets/missing", json={"name": "Valid"}).status_code == 404


def test_unused_image_deletion_holds_files_and_reupload_gets_a_new_identity(client):
    identifier = upload(client)
    assert client.get(f"/api/image-assets/{identifier}/preview").status_code == 200
    assert client.get(f"/api/image-assets/{identifier}/preview?size=large").status_code == 200
    response = client.delete(f"/api/image-assets/{identifier}/permanent")
    assert response.json() == {"deleted": True}
    assert client.get("/api/image-assets").json() == []
    assert list(client.app.state.images.root.glob(f"{identifier}.*"))
    assert client.get(f"/api/image-assets/{identifier}/preview").status_code == 404
    assert client.post(f"/api/image-assets/{identifier}/restore").status_code == 404
    replacement = upload(client, SVG)
    assert replacement != identifier
    assert client.get(f"/api/image-assets/{replacement}/preview").status_code == 200


@pytest.mark.parametrize("reference", ["template", "revision", "job", "run"])
def test_admin_can_delete_each_kind_of_saved_reference_including_history(client, reference):
    identifier = upload(client)
    doc = document(identifier)
    tape = profile(client)
    with client.app.state.factory.begin() as session:
        if reference == "template":
            session.add(LabelTemplate(name="Archived", archived=True, document=doc))
        elif reference == "revision":
            template = LabelTemplate(name="Now empty", document={"elements": []}, revision=2)
            session.add(template)
            session.flush()
            session.add(
                TemplateRevision(template_id=template.id, revision=1, name="Old", document=doc)
            )
        elif reference == "job":
            session.add(
                PrintJob(
                    profile_id=tape["id"],
                    template_id="image",
                    template_snapshot={"document": doc},
                    payload={},
                    width_mm=24,
                    length_mm=60,
                    copies=1,
                )
            )
        else:
            session.add(
                PrintRun(
                    request_key="frozen",
                    request_hash="hash",
                    name="Frozen run",
                    profile_id=tape["id"],
                    manifest={"rows": [{"template_snapshot": {"document": doc}}]},
                )
            )
    assert client.delete(f"/api/image-assets/{identifier}").json()["archived"]
    assert client.get(f"/api/image-assets/{identifier}/preview").status_code == 200
    response = client.delete(f"/api/image-assets/{identifier}/permanent")
    assert response.status_code == 200
    assert client.app.state.images.path(identifier, include_deleted=True).is_file()
    assert client.get(f"/api/image-assets/{identifier}/preview").status_code == 404


def test_library_changes_and_previews_respect_access_policy(client):
    identifier = upload(client)
    client.app.state.access_policy = Policy(Action.WRITE)
    assert client.put(f"/api/image-assets/{identifier}", json={"name": "Denied"}).status_code == 403
    client.app.state.access_policy = Policy(Action.DELETE)
    assert client.delete(f"/api/image-assets/{identifier}/permanent").status_code == 403
    client.app.state.access_policy = Policy(Action.READ)
    assert client.get(f"/api/image-assets/{identifier}/preview").status_code == 403
