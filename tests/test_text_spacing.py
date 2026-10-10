"""Text spacing changes the same raster used for previews and physical printing."""

import base64
import io
import re

import pytest
from conftest import profile
from fontTools.ttLib import TTFont
from PIL import Image, ImageOps

from app.models import LabelCopy, PrintJob
from app.render import FONT_DIR, RenderSpec, render_document, render_job
from app.template_schema import Element, TemplateDocument, TemplateField


def document(**changes):
    return TemplateDocument(
        elements=[
            Element(
                **{
                    "id": "text",
                    "kind": "text",
                    "x": 2,
                    "y": 2,
                    "width": 50,
                    "height": 20,
                    "content": "HHH",
                    "wrap": False,
                    **changes,
                }
            )
        ]
    )


def raster(doc):
    return render_document(doc, {}, RenderSpec(dpi=254))


def ink_bounds(output):
    bounds = ImageOps.invert(output.image.convert("L")).getbbox()
    assert bounds is not None
    return bounds


@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_horizontal_spacing_expands_printed_text_and_preserves_alignment(align):
    normal = ink_bounds(raster(document(align=align)))
    spaced = ink_bounds(raster(document(align=align, character_spacing=2)))
    # Three characters have two extra 2 mm gaps at ten pixels per mm.
    assert (spaced[2] - spaced[0]) - (normal[2] - normal[0]) == pytest.approx(40, abs=1)
    assert spaced[1::2] == normal[1::2]
    if align == "left":
        assert spaced[0] == normal[0]
    elif align == "right":
        assert spaced[2] == normal[2]
    else:
        assert spaced[0] + spaced[2] == pytest.approx(normal[0] + normal[2], abs=1)


@pytest.mark.parametrize("vertical_align", ["top", "center", "bottom"])
def test_vertical_spacing_expands_only_the_gap_and_preserves_block_alignment(vertical_align):
    normal = ink_bounds(raster(document(content="H\nH", vertical_align=vertical_align)))
    spaced = ink_bounds(
        raster(document(content="H\nH", vertical_align=vertical_align, line_spacing=2))
    )
    assert (spaced[3] - spaced[1]) - (normal[3] - normal[1]) == pytest.approx(20, abs=1)
    assert spaced[0::2] == normal[0::2]
    if vertical_align == "top":
        assert spaced[1] == normal[1]
    elif vertical_align == "bottom":
        assert spaced[3] == normal[3]
    else:
        assert spaced[1] + spaced[3] == pytest.approx(normal[1] + normal[3], abs=1)
    # A single line has no inter-line gap, even with a nonzero setting.
    assert (
        raster(document(vertical_align=vertical_align)).image.tobytes()
        == raster(document(vertical_align=vertical_align, line_spacing=2)).image.tobytes()
    )


def test_character_spacing_is_included_when_wrapping():
    normal = raster(document(content="HHHHHH", width=8, wrap=True))
    spaced = raster(document(content="HHHHHH", width=8, wrap=True, character_spacing=1))
    assert normal.svg.count("<text ") == 2
    assert spaced.svg.count("<text ") == 3
    assert ink_bounds(spaced)[2] <= 100  # 2 mm origin + 8 mm text box.


@pytest.mark.parametrize("wrap", [False, True])
def test_large_spacing_shrinks_with_text_to_fit_small_boxes(wrap):
    output = raster(
        document(
            content="HHHH\nHHHH",
            width=8,
            height=3,
            wrap=wrap,
            character_spacing=2,
            line_spacing=4,
        )
    )
    element = output.document.elements[0]
    size = float(re.search(r'font-size="([\d.]+)"', output.svg)[1])
    assert 0 < size < element.font_size
    left, top, right, bottom = ink_bounds(output)
    assert left >= 20 and top >= 20
    assert right <= 100 and bottom <= 50


@pytest.mark.parametrize("content,gaps", [("ffi", 2), ("office", 5), ("A\u0301A\u0301", 1)])
def test_tracking_separates_ligatures_without_separating_accents(content, gaps):
    normal = ink_bounds(raster(document(content=content)))
    spaced = ink_bounds(raster(document(content=content, character_spacing=1)))
    assert (spaced[2] - spaced[0]) - (normal[2] - normal[0]) == pytest.approx(gaps * 10, abs=1)
    assert spaced[1::2] == normal[1::2]


@pytest.mark.parametrize("content", ["क्षि", "स्त्री", "कर्म"])
def test_near_zero_tracking_preserves_indic_conjunct_shaping(content):
    normal = raster(document(content=content, font_size=8))
    spaced = raster(document(content=content, font_size=8, character_spacing=0.001))
    assert ink_bounds(spaced) == pytest.approx(ink_bounds(normal), abs=1)


