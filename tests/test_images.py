import base64
import io
from typing import Any

import pytest
from conftest import install, profile
from fastapi.testclient import TestClient
from PIL import Image, ImageOps

from app.image_assets import MAX_IMAGE_BYTES, ImageStore

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
    # New store instance reads only durable files; old jobs do not depend on the picker or template.
    store = ImageStore(client.app.state.images.root)
    client.app.state.images = client.app.state.worker.images = store
    assert client.get(endpoint).json() == frozen
    assert client.post(f"/api/runs/{run['id']}/submit").status_code == 200
    client.post("/api/queue/print")
    client.app.state.worker.tick()
    labels = client.app.state.worker.backend.batches[0]
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
