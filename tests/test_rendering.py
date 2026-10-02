import base64
import io
from typing import Any

import pytest
import zxingcpp
from conftest import install, profile
from fastapi.testclient import TestClient
from PIL import Image, ImageOps

from app.models import LabelCopy, PrintJob
from app.render import render_job


def asset_document() -> dict[str, Any]:
    return {
        "version": 1,
        "width_mm": 24,
        "length_mm": 60,
        "fields": [
            {"name": "name", "label": "Asset name", "required": True, "sample": "ASSET-42"},
            {
                "name": "url",
                "label": "Asset URL",
                "required": True,
                "sample": "https://example.org/42",
            },
        ],
        "elements": [
            {
                "id": "qr",
                "kind": "qr",
                "x": 2,
                "y": 2,
                "width": 20,
                "height": 20,
                "content": "{{url}}",
            },
            {
                "id": "name",
                "kind": "text",
                "x": 24,
                "y": 2,
                "width": 34,
                "height": 20,
                "content": "{{name}}",
                "font_size": 3,
            },
        ],
    }


def test_qr_preview_matches_queued_raster_and_revision_is_frozen(client: TestClient) -> None:
    doc = asset_document()
    doc["elements"][0]["qr_fill_box"] = True
    doc["elements"][0]["qr_margin_mm"] = 1
    doc["elements"][1]["vertical_align"] = "center"
    response = client.post("/api/templates", json={"name": "Asset", "document": doc})
    assert response.status_code == 201, response.text
    template = response.json()
    data = {"name": "ASSET-42", "url": "https://example.org/42"}
    preview = client.post("/api/preview", json={"template_id": template["id"], "data": data}).json()
    image = Image.open(io.BytesIO(base64.b64decode(preview["png"].split(",")[1])))
    result = zxingcpp.read_barcode(image)
    assert result and result.text == data["url"]
    tape = profile(client)
    install(client, tape["id"])
    response = client.post(
        "/api/jobs", json={"template": template["id"], "tape_profile": tape["id"], "data": data}
    )
    assert response.status_code == 201, response.text
    queued = response.json()
    doc["elements"][1]["content"] = "CHANGED"
    update = {"name": "Asset updated", "document": doc, "expected_revision": 1}
    assert client.put(f"/api/templates/{template['id']}", json=update).status_code == 200
    assert client.put(f"/api/templates/{template['id']}", json=update).status_code == 409
    assert len(client.get(f"/api/templates/{template['id']}/revisions").json()) == 2
    client.delete(f"/api/templates/{template['id']}")
    client.post("/api/queue/print")
    client.app.state.worker.tick()
    label = client.app.state.worker.backend.batches[0][0]
    ink = Image.frombytes("1", (label.pixel_width, label.pixel_height), label.raster)
    assert ImageOps.invert(ink.convert("L")).tobytes() == image.convert("L").tobytes()
    assert client.get(f"/api/jobs/{queued['id']}").json()["template_snapshot"]["revision"] == 1


@pytest.mark.parametrize("change", ["outside", "tiny_qr", "unknown_field", "missing_field"])
def test_invalid_layouts_refuse_preview(client: TestClient, change: str) -> None:
    doc = asset_document()
    if change == "outside":
        doc["elements"][0]["x"] = 50
    if change == "tiny_qr":
        doc["elements"][0].update(width=2, height=2)
    if change == "unknown_field":
        doc["elements"][1]["content"] = "{{undefined}}"
    if change == "missing_field":
        doc["fields"][0]["sample"] = ""
    assert (
        client.post("/api/preview", json={"document": doc, "use_samples": True}).status_code == 422
    )


def test_content_is_escaped_and_colors_do_not_change_geometry(client: TestClient) -> None:
    doc = asset_document()
    body = {"document": doc, "data": {"name": "<script>x</script>", "url": "file:///etc/passwd"}}
    response = client.post("/api/preview", json=body)
    assert response.status_code == 200, response.text
    assert "<script>" not in response.json()["svg"]
    assert "&lt;script&gt;" in response.json()["svg"]
    colored = client.post(
        "/api/preview", json={**body, "foreground": "#ffffff", "background": "#000000"}
    ).json()
    assert colored["svg"] == response.json()["svg"]
    doc["url"] = "file:///etc/passwd"
    assert (
        client.post("/api/preview", json={"document": doc, "use_samples": True}).status_code == 422
    )


