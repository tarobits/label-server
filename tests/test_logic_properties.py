"""Property dependencies and measured automatic dimensions are typed and frozen."""

import copy

import pytest
from conftest import profile
from test_template_logic import TARGETS
from test_template_logic_integration import document, save_template

from app.render import RenderSpec, render_document
from app.templates.logic_engine import LogicError, evaluate_program
from app.templates.logic_schema import Target
from app.templates.logic_source import compile_source, format_source
from app.templates.template_logic import logic_fields, logic_targets
from app.templates.template_schema import TemplateDocument


@pytest.mark.parametrize("reverse", [False, True])
def test_property_reads_follow_bindings_and_intermediates_independent_of_order(reverse):
    lines = ["text2.height = half;", "let half = text1.height / 2;", "text1.height = 12;"]
    source = "\n".join(reversed(lines) if reverse else lines)
    program = compile_source(source, [], TARGETS)
    result = evaluate_program(program, [], TARGETS, {})
    assert result.properties["stable-subtitle-id"]["height"] == 6
    renamed = {"renamed" if name == "text1" else name: target for name, target in TARGETS.items()}
    formatted = format_source(program, [], renamed)
    assert "renamed.height" in formatted
    assert (
        evaluate_program(compile_source(formatted, [], renamed), [], renamed, {}).properties
        == result.properties
    )


@pytest.mark.parametrize(
    "source",
    [
        "text1.height = text1.height - 2;",
        "text1.height = text2.height; text2.height = text1.height;",
        "let value = text1.height; text1.height = value;",
        "text1.height = if(false, text1.height, 12);",
    ],
)
def test_circular_property_dependencies_are_rejected_even_in_unused_branches(source):
    with pytest.raises(LogicError, match="Circular dependency"):
        compile_source(source, [], TARGETS)


@pytest.mark.parametrize(
    "source",
    [
        "text1.height = text1.visible;",
        "text1.height = unknown.width;",
        "text1.height = text1.unknown;",
        "text1.visible = text1.content == text2.height;",
    ],
)
def test_property_inputs_do_not_weaken_types_or_allow_arbitrary_attributes(source):
    with pytest.raises(LogicError):
        compile_source(source, [], TARGETS)


@pytest.mark.parametrize("reverse", [False, True])
def test_property_chains_cannot_bypass_dependency_depth_limits(reverse):
    targets = {f"p{i}": Target(id=f"id{i}", properties={"width": "number"}) for i in range(35)}
    lines = [f"p{i}.width = p{i + 1}.width;" for i in range(34)] + ["p34.width = 1;"]
    with pytest.raises(LogicError, match="depth"):
        compile_source("\n".join(reversed(lines) if reverse else lines), [], targets)


def auto_document(source):
    raw = document("", automatic=True).model_dump()
    raw["elements"][0].update(auto_width=True, content="{{variable1}}")
    base = TemplateDocument.model_validate(raw)
    raw["logic"] = compile_source(source, logic_fields(base), logic_targets(base)).model_dump()
    return TemplateDocument.model_validate(raw)


def test_automatic_text_measures_bound_content_before_dependent_geometry():
    base = auto_document("")
    plain = render_document(base, {"variable1": "Long measured title"}, RenderSpec())
    doc = auto_document(
        'let measured = text1.width; text2.width = measured / 2; text1.content = "X"; text2.visible = false; let width = label.width_mm;'
    )
    output = render_document(doc, {"variable1": "Long measured title"}, RenderSpec())
    assert output.document.length_mm == max(
        10, output.document.elements[0].x + output.document.elements[0].width + 1
    )
    expected = auto_document("")
    expected.elements[0].content = "X"
    measured = render_document(expected, {"variable1": "Long measured title"}, RenderSpec())
    assert output.document.elements[0].width == measured.document.elements[0].width
    assert output.document.elements[0].width < plain.document.elements[0].width
    assert output.document.elements[1].width == measured.document.elements[0].width / 2
    assert output.document.elements[0].content == "X"
    assert not output.document.elements[0].auto_width
    assert not output.document.auto_length
    assert output.resolved_inputs is not None
    repeated = render_document(output.document, output.resolved_inputs, RenderSpec())
    assert output.image.tobytes() == repeated.image.tobytes()


@pytest.mark.parametrize(
    "source, message",
    [
        ("text1.width = 20;", "automatic text width"),
        ("label.length_mm = 60;", "automatic label length"),
        ("text1.auto_width = false;", "Layout"),
    ],
)
def test_automatic_fields_reject_assignments(source, message):
    with pytest.raises(ValueError, match=message):
        auto_document(source)


def test_read_only_label_properties_and_unbound_boolean_values():
    output = render_document(
        document("text1.width = label.width_mm; text2.visible = label.auto_length;"),
        {},
        RenderSpec(),
    )
    assert output.document.elements[0].width == 24
    assert output.document.elements[1].visible is False
    with pytest.raises(LogicError, match="Unknown target"):
        document("label.width_mm = 12;")


def test_automatic_label_length_follows_logic_positions():
    output = render_document(
        document("text2.x = 40;", automatic=True),
        {},
        RenderSpec(),
    )
    assert output.document.elements[1].x == 40
    assert output.document.length_mm == 76


def test_automatic_label_length_is_not_a_logic_input():
    with pytest.raises(LogicError, match="cannot be read"):
        document("text2.width = label.length_mm;", automatic=True)


