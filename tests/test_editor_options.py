import base64
import io
from dataclasses import replace

import pytest
from conftest import profile
from PIL import Image

from app.render import RenderSpec, render_document
from app.template_schema import TemplateDocument


def document(**options):
    return {
        "elements": [
            {
                "id": "text",
                "kind": "text",
                "x": 2,
                "y": 3,
                "width": 40,
                "height": 16,
                "content": "Padding",
                "font_size": 3,
            }
        ],
        **options,
    }


@pytest.mark.parametrize(
    "align,vertical", [("left", "top"), ("center", "center"), ("right", "bottom")]
)
def test_each_padding_side_reduces_the_alignment_and_fitting_area(align, vertical):
    padded = document()
    padded["elements"][0].update(
        align=align,
        vertical_align=vertical,
        padding_left=2,
        padding_right=4,
        padding_top=1,
        padding_bottom=3,
    )
    reference = document()
    reference["elements"][0].update(
        x=4, y=4, width=34, height=12, align=align, vertical_align=vertical
    )
    actual = render_document(TemplateDocument.model_validate(padded), {}, RenderSpec())
    expected = render_document(TemplateDocument.model_validate(reference), {}, RenderSpec())
    assert actual.image.tobytes() == expected.image.tobytes()


def test_auto_width_includes_padding_and_impossible_padding_is_explicit():
    doc = TemplateDocument.model_validate(document(auto_length=True))
    doc.elements[0].auto_width = True
    base = render_document(doc, {}, RenderSpec())
    doc.elements[0].padding_left, doc.elements[0].padding_right = 2, 4
    padded = render_document(doc, {}, RenderSpec())
    assert padded.document.elements[0].width == pytest.approx(base.document.elements[0].width + 6)
    assert padded.document.length_mm == pytest.approx(base.document.length_mm + 6)
    doc.elements[0].padding_top = doc.elements[0].height
    with pytest.raises(ValueError, match="padding leaves no space"):
        render_document(doc, {}, RenderSpec())


def test_resolution_and_padding_freeze_in_jobs_and_csv_runs(client):
    tape = profile(client)
    doc = document(print_resolution="high")
    doc["elements"][0]["padding_left"] = 2
    saved = client.post("/api/templates", json={"name": "High with padding", "document": doc})
    assert saved.status_code == 201, saved.text
    template = saved.json()
    preview = client.post("/api/preview", json={"template_id": template["id"]}).json()
    assert (preview["pixel_width"], preview["pixel_height"]) == (850, 170)
    job = client.post(
        "/api/jobs", json={"template": template["id"], "tape_profile": tape["id"], "data": {}}
    ).json()
    assert job["template_snapshot"]["render_spec"]["dpi_x"] == 360
    assert job["template_snapshot"]["document"]["elements"][0]["padding_left"] == 2
    prepared = client.post(
        "/api/runs/prepare",
        json={
            "request_key": "resolution-padding",
            "name": "Frozen resolution and padding",
            "template": template["id"],
            "expected_revision": 1,
            "tape_profile": tape["id"],
            "csv_text": "Row\nOne\n",
            "mapping": {},
            "rows": [{"source_row": 2, "copies": 1}],
        },
    )
    assert prepared.status_code == 200, prepared.text
    run_id = prepared.json()["run"]["id"]
    doc["print_resolution"] = "normal"
    doc["elements"][0]["padding_left"] = 0
    assert (
        client.put(
            f"/api/templates/{template['id']}",
            json={
                "name": "Normal without padding",
                "document": doc,
                "expected_revision": 1,
            },
        ).status_code
        == 200
    )
    current = client.post("/api/preview", json={"template_id": template["id"]}).json()
    assert current["pixel_width"] == 425
    frozen = client.get(f"/api/runs/{run_id}/rows/0/preview").json()
    assert frozen["png"] == preview["png"]
    assert Image.open(io.BytesIO(base64.b64decode(frozen["png"].split(",")[1]))).size == (850, 170)
    assert client.post(f"/api/runs/{run_id}/submit").status_code == 200
    old = client.get(f"/api/jobs/{job['id']}").json()
    assert old["template_snapshot"] == job["template_snapshot"]
    run_jobs = [j for j in client.get("/api/jobs").json() if j["run_id"] == run_id]
    assert run_jobs[0]["template_snapshot"]["render_spec"]["dpi_x"] == 360


def test_template_resolution_overrides_default_and_rejects_unsupported_modes(client):
    registry = client.app.state.registry
    device = registry.definition("main")
    registry._definitions["main"] = replace(
        device, capabilities=replace(device.capabilities, dpi_x=360)
    )
    for mode, width in [("printer", 850), ("normal", 425), ("high", 850)]:
        response = client.post("/api/preview", json={"document": document(print_resolution=mode)})
        assert response.status_code == 200, response.text
        assert response.json()["pixel_width"] == width
    registry._definitions["main"] = replace(
        device, capabilities=replace(device.capabilities, resolution_modes=None)
    )
    response = client.post("/api/preview", json={"document": document(print_resolution="high")})
    assert response.status_code == 422
