import base64
import io

import pytest
from conftest import profile
from fastapi.testclient import TestClient
from PIL import Image, ImageOps

from app.models import LabelCopy, PrintJob
from app.render import RenderSpec, render_document, render_job
from app.template_schema import TemplateDocument


def test_clipping_preserves_source_but_excludes_ink_outside_printable_area(
    client: TestClient,
) -> None:
    doc = {
        "length_mm": 30,
        "elements": [
            {
                "id": "partial",
                "kind": "rectangle",
                "x": 0,
                "y": 0,
                "width": 10,
                "height": 10,
                "filled": True,
            },
            {
                "id": "hidden",
                "kind": "rectangle",
                "x": 35,
                "y": 2,
                "width": 5,
                "height": 5,
                "filled": True,
            },
        ],
    }
    assert client.post("/api/preview", json={"document": doc}).status_code == 422
    doc["out_of_bounds"] = "clip"
    response = client.post("/api/preview", json={"document": doc})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert any("partial is clipped" in w for w in preview["warnings"])
    assert any("hidden is omitted" in w for w in preview["warnings"])
    image = Image.open(io.BytesIO(base64.b64decode(preview["png"].split(",")[1]))).convert("L")
    assert image.getpixel((2, 2)) == 255
    assert image.getpixel((20, 20)) == 0
    saved = client.post("/api/templates", json={"name": "Clipped", "document": doc}).json()
    assert len(saved["document"]["elements"]) == 2
    tape = profile(client)
    queued = client.post(
        "/api/jobs", json={"template": saved["id"], "tape_profile": tape["id"], "data": {}}
    )
    assert queued.status_code == 201, queued.text
    job = PrintJob(
        **{k: queued.json()[k] for k in ["template_snapshot", "width_mm", "length_mm", "payload"]}
    )
    rendered = render_job(job, LabelCopy(id="test"))
    raster = Image.frombytes("1", (rendered.pixel_width, rendered.pixel_height), rendered.raster)
    assert ImageOps.invert(raster.convert("L")).tobytes() == image.tobytes()


def test_auto_length_resolves_values_and_freezes_each_job(client: TestClient) -> None:
    doc = {
        "length_mm": 60,
        "auto_length": True,
        "fields": [{"name": "text", "label": "Text", "sample": "Sample"}],
        "elements": [
            {
                "id": "text",
                "kind": "text",
                "x": 2,
                "y": 2,
                "width": 30,
                "height": 20,
                "content": "{{text}}",
                "auto_width": True,
            }
        ],
    }
    saved = client.post("/api/templates", json={"name": "Fitted", "document": doc}).json()
    tape = profile(client)
    lengths = []
    for text in ["A", "A longer label value"]:
        data = {"text": text}
        preview = client.post("/api/preview", json={"document": doc, "data": data}).json()
        response = client.post(
            "/api/jobs", json={"template": saved["id"], "tape_profile": tape["id"], "data": data}
        )
        assert response.status_code == 201, response.text
        queued = response.json()
        assert queued["length_mm"] == preview["length_mm"]
        assert queued["width_mm"] == 24
        frozen = queued["template_snapshot"]["document"]
        assert not frozen["auto_length"]
        assert not frozen["elements"][0]["auto_width"]
        assert frozen["length_mm"] == preview["length_mm"]
        reproduced = client.post("/api/preview", json={"document": frozen, "data": data}).json()
        assert reproduced["png"] == preview["png"]
        lengths.append(queued["length_mm"])
    assert lengths[0] == 10
    assert lengths[1] > lengths[0]
    original = client.get(f"/api/templates/{saved['id']}").json()["document"]
    assert original["auto_length"] and original["length_mm"] == 60
    assert original["elements"][0]["width"] == 30


@pytest.mark.parametrize("natural_length", [9.5, 9.999, 10, 10.5])
@pytest.mark.parametrize("automatic", [False, True])
def test_only_automatic_lengths_below_ten_mm_warn(natural_length, automatic):
    document = TemplateDocument.model_validate(
        {
            "length_mm": 10,
            "auto_length": automatic,
            "out_of_bounds": "clip",
            "elements": [
                {
                    "id": "line",
                    "kind": "line",
                    "x": 1,
                    "y": 5,
                    "width": natural_length - 2,
                    "height": 1,
                }
            ],
        }
    )
    output = render_document(document, {}, RenderSpec())
    minimum_warnings = [
        warning for warning in output.warnings if "10 mm template minimum" in warning
    ]
    assert bool(minimum_warnings) == (automatic and natural_length < 10)
    assert output.document.length_mm == (max(10, natural_length) if automatic else 10)


def test_auto_length_rotation_limits_and_fixed_media() -> None:
    doc = TemplateDocument.model_validate(
        {
            "auto_length": True,
            "elements": [
                {
                    "id": "rotated",
                    "kind": "rectangle",
                    "x": 10,
                    "y": 5,
                    "width": 4,
                    "height": 10,
                    "rotation": 90,
                }
            ],
        }
    )
    assert render_document(doc, {}, RenderSpec()).document.length_mm == 18
    assert doc.length_mm == 60
    with pytest.raises(ValueError, match="continuous media"):
        render_document(doc, {}, RenderSpec(media_kind="fixed_label"))
    doc.elements[0].x = 299
    doc.out_of_bounds = "clip"
    with pytest.raises(ValueError, match="300 mm"):
        render_document(doc, {}, RenderSpec())


def test_auto_length_precedes_clipping_and_manual_length_stays_fixed() -> None:
    doc = TemplateDocument.model_validate(
        {
            "length_mm": 10,
            "auto_length": True,
            "out_of_bounds": "clip",
            "elements": [
                {"id": "shape", "kind": "rectangle", "x": 20, "y": 22, "width": 10, "height": 5}
            ],
        }
    )
    output = render_document(doc, {}, RenderSpec())
    assert output.document.length_mm == 31
    assert "clipped" in output.warnings[0]
    doc.auto_length = False
    output = render_document(doc, {}, RenderSpec())
    assert output.document.length_mm == 10
    assert "omitted" in output.warnings[0]
    doc.out_of_bounds = "error"
    with pytest.raises(ValueError, match="outside"):
        render_document(doc, {}, RenderSpec())
