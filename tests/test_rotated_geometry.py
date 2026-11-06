"""Logic geometry follows label axes while persisted print geometry stays stable."""

import pytest

from app.element_geometry import element_geometry, local_geometry
from app.logic_source import compile_source
from app.render import RenderSpec, element_bounds, render_document
from app.template_logic import logic_fields, logic_property_values, logic_targets
from app.template_schema import Element, TemplateDocument


def document(rotation, source="", *, kind="text", auto_width=False):
    element = Element(
        id="object",
        logic_name="object",
        kind=kind,
        rotation=rotation,
        x=8,
        y=8,
        width=8,
        height=6,
        stroke=0.3,
        content="Text",
        auto_width=auto_width,
    )
    # Start from the same visible origin at every angle, including legacy line padding.
    geometry = element_geometry(element)
    element.x += 4 - geometry["x"]
    element.y += 4 - geometry["y"]
    doc = TemplateDocument(version=2, elements=[element], auto_length=True)
    doc.logic = compile_source(source, logic_fields(doc), logic_targets(doc))
    return doc


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_resizing_logic_height_changes_only_visible_height(rotation):
    doc = document(rotation, "object.height = 2;")
    before = element_geometry(doc.elements[0])
    result = render_document(doc, {}, RenderSpec())
    after = element_geometry(result.document.elements[0])
    assert after == {**before, "height": 2}
    assert result.document.length_mm == before["x"] + before["width"] + 1
    frozen = render_document(result.document, result.resolved_inputs, RenderSpec())
    assert frozen.image.tobytes() == result.image.tobytes()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_geometry_property_reads_and_assignments_use_visible_bounds(rotation):
    doc = document(rotation, "object.width = object.height; object.x = 3; object.y = 5;")
    before = element_geometry(doc.elements[0])
    values = logic_property_values(doc)["object"]
    assert {name: values[name] for name in before} == before
    output = render_document(doc, {}, RenderSpec())
    assert element_geometry(output.document.elements[0]) == {
        "x": 3,
        "y": 5,
        "width": before["height"],
        "height": before["height"],
    }


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_line_bounds_and_logic_stroke_have_no_empty_box(rotation):
    doc = document(rotation, "object.stroke = 1;", kind="line")
    before = element_geometry(doc.elements[0])
    axis = "width" if rotation % 180 else "height"
    output = render_document(doc, {}, RenderSpec())
    expected = {**before, axis: 1}
    assert element_geometry(output.document.elements[0]) == expected
    assert element_bounds(output.document.elements[0]) == (
        expected["x"],
        expected["y"],
        expected["x"] + expected["width"],
        expected["y"] + expected["height"],
    )
    with pytest.raises(ValueError, match="stroke"):
        document(rotation, f"object.{axis} = 2;", kind="line")


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_automatic_text_dimension_uses_rotated_axis(rotation):
    axis = "height" if rotation % 180 else "width"
    doc = document(rotation, auto_width=True)
    assert axis in logic_targets(doc)["object"].disabled_properties
    with pytest.raises(ValueError, match="automatic text width"):
        compile_source(f"object.{axis} = 2;", logic_fields(doc), logic_targets(doc))


@pytest.mark.parametrize("kind", ["text", "line"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_existing_local_geometry_is_not_rewritten_without_geometry_bindings(rotation, kind):
    doc = document(rotation, kind=kind)
    output = render_document(doc, {}, RenderSpec())
    for name in ["x", "y", "width", "height", "stroke", "rotation"]:
        assert getattr(output.document.elements[0], name) == getattr(doc.elements[0], name)
    assert (
        local_geometry(element_geometry(doc.elements[0]), rotation)["width"]
        == doc.elements[0].width
    )


@pytest.mark.parametrize("kind", ["rectangle", "line"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_printed_ink_matches_logic_coordinates_on_both_axes(rotation, kind):
    from PIL import ImageOps

    doc = document(rotation, "object.x = 3; object.y = 4;", kind=kind)
    doc.elements[0].filled = True
    doc.elements[0].stroke = 1
    spec = RenderSpec()
    output = render_document(doc, {}, spec)
    geometry = element_geometry(output.document.elements[0])
    ink = ImageOps.invert(output.image.convert("L")).getbbox()
    assert ink is not None
    scale_x = output.image.width / output.document.length_mm
    scale_y = output.image.height / output.document.width_mm
    assert ink == pytest.approx(
        (
            3 * scale_x,
            4 * scale_y,
            (3 + geometry["width"]) * scale_x,
            (4 + geometry["height"]) * scale_y,
        ),
        abs=1.1,
    )


def test_rotated_logic_catalog_and_preview_agree(client):
    doc = document(90, "object.height = 2; object.x = 3; object.y = 4;")
    catalog = client.post("/api/logic/inspect", json=doc.model_dump(mode="json"))
    assert catalog.status_code == 200, catalog.text
    values = catalog.json()["property_values"]["object"]
    preview = client.post("/api/preview", json={"document": doc.model_dump(mode="json")})
    assert preview.status_code == 200, preview.text
    rendered = Element.model_validate(preview.json()["resolved_elements"][0])
    assert element_geometry(rendered) == {key: values[key] for key in ("x", "y", "width", "height")}
