"""Dimension descriptions follow input-driven geometry rather than auto-length flags."""

import copy

import pytest

from app.render import RenderSpec, render_document
from app.template_dimensions import template_dimensions
from app.template_schema import TemplateDocument


def text(**changes):
    return {
        "id": "text",
        "kind": "text",
        "x": 2,
        "y": 2,
        "width": 40,
        "height": 12,
        "content": "Fixed caption",
        **changes,
    }


def document(elements, **changes):
    return TemplateDocument.model_validate(
        {
            "auto_length": True,
            "out_of_bounds": "clip",
            # An empty sample or an unused required field must not prevent
            # measuring geometry that does not depend on its value.
            "fields": [{"name": "text", "label": "Text"}],
            "elements": elements,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "doc",
    [
        document([text(content="{{text}}", auto_width=True)], auto_length=False),
        document([text(content="{{text}}")]),
        document([text(auto_width=True)]),
        document([text()]),
        document([]),
        document([text(kind="qr", width=20, height=20, content="{{text}}")]),
    ],
    ids=["manual", "fixed-input-box", "static-auto-width", "unused-field", "empty", "qr"],
)
def test_constant_dimensions_agree_with_the_renderer_and_do_not_mutate(doc):
    original = doc.model_dump()
    dimensions = template_dimensions(doc)
    assert dimensions["variable_length"] is False
    for value in ("A", "A longer label input"):
        output = render_document(doc, {"text": value}, RenderSpec())
        assert dimensions["length_mm"] == output.document.length_mm
    assert doc.model_dump() == original
    if doc.auto_length:
        assert dimensions["length_mm"] != doc.length_mm


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_input_driven_auto_width_can_change_length_in_each_rotation(rotation):
    doc = document([text(content="{{ text }}", auto_width=True, rotation=rotation)])
    assert template_dimensions(doc) == {"variable_length": True, "length_mm": None}
    lengths = [
        render_document(doc, {"text": value}, RenderSpec()).document.length_mm
        for value in ("A", "A longer label input")
    ]
    assert lengths[0] != lengths[1]


def test_horizontal_holder_can_cancel_rotated_text_width_but_propagates_anchor_growth():
    anchor = text(id="anchor", kind="rectangle", width=10, height=10)
    caption = text(
        auto_width=True,
        content="{{text}}",
        rotation=90,
        distance_holder={"element_id": "anchor", "axis": "horizontal", "gap_mm": 2},
    )
    follower = text(
        id="follower",
        kind="rectangle",
        width=20,
        height=5,
        distance_holder={"element_id": "text", "axis": "horizontal", "gap_mm": 2},
    )
    doc = document([anchor, caption, follower])
    dimensions = template_dimensions(doc)
    assert dimensions == {"variable_length": False, "length_mm": 49}
    for value in ("A", "A longer label input"):
        assert render_document(doc, {"text": value}, RenderSpec()).document.length_mm == 49
    doc.elements[0].kind = "text"
    doc.elements[0].auto_width = True
    doc.elements[0].content = "{{text}}"
    assert template_dimensions(doc)["variable_length"] is True


def test_missing_static_font_does_not_claim_the_fallback_length():
    doc = document([text(auto_width=True, font="a" * 64)])
    assert template_dimensions(doc) == {"variable_length": False, "length_mm": None}


def test_template_and_revision_records_expose_current_and_historical_dimensions(client):
    doc = document(
        [text(content="{{text}}")], fields=[{"name": "text", "label": "Text", "sample": "A"}]
    )
    response = client.post(
        "/api/templates", json={"name": "Calculated length", "document": doc.model_dump()}
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["length_mm"] == 43
    assert saved["variable_length"] is False
    # No calculated result is written over the user's manual length or flags.
    assert saved["document"] == doc.model_dump()
    changed = copy.deepcopy(saved["document"])
    changed["elements"][0]["auto_width"] = True
    path = f"/api/templates/{saved['id']}"
    response = client.put(
        path,
        json={"name": saved["name"], "document": changed, "expected_revision": 1},
    )
    assert response.status_code == 200, response.text
    for item in (response.json(), client.get(path).json()):
        assert item["variable_length"] is True
        assert item["length_mm"] is None
    listed = next(item for item in client.get("/api/templates").json() if item["id"] == saved["id"])
    assert listed["variable_length"] is True
    revisions = client.get(f"{path}/revisions").json()
    assert [(item["variable_length"], item["length_mm"]) for item in revisions] == [
        (True, None),
        (False, 43),
    ]