def test_legacy_mock_snapshots_keep_their_output() -> None:
    job = PrintJob(template_snapshot={"renderer": "mock"}, width_mm=24, length_mm=40)
    copy = LabelCopy(id="old")
    assert render_job(job, copy).raster == b"\xaa\x55" * 4


def test_edited_builtin_text_keeps_saved_geometry(client: TestClient) -> None:
    template = client.get("/api/templates/text").json()
    doc = template["document"]
    doc["length_mm"] = 70
    assert (
        client.put(
            "/api/templates/text",
            json={
                "name": "Edited text",
                "document": doc,
                "expected_revision": template["revision"],
            },
        ).status_code
        == 200
    )
    tape = profile(client)
    response = client.post(
        "/api/jobs",
        json={
            "template": "text",
            "tape_profile": tape["id"],
            "length_mm": 40,
            "data": {"text": "Saved layout"},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["length_mm"] == 70
    assert response.json()["template_snapshot"]["document"] == doc


def test_qr_overlap_is_advisory_and_can_be_saved_and_queued(client: TestClient) -> None:
    doc = asset_document()
    # An enclosing outline intersects bounding boxes without touching QR modules.
    doc["elements"].append(
        {
            "id": "border",
            "kind": "rectangle",
            "x": 1,
            "y": 1,
            "width": 22,
            "height": 22,
            "stroke": 0.2,
        }
    )
    preview = client.post("/api/preview", json={"document": doc, "use_samples": True})
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["warnings"]) == 1
    image = Image.open(io.BytesIO(base64.b64decode(preview.json()["png"].split(",")[1])))
    assert zxingcpp.read_barcode(image).text == "https://example.org/42"
    # Even actual overlap is the designer's choice, rather than a save/print prohibition.
    doc["elements"][1]["x"] = 5
    response = client.post("/api/templates", json={"name": "Overlap", "document": doc})
    assert response.status_code == 201, response.text
    tape = profile(client)
    response = client.post(
        "/api/jobs",
        json={
            "template": response.json()["id"],
            "tape_profile": tape["id"],
            "data": {"name": "Asset", "url": "https://example.org/42"},
        },
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("content", ["A", "B" * 60, "C" * 180])
def test_qr_fill_box_scales_up_across_versions(client: TestClient, content: str) -> None:
    import re

    import qrcode

    from app.render import RenderSpec, qr_svg
    from app.template_schema import Element

    element = Element(id="qr", kind="qr", x=2, y=2, width=20, height=20)
    matrix = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    matrix.add_data(content)
    matrix.make(fit=True)
    count = len(matrix.get_matrix())
    original = qr_svg(element, content, RenderSpec())
    element.qr_fill_box = True
    scaled = qr_svg(element, content, RenderSpec())
    original_module = float(re.search(r"h([\d.]+)v", original)[1])
    scaled_module = float(re.search(r"h([\d.]+)v", scaled)[1])
    assert scaled_module >= original_module
    assert scaled_module * count == pytest.approx(element.width)
    # First finder module starts after exactly four quiet-zone modules, no extra padding.
    assert float(re.search(r"M([\d.]+),", scaled)[1]) == pytest.approx(4 * scaled_module)
    doc = {"elements": [element.model_dump()]}
    # Content is supplied directly, without variable fields.
    doc["elements"][0]["content"] = content
    response = client.post("/api/preview", json={"document": doc})
    assert response.status_code == 200, response.text
    image = Image.open(io.BytesIO(base64.b64decode(response.json()["png"].split(",")[1])))
    assert zxingcpp.read_barcode(image).text == content
    element.width = element.height = 2
    with pytest.raises(ValueError, match="too small"):
        qr_svg(element, content, RenderSpec())


@pytest.mark.parametrize("margin", [0, 0.5, 2])
def test_qr_explicit_margin_fills_box(client: TestClient, margin: float) -> None:
    import re

    from app.render import RenderSpec, qr_svg
    from app.template_schema import Element

    element = Element(
        id="qr",
        kind="qr",
        x=2,
        y=2,
        width=20,
        height=20,
        content="Margin test",
        qr_fill_box=True,
        qr_margin_mm=margin,
    )
    svg = qr_svg(element, element.content, RenderSpec())
    cells = re.findall(r"M([\d.]+),([\d.]+)h([\d.]+)v", svg)
    assert min(float(x) for x, _, _ in cells) == pytest.approx(margin)
    assert max(float(x) + float(size) for x, _, size in cells) == pytest.approx(20 - margin)
    response = client.post("/api/preview", json={"document": {"elements": [element.model_dump()]}})
    assert response.status_code == 200, response.text
    image = Image.open(io.BytesIO(base64.b64decode(response.json()["png"].split(",")[1])))
    assert zxingcpp.read_barcode(image).text == element.content
    element.qr_margin_mm = 10
    with pytest.raises(ValueError, match="too small"):
        qr_svg(element, element.content, RenderSpec())


@pytest.mark.parametrize("content", ["Single line", "Two\nlines"])
def test_text_vertical_alignment_positions_whole_block(content: str) -> None:
    import re

    from app.render import text_svg
    from app.template_schema import Element

    element = Element(id="text", kind="text", x=2, y=2, width=40, height=20)
    positions = []
    for alignment in ("top", "center", "bottom"):
        element.vertical_align = alignment
        positions.append(
            [float(y) for y in re.findall(r' y="([\d.]+)"', text_svg(element, content))]
        )
    for top, center, bottom in zip(*positions):
        assert top < center < bottom
        assert center == pytest.approx((top + bottom) / 2)
    element.height = 1
    assert (
        float(re.search(r'font-size="([\d.]+)"', text_svg(element, content))[1]) < element.font_size
    )


def test_design_preview_rerenders_vectors_with_antialiasing(client: TestClient) -> None:
    doc = asset_document()
    response = client.post("/api/preview", json={"document": doc, "use_samples": True})
    assert response.status_code == 200, response.text
    result = response.json()
    raster = Image.open(io.BytesIO(base64.b64decode(result["png"].split(",")[1]))).convert("L")
    design = Image.open(io.BytesIO(base64.b64decode(result["design_png"].split(",")[1]))).convert(
        "L"
    )
    assert design.size == (raster.width * 4, raster.height * 4)
    assert set(raster.tobytes()) == {0, 255}
    assert any(0 < value < 255 for value in design.tobytes())
    assert zxingcpp.read_barcode(design).text == "https://example.org/42"


@pytest.mark.parametrize("wrap", [False, True])
@pytest.mark.parametrize("size", [(6, 2), (0.1, 0.1), (40, 20)])
def test_text_fits_box_without_exceeding_chosen_font_size(
    wrap: bool, size: tuple[float, float]
) -> None:
    import re

    from app.render import font_for, text_svg
    from app.template_schema import Element

    element = Element(
        id="fit",
        kind="text",
        x=2,
        y=2,
        width=size[0],
        height=size[1],
        wrap=wrap,
        font_size=4,
        align="center",
        vertical_align="center",
    )
    svg = text_svg(element, "Wide text\nSecond line")
    actual = float(re.search(r'font-size="([\d.]+)"', svg)[1])
    assert 0 < actual <= element.font_size
    font = font_for(element.font_size, False)
    ratio = actual / element.font_size
    lines = re.findall(r'xml:space="preserve">(.*?)</text>', svg)
    assert all(font.getlength(line) * ratio / 100 <= element.width + 1e-6 for line in lines)
    assert len(lines) * sum(font.getmetrics()) * ratio / 100 <= element.height + 1e-6
    if size == (40, 20):
        assert actual == element.font_size
    else:
        assert actual < element.font_size


def test_shrunken_text_can_be_previewed_saved_and_queued(client: TestClient) -> None:
    doc = asset_document()
    doc["elements"][1].update(height=1, width=5, font_size=6)
    response = client.post("/api/templates", json={"name": "Small text", "document": doc})
    assert response.status_code == 201, response.text
    template = response.json()
    data = {"name": "A long asset name", "url": "https://example.org/42"}
    preview = client.post("/api/preview", json={"template_id": template["id"], "data": data})
    assert preview.status_code == 200, preview.text
    tape = profile(client)
    queued = client.post(
        "/api/jobs", json={"template": template["id"], "tape_profile": tape["id"], "data": data}
    )
    assert queued.status_code == 201, queued.text
    frozen = queued.json()["template_snapshot"]["document"]
    assert (
        client.post("/api/preview", json={"document": frozen, "data": data}).json()["png"]
        == preview.json()["png"]
    )
