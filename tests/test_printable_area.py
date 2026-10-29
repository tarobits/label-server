"""The editor's visible band and the printer's accepted raster must agree."""

import base64
import io

import pytest
from conftest import profile
from PIL import Image, ImageOps

from app.models import LabelCopy, PrintJob
from app.printer.base import RenderedLabel
from app.printer.brother import PRINT_PINS, capabilities, encode_raster
from app.render import RenderSpec, render_document, render_job
from app.template_schema import TemplateDocument


@pytest.mark.parametrize("width", PRINT_PINS)
@pytest.mark.parametrize("dpi_x", [180, 360])
@pytest.mark.parametrize("length", [10, 60, 299.99])
def test_full_bleed_artwork_clips_to_exact_device_rows(width, dpi_x, length):
    document = TemplateDocument.model_validate(
        {
            "width_mm": width,
            "length_mm": length,
            "out_of_bounds": "clip",
            "elements": [
                dict(id="edge", kind="rectangle", x=0, y=0, width=length, height=width, filled=True)
            ],
        }
    )
    output = render_document(
        document,
        {},
        RenderSpec(
            dpi_x=dpi_x,
            printable_widths_mm=capabilities().printable_widths_mm,
            stretch_canvas=True,
            align_printable_band=True,
        ),
    )
    ink = ImageOps.invert(output.image.convert("L")).convert("1")
    top = (ink.height - PRINT_PINS[width]) // 2
    assert ink.getbbox()[1::2] == (top, top + PRINT_PINS[width])
    assert encode_raster(
        RenderedLabel("edge", width, length, *ink.size, ink.tobytes(), dpi_x=dpi_x)
    )
    assert any("clipped" in warning for warning in output.warnings)


def test_12mm_blank_text_bounds_do_not_report_clipped_ink():
    spec = RenderSpec(
        printable_widths_mm=capabilities().printable_widths_mm,
        stretch_canvas=True,
        align_printable_band=True,
    )
    doc = TemplateDocument.model_validate(
        {
            "width_mm": 12,
            "out_of_bounds": "clip",
            "elements": [
                dict(id="caption", kind="text", x=1, y=0.9, width=30, height=11, content="Caption"),
                dict(id="line", kind="line", x=1, y=0.5, width=30, height=2),
            ],
        }
    )
    assert render_document(doc, {}, spec).warnings == []
    doc.elements[0].y = -1
    assert any("caption is clipped" in w for w in render_document(doc, {}, spec).warnings)
    doc.elements[0].y = -20
    assert any("caption is omitted" in w for w in render_document(doc, {}, spec).warnings)


def test_saved_template_changed_from_24_to_12_uses_correct_band(client):
    from dataclasses import replace

    registry = client.app.state.registry
    registry._definitions["main"] = replace(
        registry.definition("main"), capabilities=capabilities()
    )
    tape = profile(client, width=12)
    document = {
        "width_mm": 24,
        "out_of_bounds": "clip",
        "elements": [dict(id="edge", kind="rectangle", x=0, y=0, width=40, height=24, filled=True)],
    }
    saved = client.post("/api/templates", json={"name": "Narrowed", "document": document}).json()
    document["width_mm"] = 12
    edited = client.put(
        f"/api/templates/{saved['id']}",
        json={"name": "Narrowed", "document": document, "expected_revision": 1},
    )
    assert edited.status_code == 200, edited.text
    preview = client.post("/api/preview", json={"template_id": saved["id"]}).json()
    response = client.post(
        "/api/jobs", json={"template": saved["id"], "tape_profile": tape["id"], "data": {}}
    )
    assert response.status_code == 201, response.text
    queued = response.json()
    assert queued["template_snapshot"]["render_spec"]["align_printable_band"]
    with client.app.state.factory() as session:
        rendered = render_job(session.get(PrintJob, queued["id"]), LabelCopy(id="test"))
    assert encode_raster(rendered)
    image = Image.open(io.BytesIO(base64.b64decode(preview["png"].split(",")[1]))).convert("L")
    ink = Image.frombytes("1", (rendered.pixel_width, rendered.pixel_height), rendered.raster)
    assert ImageOps.invert(ink.convert("L")).tobytes() == image.tobytes()


def test_legacy_render_spec_preserves_original_band():
    document = TemplateDocument.model_validate(
        {
            "width_mm": 12,
            "out_of_bounds": "clip",
            "elements": [
                dict(id="edge", kind="rectangle", x=0, y=0, width=60, height=12, filled=True)
            ],
        }
    )
    output = render_document(
        document,
        {},
        RenderSpec(stretch_canvas=True, printable_widths_mm=capabilities().printable_widths_mm),
    )
    ink = ImageOps.invert(output.image.convert("L")).convert("1")
    assert ink.getbbox()[1::2] == (8, 78)


@pytest.mark.parametrize("width", PRINT_PINS)
@pytest.mark.parametrize("image", [False, True])
def test_generated_text_and_image_jobs_fit_the_same_band(client, width, image):
    from dataclasses import replace

    registry = client.app.state.registry
    registry._definitions["main"] = replace(
        registry.definition("main"), capabilities=capabilities()
    )
    tape = profile(client, width=width)
    body = {"tape_profile": tape["id"], "data": {"text": "Test"}}
    path = "/api/jobs"
    if image:
        asset = client.post(
            "/api/image-assets",
            content=b'<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>',
        ).json()
        body = {"tape_profile": tape["id"], "image_asset": asset["id"]}
        path = "/api/image-jobs"
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    with client.app.state.factory() as session:
        label = render_job(
            session.get(PrintJob, response.json()["id"]),
            LabelCopy(id="test"),
            images=client.app.state.images,
        )
    assert encode_raster(label)