def test_hidden_text_is_measured_before_logic_makes_it_visible():
    doc = auto_document('text1.visible = true; text1.content = "X"; text2.width = text1.width;')
    doc.elements[0].visible = False
    expected = auto_document("")
    expected.elements[0].content = "X"
    plain = render_document(expected, {"variable1": "Long measured title"}, RenderSpec())
    output = render_document(doc, {"variable1": "Long measured title"}, RenderSpec())
    assert output.document.elements[0].width == plain.document.elements[0].width
    assert output.document.elements[1].width == plain.document.elements[0].width
    assert output.document.elements[0].visible
    assert not output.document.elements[0].auto_width


@pytest.mark.parametrize(
    "text,bold,left,right",
    [
        ("Short", False, False, True),
        ("Longer bound text between two images", True, True, True),
        ("Two lines\nwith bold text", True, True, False),
    ],
)
def test_bound_text_auto_sizes_between_logic_positioned_images(text, bold, left, right):
    from app.templates.logic_schema import ImageValue, LogicInput

    source = TemplateDocument.model_validate(
        {
            "version": 2,
            "auto_length": True,
            "out_of_bounds": "clip",
            "fields": [
                LogicInput(
                    name="left_image", label="Left image", type="image", required=False
                ).model_dump(),
                LogicInput(
                    name="right_image", label="Right image", type="image", required=False
                ).model_dump(),
                LogicInput(name="bold_text", label="Bold", type="boolean").model_dump(),
                LogicInput(name="text_content", label="Text").model_dump(),
            ],
            "elements": [
                {
                    "id": "left",
                    "logic_name": "image1",
                    "kind": "image",
                    "x": 1,
                    "y": 1,
                    "width": 10,
                    "height": 10,
                },
                {
                    "id": "text",
                    "logic_name": "text1",
                    "kind": "text",
                    "x": 12,
                    "y": 1,
                    "width": 2,
                    "height": 10,
                    "auto_width": True,
                    "content": "Fallback",
                },
                {
                    "id": "right",
                    "logic_name": "image2",
                    "kind": "image",
                    "x": 15,
                    "y": 1,
                    "width": 10,
                    "height": 10,
                },
            ],
        }
    )
    source.logic = compile_source(
        """
        image1.image_asset = left_image;
        image2.image_asset = right_image;
        text1.bold = bold_text;
        text1.x = if(filled(left_image), (1 + (image1.x + image1.width)), 1);
        image2.x = ((if(filled(left_image), (1 + (image1.x + image1.width)), 1) + text1.width) + 1);
        image1.visible = filled(left_image);
        image2.visible = filled(right_image);
        text1.content = text_content;
    """,
        logic_fields(source),
        logic_targets(source),
    )
    values = {
        "text_content": text,
        "bold_text": bold,
        "left_image": ImageValue(image_asset="a" * 64) if left else None,
        "right_image": ImageValue(image_asset="b" * 64) if right else None,
    }
    result = render_document(source, values, RenderSpec(), allow_missing_assets=True)
    actual = result.document.elements[1]
    expected = source.model_copy(deep=True)
    expected.logic = None
    expected.elements[0].visible = False
    expected.elements[2].visible = False
    expected.elements[1].content = text
    expected.elements[1].bold = bold
    measured = render_document(expected, values, RenderSpec(), allow_missing_assets=True)
    assert actual.content == text and actual.bold == bold
    assert actual.width == measured.document.elements[1].width
    assert actual.x == (12 if left else 1)
    assert result.document.elements[2].x == actual.x + actual.width + 1
    assert source.elements[1].width == 2 and source.elements[1].auto_width


def test_auto_sizing_rejects_implicit_geometry_cycles():
    doc = auto_document("text1.font_size = text2.x; text2.x = text1.width;")
    with pytest.raises(ValueError, match="No saved value for property"):
        render_document(doc, {"variable1": "Cycle"}, RenderSpec())


def test_inspection_preview_and_queued_snapshot_agree_on_measured_inputs(client):
    doc = auto_document(
        "text2.width = text1.width / 2; text2.visible = false; let measured = text1.width;"
    )
    raw = doc.model_dump()
    raw["fields"][0]["sample"] = raw["fields"][0]["default"] = "Measured label"
    doc = TemplateDocument.model_validate(raw)
    tape = profile(client)
    saved = save_template(client, doc)
    inspected = client.post("/api/logic/inspect", json=doc.model_dump(mode="json"))
    assert inspected.status_code == 200, inspected.text
    catalog = inspected.json()
    assert catalog["sample_error"] is None
    assert catalog["targets"]["text1"]["disabled_properties"]["width"]
    preview = client.post(
        "/api/preview", json={"document": doc.model_dump(mode="json"), "use_samples": True}
    ).json()
    assert catalog["values"]["measured"] == catalog["property_values"]["title-id"]["width"]
    response = client.post(
        "/api/jobs", json={"template": saved["id"], "tape_profile": tape["id"], "data": {}}
    )
    assert response.status_code == 201, response.text
    job = response.json()
    frozen = job["template_snapshot"]["document"]
    assert frozen["length_mm"] == preview["length_mm"]
    assert frozen["elements"] == preview["resolved_elements"]
    changed = copy.deepcopy(saved["document"])
    changed["fields"][0]["default"] = "Changed"
    assert (
        client.put(
            f"/api/templates/{saved['id']}",
            json={
                "name": saved["name"],
                "document": changed,
                "expected_revision": saved["revision"],
            },
        ).status_code
        == 200
    )
    assert client.get(f"/api/jobs/{job['id']}").json()["template_snapshot"]["document"] == frozen
