import base64
import io
import xml.etree.ElementTree as ET
from typing import Any

import pytest
from app_client import TestClient
from conftest import install, profile
from PIL import Image, ImageOps

from app.assets.image_assets import MAX_IMAGE_BYTES, ImageStore
from app.templates.logic_source import compile_source
from app.templates.template_logic import logic_fields, logic_targets
from app.templates.template_schema import Element, TemplateDocument

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><path d="M0 0H50V50H0Z" fill="black"/><rect x="50" width="50" height="50" fill="#999999"/></svg>'


def document(identifier: str, **settings: Any) -> dict[str, Any]:
    return {
        "elements": [
            {
                "id": "art",
                "kind": "image",
                "x": 2,
                "y": 2,
                "width": 30,
                "height": 18,
                "image_asset": identifier,
                **settings,
            }
        ]
    }


def pixels(preview: dict[str, Any]) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(preview["png"].split(",")[1]))).convert("L")


def upload(client: TestClient, data: bytes = SVG) -> str:
    response = client.post("/api/image-assets?name=Artwork", content=data)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.mark.parametrize("x,y", [(2, 2), (70, 5), (2.07, 3.13)])
def test_dither_density_survives_placement_in_print_raster(client, x, y):
    identifier = upload(
        client,
        b'<svg viewBox="0 0 90 40"><rect width="30" height="40" fill="#444444"/>'
        b'<rect x="30" width="30" height="40" fill="#888888"/>'
        b'<rect x="60" width="30" height="40" fill="#cccccc"/></svg>',
    )
    doc = document(identifier, image_mode="dither", x=x, y=y, height=40 / 3)
    doc["length_mm"] = 102
    response = client.post("/api/preview", json={"document": doc})
    assert response.status_code == 200, response.text
    raster = pixels(response.json())
    for index, gray in enumerate((0x44, 0x88, 0xCC)):
        # Sample within each block, excluding boundary/rounding effects.
        box = tuple(
            round(mm * 180 / 25.4) for mm in (x + index * 10 + 1, y + 1, x + index * 10 + 9, y + 12)
        )
        sample = raster.crop(box)
        ink_fraction = sample.histogram()[0] / (sample.width * sample.height)
        assert ink_fraction == pytest.approx(1 - gray / 255, abs=0.04)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_high_resolution_svg_uses_rectangular_pixels_without_letterboxing(client, rotation):
    from app.render import RenderSpec, render_document
    from app.templates.template_schema import TemplateDocument

    identifier = upload(client, b'<svg viewBox="0 0 40 40"><circle cx="20" cy="20" r="16"/></svg>')
    doc = TemplateDocument.model_validate(
        document(
            identifier,
            width=12,
            height=12,
            x=4,
            y=4,
            rotation=rotation,
        )
    )
    output = render_document(doc, {}, RenderSpec(dpi_x=360), images=client.app.state.images)
    bounds = ImageOps.invert(output.image.convert("L")).getbbox()
    assert bounds is not None
    # Circle diameter = 80% of a 12 mm box on both physical axes.
    assert bounds[2] - bounds[0] == pytest.approx(9.6 * 360 / 25.4, abs=2)
    assert bounds[3] - bounds[1] == pytest.approx(9.6 * 180 / 25.4, abs=2)