def test_tracking_preserves_right_to_left_wrapping(client):
    # Map Hebrew codepoints to bundled glyphs so this layout regression needs
    # neither a system font nor a network download.
    output = io.BytesIO()
    with TTFont(FONT_DIR / "NotoSans.ttf") as font:
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[0x05D0] = table.cmap[ord("A")]
                table.cmap[0x05D1] = table.cmap[ord("B")]
        font.save(output)
    response = client.post("/api/font-assets", content=output.getvalue())
    assert response.status_code == 201, response.text
    doc = document(content="אב אב אב", font=response.json()["id"], width=6, wrap=True)
    normal = render_document(doc, {}, RenderSpec(dpi=254), fonts=client.app.state.fonts)
    doc.elements[0].character_spacing = 1
    spaced = render_document(doc, {}, RenderSpec(dpi=254), fonts=client.app.state.fonts)
    assert normal.svg.count("<text ") > 1
    assert spaced.svg.count("<text ") == normal.svg.count("<text ")
    assert ink_bounds(spaced) == ink_bounds(normal)


def test_spacing_affects_auto_width_linked_positions_and_label_length():
    doc = document(width=5, auto_width=True, character_spacing=0)
    doc.auto_length = True
    doc.elements.append(
        Element(
            id="follower",
            kind="text",
            x=2,
            y=2,
            width=5,
            height=20,
            content="H",
            distance_holder={"element_id": "text", "gap_mm": 2},
        )
    )
    normal = raster(doc).document
    doc.elements[0].character_spacing = 2
    spaced = raster(doc).document
    assert spaced.elements[0].width - normal.elements[0].width == pytest.approx(4, abs=0.01)
    assert spaced.elements[1].x - normal.elements[1].x == pytest.approx(4, abs=0.01)
    assert spaced.length_mm - normal.length_mm == pytest.approx(4, abs=0.01)


def test_spaced_templates_freeze_in_jobs_and_csv_drafts(client):
    doc = document(character_spacing=0.7, line_spacing=1.2)
    doc.elements[0].content = "{{text}}"
    doc.fields = [TemplateField(name="text", label="Text", sample="H\nHHH")]
    # Validate the complete document after assigning variable declarations.
    serialized = TemplateDocument.model_validate(doc.model_dump()).model_dump(mode="json")
    created = client.post("/api/templates", json={"name": "Spaced text", "document": serialized})
    assert created.status_code == 201, created.text
    template = created.json()
    tape = profile(client, threshold=1000)
    body = {"template": template["id"], "tape_profile": tape["id"], "data": {"text": "H\nHHH"}}
    queued = client.post("/api/jobs", json=body)
    assert queued.status_code == 201, queued.text
    job = queued.json()
    before = client.get(f"/api/jobs/{job['id']}/preview").content
    pixels = Image.open(io.BytesIO(before)).convert("L")
    prepared = client.post(
        "/api/runs/prepare",
        json={
            "request_key": "spacing-draft",
            "name": "Spaced CSV",
            "template": template["id"],
            "expected_revision": 1,
            "tape_profile": tape["id"],
            "csv_text": 'Text\n"H\nHHH"\n',
            "mapping": {"text": "Text"},
            "rows": [{"source_row": 2, "copies": 1}],
        },
    )
    assert prepared.status_code == 200, prepared.text
    run = prepared.json()["run"]
    draft_preview = client.get(f"/api/runs/{run['id']}/rows/0/preview").json()["png"]
    assert (
        Image.open(io.BytesIO(base64.b64decode(draft_preview.split(",")[1]))).convert("L").tobytes()
        == pixels.tobytes()
    )
    serialized["elements"][0].update(character_spacing=3, line_spacing=4)
    assert (
        client.put(
            f"/api/templates/{template['id']}",
            json={"name": "Updated spacing", "document": serialized, "expected_revision": 1},
        ).status_code
        == 200
    )
    assert client.get(f"/api/jobs/{job['id']}/preview").content == before
    assert client.get(f"/api/runs/{run['id']}/rows/0/preview").json()["png"] == draft_preview
    with client.app.state.factory() as session:
        frozen = session.get(PrintJob, job["id"])
        frozen_element = frozen.template_snapshot["document"]["elements"][0]
        assert frozen_element["character_spacing"] == 0.7
        assert frozen_element["line_spacing"] == 1.2
        copy = session.get(LabelCopy, job["labels"][0]["id"])
        printed = render_job(frozen, copy, client.app.state.fonts, client.app.state.images)
        assert printed.raster == ImageOps.invert(pixels).convert("1").tobytes()
