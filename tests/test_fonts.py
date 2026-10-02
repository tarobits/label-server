from pathlib import Path

import pytest
from conftest import install, profile
from fastapi.testclient import TestClient

from app.font_assets import MAX_FONT_BYTES, FontStore

FONT = Path("app/fonts/NotoSans-Bold.ttf")


def test_uploaded_font_is_used_and_survives_hiding_and_store_reload(client: TestClient) -> None:
    uploaded = client.post("/api/font-assets", content=FONT.read_bytes())
    assert uploaded.status_code == 201, uploaded.text
    font = uploaded.json()
    assert client.post("/api/font-assets", content=FONT.read_bytes()).json()["id"] == font["id"]
    assert len(client.get("/api/font-assets").json()) == 1
    doc = {
        "elements": [
            {
                "id": "text",
                "kind": "text",
                "x": 2,
                "y": 2,
                "width": 40,
                "height": 15,
                "content": "Font test",
                "font": font["id"],
                "font_size": 5,
            }
        ]
    }
    preview = client.post("/api/preview", json={"document": doc})
    assert preview.status_code == 200, preview.text
    # The uploaded bold face must produce the same pixels as bundled bold,
    # rather than silently falling back to regular or a system font.
    builtin = {"elements": [{**doc["elements"][0], "font": "Noto Sans", "bold": True}]}
    assert (
        client.post("/api/preview", json={"document": builtin}).json()["png"]
        == preview.json()["png"]
    )
    saved = client.post("/api/templates", json={"name": "Custom font", "document": doc})
    assert saved.status_code == 201, saved.text
    tape = profile(client)
    install(client, tape["id"])
    queued = client.post(
        "/api/jobs", json={"template": saved.json()["id"], "tape_profile": tape["id"], "data": {}}
    )
    assert queued.status_code == 201, queued.text
    assert client.delete(f"/api/font-assets/{font['id']}").json()["archived"]
    store = FontStore(client.app.state.fonts.root)
    assert store.list()[0]["archived"]
    client.app.state.fonts = store
    client.app.state.worker.fonts = store
    assert (
        client.post("/api/preview", json={"document": doc}).json()["png"] == preview.json()["png"]
    )
    assert client.post("/api/queue/print").status_code == 202
    client.app.state.worker.tick()
    assert client.app.state.worker.backend.batches
    assert not client.post(f"/api/font-assets/{font['id']}/restore").json()["archived"]


@pytest.mark.parametrize("data", [b"", b"not a font", b"\x00\x01\x00\x00broken", b"wOFFfake"])
def test_reject_invalid_font_without_creating_assets(client: TestClient, data: bytes) -> None:
    assert client.post("/api/font-assets", content=data).status_code == 422
    assert client.get("/api/font-assets").json() == []


def test_font_limits_and_missing_references(client: TestClient) -> None:
    assert client.post("/api/font-assets", content=b"x" * (MAX_FONT_BYTES + 1)).status_code == 413
    assert client.delete("/api/font-assets/invalid").status_code == 404
    doc = {"elements": [{"id": "t", "kind": "text", "content": "text", "font": "a" * 64}]}
    response = client.post("/api/preview", json={"document": doc})
    assert response.status_code == 422
    assert "missing" in response.text


def test_otf_outlines_render_and_csv_keeps_font_reference(client: TestClient) -> None:
    import io

    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "A"])
    builder.setupCharacterMap({65: "A"})
    builder.setupHorizontalMetrics({".notdef": (600, 0), "A": (600, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Test OTF", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    pen = T2CharStringPen(600, None)
    pen.moveTo((50, 0))
    pen.lineTo((300, 700))
    pen.lineTo((550, 0))
    pen.closePath()
    builder.setupCFF(
        "TestOTF",
        {},
        {".notdef": T2CharStringPen(600, None).getCharString(), "A": pen.getCharString()},
        {},
    )
    output = io.BytesIO()
    builder.save(output)
    response = client.post("/api/font-assets", content=output.getvalue())
    assert response.status_code == 201, response.text
    font = response.json()["id"]
    doc = {
        "fields": [{"name": "text", "label": "Text", "sample": "A"}],
        "elements": [
            {
                "id": "t",
                "kind": "text",
                "x": 2,
                "y": 2,
                "width": 30,
                "height": 15,
                "content": "{{text}}",
                "font": font,
                "font_size": 5,
            }
        ],
    }
    template = client.post("/api/templates", json={"name": "OTF", "document": doc})
    assert template.status_code == 201, template.text
    tape = profile(client)
    response = client.post(
        "/api/runs/prepare",
        json={
            "request_key": "font-run",
            "name": "Fonts",
            "template": template.json()["id"],
            "expected_revision": 1,
            "tape_profile": tape["id"],
            "csv_text": "Text\nA\n",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2, "copies": 1}],
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    endpoint = f"/api/runs/{run['id']}/rows/0/preview"
    preview = client.get(endpoint)
    assert preview.status_code == 200, preview.text
    import base64

    from PIL import Image

    image = Image.open(io.BytesIO(base64.b64decode(preview.json()["png"].split(",")[1])))
    assert image.convert("L").getextrema() == (0, 255)
    client.delete(f"/api/font-assets/{font}")
    assert client.get(endpoint).json() == preview.json()
    assert client.post(f"/api/runs/{run['id']}/submit").status_code == 200