def test_images_freeze_in_jobs_and_runs_and_match_print_pixels(client: TestClient) -> None:
    identifier = upload(client)
    assert upload(client) == identifier
    doc = document(identifier, image_mode="dither")
    preview = client.post("/api/preview", json={"document": doc})
    assert preview.status_code == 200, preview.text
    image = pixels(preview.json())
    assert image.getextrema() == (0, 255)
    saved = client.post("/api/templates", json={"name": "Artwork", "document": doc}).json()
    tape = profile(client)
    install(client, tape["id"])
    job = client.post(
        "/api/jobs", json={"template": saved["id"], "tape_profile": tape["id"], "data": {}}
    )
    assert job.status_code == 201, job.text
    prepared = client.post(
        "/api/runs/prepare",
        json={
            "request_key": "art-run",
            "name": "Artwork run",
            "template": saved["id"],
            "expected_revision": 1,
            "tape_profile": tape["id"],
            "csv_text": "Row\nOne\n",
            "mapping": {},
            "rows": [{"source_row": 2, "copies": 1}],
        },
    )
    assert prepared.status_code == 200, prepared.text
    run = prepared.json()["run"]
    endpoint = f"/api/runs/{run['id']}/rows/0/preview"
    frozen = client.get(endpoint).json()
    assert client.delete(f"/api/image-assets/{identifier}").json()["archived"]
    doc["elements"][0]["brightness"] = 3
    changed = client.put(
        f"/api/templates/{saved['id']}",
        json={"name": "Changed", "document": doc, "expected_revision": 1},
    )
    assert changed.status_code == 200, changed.text
    # New store instance reads durable database assets; old jobs do not depend on the picker or template.
    store = ImageStore(client.app.state.images.root, client.app.state.factory)
    client.app.state.images = client.app.state.fleet.workers["main"].images = store
    assert client.get(endpoint).json() == frozen
    assert client.post(f"/api/runs/{run['id']}/submit").status_code == 200
    client.post("/api/queue/print")
    client.app.state.fleet.workers["main"].tick()
    labels = client.app.state.fleet.workers["main"].backend.batches[0]
    assert len(labels) == 2
    for label in labels:
        ink = Image.frombytes("1", (label.pixel_width, label.pixel_height), label.raster)
        assert ImageOps.invert(ink.convert("L")).tobytes() == image.tobytes()
    assert not client.post(f"/api/image-assets/{identifier}/restore").json()["archived"]


def test_tonal_controls_aspect_and_tape_colors(client: TestClient) -> None:
    buffer = io.BytesIO()
    Image.linear_gradient("L").resize((100, 50)).save(buffer, "PNG")
    identifier = upload(client, buffer.getvalue())

    def preview(**settings: Any) -> dict[str, Any]:
        response = client.post("/api/preview", json={"document": document(identifier, **settings)})
        assert response.status_code == 200, response.text
        return response.json()

    baseline = preview()
    assert pixels(baseline).tobytes() != pixels(preview(brightness=2)).tobytes()
    assert pixels(baseline).tobytes() != pixels(preview(contrast=0)).tobytes()
    assert pixels(baseline).tobytes() != pixels(preview(image_threshold=220)).tobytes()
    assert pixels(baseline).tobytes() != pixels(preview(image_mode="dither")).tobytes()
    assert pixels(baseline).tobytes() != pixels(preview(preserve_aspect=False)).tobytes()
    colored = client.post(
        "/api/preview",
        json={"document": document(identifier), "foreground": "#ff0000", "background": "#ffff00"},
    ).json()
    assert colored["svg"] == baseline["svg"]
    assert set(
        Image.open(io.BytesIO(base64.b64decode(colored["png"].split(",")[1]))).get_flattened_data()
    ) == {(255, 0, 0), (255, 255, 0)}


