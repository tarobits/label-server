import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from conftest import install, profile
from fontTools.ttLib import TTFont
from sqlalchemy import select

from app.asset_cache import expire
from app.font_assets import FontStore
from app.font_variations import InvalidFontWeight, static_instance
from app.models import PrintJob
from app.render import RenderSpec, font_path, render_document
from app.template_schema import TemplateDocument

VARIABLE = Path("app/fonts/NotoSans-Variable.ttf")


def design(weight=None, font="Noto Sans", **kwargs):
    return TemplateDocument.model_validate(
        {
            "width_mm": 24,
            "length_mm": 90,
            "out_of_bounds": "clip",
            "elements": [
                {
                    "id": "t",
                    "kind": "text",
                    "x": 2,
                    "y": 2,
                    "width": 70,
                    "height": 18,
                    "font_size": 6,
                    "content": "Medium weight",
                    "font": font,
                    "font_weight": weight,
                    **kwargs,
                }
            ],
        }
    )


def test_named_and_numeric_builtin_weights_have_distinct_output_and_metrics(tmp_path):
    fonts = FontStore(tmp_path)
    outputs = [
        render_document(design(w, auto_width=True), {}, RenderSpec(), fonts=fonts)
        for w in (100, 200, 300, 400, 450.5, 500, 600, 700, 800, 900)
    ]
    assert len({o.image.tobytes() for o in outputs}) == 10
    assert len({o.document.elements[0].width for o in outputs}) > 2
    for weight, bold in [(400, False), (700, True)]:
        legacy = render_document(design(bold=bold), {}, RenderSpec(), fonts=fonts)
        explicit = render_document(design(weight), {}, RenderSpec(), fonts=fonts)
        assert legacy.image.tobytes() == explicit.image.tobytes()
        assert legacy.preview("black", "white", smooth=True) == explicit.preview(
            "black", "white", smooth=True
        )


def test_variable_upload_limits_instances_and_cache_recovery(client):
    response = client.post("/api/font-assets", content=VARIABLE.read_bytes())
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["variable"]
    assert asset["weight_axis"] == {"min": 100, "max": 900, "default": 400}
    fonts = client.app.state.fonts
    light = render_document(design(300, asset["id"]), {}, RenderSpec(), fonts=fonts)
    heavy = render_document(design(800, asset["id"]), {}, RenderSpec(), fonts=fonts)
    assert light.image.tobytes() != heavy.image.tobytes()
    assert light.font_files[-1] != heavy.font_files[-1]
    with TTFont(light.font_files[-1]) as face:
        assert "fvar" not in face
    expected = light.preview("black", "white", smooth=True)
    expire(fonts.root, 0, now=10**12)
    assert light.preview("black", "white", smooth=True) == expected
    for weight in (99, 901):
        result = client.post(
            "/api/preview", json={"document": design(weight, asset["id"]).model_dump()}
        )
        assert result.status_code == 422, result.text
        assert "weight" in result.text.lower()
    fonts.unavailable = lambda identifier: identifier == asset["id"]
    with pytest.raises(ValueError, match="deleted"):
        font_path(design(300, asset["id"]).elements[0], fonts)


def test_static_fonts_keep_their_real_weight(client):
    asset = client.post(
        "/api/font-assets", content=Path("app/fonts/NotoSans-Bold.ttf").read_bytes()
    ).json()
    assert asset["weight"] == 700 and asset["weight_axis"] is None
    fonts = client.app.state.fonts
    implicit = render_document(design(font=asset["id"]), {}, RenderSpec(), fonts=fonts)
    explicit = render_document(design(700, asset["id"]), {}, RenderSpec(), fonts=fonts)
    assert implicit.image.tobytes() == explicit.image.tobytes()
    with pytest.raises(InvalidFontWeight, match="original weight"):
        render_document(design(300, asset["id"]), {}, RenderSpec(), fonts=fonts)


def test_uploaded_weight_range_is_enforced_and_malformed_axes_are_rejected(client):
    with TTFont(VARIABLE) as font:
        axis = next(a for a in font["fvar"].axes if a.axisTag == "wght")
        axis.minValue, axis.maxValue = 300, 700
        output = io.BytesIO()
        font.save(output)
        response = client.post("/api/font-assets", content=output.getvalue())
        assert response.status_code == 201, response.text
        asset = response.json()
        assert asset["weight_axis"] == {"min": 300, "max": 700, "default": 400}
        for value, status in [(299, 422), (300, 200), (550.5, 200), (700, 200), (701, 422)]:
            preview = client.post(
                "/api/preview", json={"document": design(value, asset["id"]).model_dump()}
            )
            assert preview.status_code == status, preview.text
        axis.defaultValue = 800
        output = io.BytesIO()
        font.save(output)
        assert client.post("/api/font-assets", content=output.getvalue()).status_code == 422


def test_cff2_variable_otf_is_normalized_to_renderable_static_outlines(client):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "A"])
    builder.setupCharacterMap({65: "A"})
    builder.setupHorizontalMetrics({".notdef": (600, 0), "A": (600, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Variable OTF", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    builder.setupFvar([("wght", 100, 400, 900, "Weight")], [])
    pen = T2CharStringPen(None, None)
    pen.moveTo((50, 0))
    pen.lineTo((300, 700))
    pen.lineTo((550, 0))
    pen.closePath()
    builder.setupCFF2(
        {".notdef": T2CharStringPen(None, None).getCharString(), "A": pen.getCharString()}
    )
    output = io.BytesIO()
    builder.save(output)
    response = client.post("/api/font-assets", content=output.getvalue())
    assert response.status_code == 201, response.text
    rendered = render_document(
        design(550, response.json()["id"], content="A"),
        {},
        RenderSpec(),
        fonts=client.app.state.fonts,
    )
    assert rendered.image.convert("L").getextrema() == (0, 255)
    with TTFont(rendered.font_files[-1]) as font:
        assert "CFF " in font and "CFF2" not in font and "fvar" not in font


def test_instance_publication_is_safe_under_concurrent_requests(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: static_instance(VARIABLE, 575, tmp_path), range(8)))
    assert len(set(paths)) == 1
    with TTFont(paths[0]) as font:
        assert "fvar" not in font
        assert font["name"].getBestFamilyName() == paths[0].stem


def test_saved_job_keeps_weight_after_template_changes(client):
    doc = design(350).model_dump()
    template = client.post("/api/templates", json={"name": "Weighted", "document": doc}).json()
    tape = profile(client)
    install(client, tape["id"])
    response = client.post(
        "/api/jobs", json={"template": template["id"], "tape_profile": tape["id"], "data": {}}
    )
    assert response.status_code == 201, response.text
    with client.app.state.factory() as session:
        job = session.scalar(select(PrintJob).where(PrintJob.template_id == template["id"]))
        assert job.template_snapshot["document"]["elements"][0]["font_weight"] == 350
    doc["elements"][0]["font_weight"] = 800
    response = client.put(
        f"/api/templates/{template['id']}",
        json={"name": "Weighted", "document": doc, "expected_revision": 1},
    )
    assert response.status_code == 200, response.text
    with client.app.state.factory() as session:
        job = session.scalar(select(PrintJob).where(PrintJob.template_id == template["id"]))
        assert job.template_snapshot["document"]["elements"][0]["font_weight"] == 350