@pytest.mark.parametrize("preserve", [True, False])
@pytest.mark.parametrize("scale", [0.1, 0.5, 1])
def test_image_scale_fits_inside_unchanged_box(client, preserve, scale):
    identifier = upload(client, b'<svg viewBox="0 0 100 50"><rect width="100" height="50"/></svg>')
    response = client.post(
        "/api/preview",
        json={
            "document": document(
                identifier,
                preserve_aspect=preserve,
                lock_aspect=False,
                image_scale=scale,
            )
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    artwork = ET.fromstring(result["svg"]).find(".//{http://www.w3.org/2000/svg}image")
    assert artwork is not None
    width, height = 30 * scale, (15 if preserve else 18) * scale
    assert float(artwork.attrib["width"]) == pytest.approx(width)
    assert float(artwork.attrib["height"]) == pytest.approx(height)
    assert float(artwork.attrib["x"]) == pytest.approx((30 - width) / 2)
    assert float(artwork.attrib["y"]) == pytest.approx((18 - height) / 2)
    assert ImageOps.invert(pixels(result)).getbbox() is not None
    element = result["resolved_elements"][0]
    assert (element["width"], element["height"]) == (30, 18)


@pytest.mark.parametrize("scale", [0, 0.09, 1.01, -1])
def test_image_scale_rejects_out_of_range_values(client, scale):
    identifier = upload(client)
    assert (
        client.post(
            "/api/preview", json={"document": document(identifier, image_scale=scale)}
        ).status_code
        == 422
    )


def test_logic_changes_image_and_scale_without_resizing_box(client):
    wide = upload(client)
    tall = upload(client, b'<svg viewBox="0 0 50 100"><rect width="50" height="100"/></svg>')
    raw = document(wide, logic_name="picture", lock_aspect=True)
    raw.update(
        version=2,
        fields=[
            {"name": "photo", "type": "image", "label": "Photo"},
            {"name": "size", "type": "number", "label": "Scale", "default": 1},
        ],
    )
    base = TemplateDocument.model_validate(raw)
    raw["logic"] = compile_source(
        "picture.image_asset = photo; picture.image_scale = size;",
        logic_fields(base),
        logic_targets(base),
    ).model_dump()
    for asset, size in [(wide, 1), (tall, 0.5)]:
        response = client.post(
            "/api/preview",
            json={"document": raw, "data": {"photo": {"image_asset": asset}, "size": size}},
        )
        assert response.status_code == 200, response.text
        item = response.json()["resolved_elements"][0]
        assert (item["width"], item["height"]) == (30, 18)
        assert item["image_scale"] == size
    rejected = client.post(
        "/api/preview", json={"document": raw, "data": {"photo": {"image_asset": tall}, "size": 2}}
    )
    assert rejected.status_code == 422


@pytest.mark.parametrize("preserve", [True, False])
def test_legacy_image_settings_keep_existing_defaults(preserve):
    raw = document("a" * 64, preserve_aspect=preserve)["elements"][0]
    element = Element.model_validate(raw)
    assert element.image_scale == 1
    assert element.lock_aspect is preserve
    assert Element.model_validate({**raw, "lock_aspect": not preserve}).lock_aspect is not preserve


@pytest.mark.parametrize(
    "markup",
    [
        "<script>alert(1)</script>",
        '<image href="file:///etc/passwd"/>',
        '<use href="https://example.org/a.svg"/>',
        '<rect onload="bad()"/>',
        '<rect fill="url(https://example.org/a)"/>',
        "<style>rect{fill:red}</style>",
        "<foreignObject/>",
        "<text>Hello</text>",
        "<filter/>",
        "<svg/>",
    ],
)
def test_reject_active_or_unsupported_svg(client: TestClient, markup: str) -> None:
    response = client.post(
        "/api/image-assets", content=f'<svg viewBox="0 0 10 10">{markup}</svg>'.encode()
    )
    assert response.status_code == 422, response.text
    assert client.get("/api/image-assets").json() == []


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"bad image",
        b'<!DOCTYPE svg [<!ENTITY x "test">]><svg>&x;</svg>',
        b'<svg viewBox="0 0 inf 20"/>',
        b'<svg width="9000" height="2"/>',
    ],
)
def test_invalid_and_unbounded_uploads(client: TestClient, data: bytes) -> None:
    assert client.post("/api/image-assets", content=data).status_code == 422


def test_image_size_limit_and_missing_asset(client: TestClient) -> None:
    assert client.post("/api/image-assets", content=b"x" * (MAX_IMAGE_BYTES + 1)).status_code == 413
    response = client.post("/api/preview", json={"document": document("a" * 64)})
    assert response.status_code == 422 and "missing" in response.text
    assert client.delete("/api/image-assets/invalid").status_code == 404


def test_transparency_stays_tape_colored(client: TestClient) -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buffer, "PNG")
    identifier = upload(client, buffer.getvalue())
    response = client.post("/api/preview", json={"document": document(identifier, brightness=0)})
    assert pixels(response.json()).getextrema() == (255, 255)


def test_transparent_image_does_not_erase_underlying_shapes(client: TestClient) -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(buffer, "PNG")
    identifier = upload(client, buffer.getvalue())
    doc = document(identifier)
    shape = {
        "id": "background",
        "kind": "rectangle",
        "x": 2,
        "y": 2,
        "width": 30,
        "height": 18,
        "filled": True,
    }
    doc["elements"].insert(0, shape)
    baseline = client.post("/api/preview", json={"document": {"elements": [shape]}}).json()
    assert client.post("/api/preview", json={"document": doc}).json()["png"] == baseline["png"]


def test_reject_animated_and_oversized_bitmaps(client: TestClient) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "black").save(
        buffer,
        "GIF",
        save_all=True,
        append_images=[Image.new("RGB", (8, 8), "white")],
        duration=100,
    )
    assert client.post("/api/image-assets", content=buffer.getvalue()).status_code == 422
    buffer = io.BytesIO()
    Image.new("1", (8193, 1)).save(buffer, "PNG")
    assert client.post("/api/image-assets", content=buffer.getvalue()).status_code == 422
