"""Language-core contract for future graph, source, and renderer integrations."""

import json

import pytest
from pydantic import ValidationError

from app.asset_access import asset_references
from app.logic_engine import LogicError, evaluate_program, resolve_inputs, validate_program
from app.logic_schema import (
    MAX_NODES,
    Binding,
    CallExpression,
    ImageValue,
    LiteralExpression,
    LogicInput,
    Program,
    ReferenceExpression,
    Target,
)
from app.logic_source import compile_source, format_source

TARGETS = {
    "text1": Target(
        id="stable-title-id",
        properties={"height": "number", "visible": "boolean", "content": "text"},
    ),
    "text2": Target(id="stable-subtitle-id", properties={"height": "number", "visible": "boolean"}),
    "label": Target(id="label", properties={"length_mm": "number"}),
    "picture": Target(id="stable-image-id", properties={"image_asset": "image"}),
}
FIELDS = [
    LogicInput(name="variable1", label="Subtitle", required=False, default=""),
    LogicInput(name="itemCount", label="Count", type="number", default=3, minimum=0, maximum=100),
    LogicInput(name="enabled", label="Enabled", type="boolean", default=False),
    LogicInput(name="photo", label="Photo", type="image", required=False),
]
EXAMPLE = """// Conditional text layout
let hasSubtitle = filled(variable1);
let subtitleHeight = if(hasSubtitle, 2, 0);
let titleHeight = 14 - subtitleHeight;

text1.height = titleHeight;
text2.height = 2;
text2.visible = hasSubtitle;
label.length_mm = max(30, itemCount * 12);
"""


def evaluate(source, values=None, fields=FIELDS):
    return evaluate_program(compile_source(source, fields, TARGETS), fields, TARGETS, values or {})


@pytest.mark.parametrize(
    "subtitle, height, visible", [("", 14, False), (" \n\t", 14, False), ("Subtitle", 12, True)]
)
def test_conditional_layout_and_explicit_label_length(subtitle, height, visible):
    result = evaluate(EXAMPLE, {"variable1": subtitle})
    assert result.properties == {
        "stable-title-id": {"height": height},
        "stable-subtitle-id": {"height": 2, "visible": visible},
        "label": {"length_mm": 36},
    }
    assert result.variables["hasSubtitle"] is visible


def test_defaults_samples_zero_false_and_explicit_absence():
    fields = [
        LogicInput(name="quantity", label="Quantity", type="number", default=5, sample=0),
        LogicInput(name="flag", label="Flag", type="boolean", default=True, sample=False),
        LogicInput(name="optional", label="Optional", type="number", required=False, default=4),
    ]
    assert resolve_inputs(fields, {}, samples=True) == {"quantity": 0, "flag": False, "optional": 4}
    assert resolve_inputs(fields, {"quantity": 0, "flag": False, "optional": None}) == {
        "quantity": 0,
        "flag": False,
        "optional": None,
    }
    assert (
        evaluate(
            "text1.visible = filled(itemCount) and filled(enabled);",
            {"itemCount": 0, "enabled": False},
        ).properties["stable-title-id"]["visible"]
        is True
    )


@pytest.mark.parametrize(
    "value", ["3", True, [], {}, float("nan"), float("inf"), 10**1000, -1, 101]
)
def test_numbers_are_strict_finite_and_bounded(value):
    with pytest.raises(LogicError, match="Count: invalid number"):
        resolve_inputs(FIELDS, {"itemCount": value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", "false"),
        ("enabled", 0),
        ("variable1", 5),
        ("photo", "https://example.invalid/image.png"),
    ],
)
def test_no_implicit_type_coercion(field, value):
    with pytest.raises(LogicError):
        resolve_inputs(FIELDS, {field: value})


def test_required_values_unknown_fields_and_sanitized_errors():
    with pytest.raises(LogicError, match="Count is required"):
        resolve_inputs(FIELDS, {"itemCount": None})
    with pytest.raises(LogicError, match="Unknown inputs"):
        resolve_inputs(FIELDS, {"unknown": 1})
    with pytest.raises(LogicError) as captured:
        resolve_inputs(FIELDS, {"itemCount": "sensitive-user-value"})
    assert "sensitive-user-value" not in str(captured.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "boolean", "default": 1},
        {"type": "number", "minimum": 5, "maximum": 2},
        {"type": "text", "minimum": 1},
        {"type": "number", "default": True},
        {"type": "number", "sample": float("inf")},
        {"type": "number", "minimum": 3, "default": 2},
        {"name": "if"},
        {"default": "x" * 2001},
    ],
)
def test_invalid_input_definitions_are_rejected(changes):
    with pytest.raises(ValidationError):
        LogicInput.model_validate({"name": "field1", "label": "Field", **changes})


def test_intermediates_are_order_independent_and_can_be_shared():
    first = "let result = base * 2; let base = itemCount + 1; text1.height = result; text2.height = result;"
    second = "let base = itemCount + 1; let result = base * 2; text1.height = result; text2.height = result;"
    assert evaluate(first) == evaluate(second)
    assert evaluate(first).variables == {"base": 4, "result": 8}


@pytest.mark.parametrize(
    "source, message",
    [
        ("let a = b; let b = a; text1.height = a;", "Circular"),
        ("let a = a;", "Circular"),
        ("let a = missing;", "Undefined"),
        ("let a = 1; let a = 2;", "Duplicate"),
        ("let variable1 = 1;", "conflicts"),
        ("let text1 = 1;", "conflicts"),
        ("let if = 1;", "conflicts"),
        ("text1.height = 1; text1.height = 2;", "only be bound once"),
        ("unknown.height = 1;", "Unknown output"),
        ("label.width_mm = 24;", "Unknown target property"),
        ("text1.height = enabled;", "requires a number"),
        ("text1.visible = 1;", "requires a boolean"),
        ("text1.height = if(variable1, 12, 14);", "boolean condition"),
        ("text1.height = if(true, 12, false);", "compatible types"),
        ("text1.height = if(true, 12, 1 + false);", "number arguments"),
        ("text1.visible = itemCount == enabled;", "compatible types"),
        ("text1.height = min(1);", "argument count"),
        ("text1.height = unknown(1);", "Unknown operation"),
        ("text1.height = null;", "requires a number"),
    ],
)
def test_static_diagnostics(source, message):
    with pytest.raises(LogicError, match=message):
        compile_source(source, FIELDS, TARGETS)


@pytest.mark.parametrize(
    "source",
    [
        'text1.height = __import__("os");',
        'text1.height = eval("1+1");',
        "text1.height = itemCount.real;",
        "text1.height = [1, 2];",
        "text1.height = (lambda: 1)();",
        "while true: text1.height = 1;",
        "text1.height = 2 ** 3;",
        "text1.height = (1).__class__;",
        "text1.height = 1",  # Statements require semicolons.
        'text1.content = "unterminated;',
    ],
)
def test_host_language_syntax_and_unknown_execution_are_rejected(source):
    with pytest.raises(LogicError):
        compile_source(source, FIELDS, TARGETS)


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("10 - 3 - 2", 5),
        ("-2 * -3", 6),
        (".5 + 1e1", 10.5),
        ("round(2.5)", 2),
        ("round(3.5)", 4),
        ("abs(-2)", 2),
        ("min(2, 5)", 2),
        ("max(2, 5)", 5),
        ("8 / 2", 4),
    ],
)
def test_arithmetic(expression, expected):
    assert (
        evaluate(f"text1.height = {expression};").properties["stable-title-id"]["height"]
        == expected
    )


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("not itemCount > 2", False),
        ("true or false and false", True),
        ("itemCount >= 3 and itemCount <= 3", True),
        ("itemCount < 3 or itemCount != 3", False),
        ("variable1 == null", False),
        ("photo == null", True),
        ("filled(false)", True),
        ("filled(0)", True),
        ("filled(null)", False),
    ],
)
def test_boolean_operators_and_presence(expression, expected):
    assert (
        evaluate(f"text1.visible = {expression};").properties["stable-title-id"]["visible"]
        is expected
    )


def test_lazy_branches_do_not_evaluate_unselected_errors():
    result = evaluate(
        "text1.height = if(false, 1 / 0, 12); text1.visible = false and (1 / 0 > 2); text2.visible = true or (1 / 0 > 2);"
    )
    assert result.properties["stable-title-id"] == {"height": 12, "visible": False}
    assert result.properties["stable-subtitle-id"]["visible"] is True


def test_missing_optional_numbers_must_be_guarded():
    fields = [LogicInput(name="quantity", label="Quantity", type="number", required=False)]
    assert (
        evaluate(
            "text1.height = if(filled(quantity), quantity * 2, 14);", fields=fields
        ).properties["stable-title-id"]["height"]
        == 14
    )
    with pytest.raises(LogicError, match="present number"):
        evaluate("text1.height = quantity * 2;", fields=fields)
    with pytest.raises(LogicError, match="present number"):
        evaluate("text1.height = quantity;", fields=fields)


@pytest.mark.parametrize(
    "source", ["text1.height = 1 / 0;", "text1.height = 1e12 * 2;", "text1.height = 1e999;"]
)
def test_invalid_numeric_results_are_rejected(source):
    with pytest.raises(LogicError):
        evaluate(source)


def test_images_are_structured_asset_references_and_remain_discoverable():
    identifier = "a" * 64
    result = evaluate("picture.image_asset = photo;", {"photo": {"image_asset": identifier}})
    assert result.properties["stable-image-id"]["image_asset"] == ImageValue(image_asset=identifier)
    source = f'picture.image_asset = if(filled(photo), photo, image("{identifier}"));'
    program = compile_source(source, FIELDS, TARGETS)
    assert asset_references(program.model_dump()) == {("image_asset", identifier)}
    assert evaluate(source).properties["stable-image-id"]["image_asset"] == ImageValue(
        image_asset=identifier
    )
    assert (
        evaluate("picture.image_asset = null;").properties["stable-image-id"]["image_asset"] is None
    )
    for invalid in (
        'image("/tmp/image.png")',
        'image("https://example.invalid")',
        "image(variable1)",
    ):
        with pytest.raises(LogicError):
            compile_source(f"picture.image_asset = {invalid};", FIELDS, TARGETS)


@pytest.mark.parametrize(
    "source",
    [
        EXAMPLE,
        'text1.content = "こんにちは \\"world\\"";',
        "text1.height = -(1 + 2) / 4; text1.visible = not (false or true);",
        f'picture.image_asset = image("{"b" * 64}");',
    ],
)
def test_json_and_source_round_trips_preserve_evaluation(source):
    program = compile_source(source, FIELDS, TARGETS)
    restored = Program.model_validate(json.loads(program.model_dump_json()))
    original_json = restored.model_dump_json()
    formatted = format_source(restored, FIELDS, TARGETS)
    for data in ({}, {"variable1": "Subtitle", "itemCount": 7}):
        expected = evaluate_program(program, FIELDS, TARGETS, data)
        assert evaluate_program(restored, FIELDS, TARGETS, data) == expected
        assert evaluate(formatted, data) == expected
    assert restored.model_dump_json() == original_json  # Evaluation never mutates the program.


def test_diagnostics_expose_source_location_and_node_id():
    source = "// comment\ntext1.height = itemCount / 0;"
    program = compile_source(source, FIELDS, TARGETS)
    program.bindings[0].expression.node_id = "division-node"
    with pytest.raises(LogicError) as captured:
        evaluate_program(program, FIELDS, TARGETS, {})
    assert captured.value.location(source) == (2, 16)
    assert captured.value.node_id == "division-node"
    with pytest.raises(LogicError) as syntax:
        compile_source("\ntext1.height = ;", FIELDS, TARGETS)
    assert syntax.value.location("\ntext1.height = ;") == (2, 16)


@pytest.mark.parametrize(
    "source",
    [
        " " * 16385,
        "text1.height = " + "(" * 80 + "1" + ")" * 80 + ";",
        "text1.height = " + "+".join("1" for _ in range(MAX_NODES)) + ";",
        "\n".join(f"let var{i} = 1;" for i in range(65)),
        "let " + "x" * 41 + " = 1;",
    ],
)
def test_source_complexity_is_bounded(source):
    with pytest.raises(LogicError):
        compile_source(source, FIELDS, TARGETS)


def test_graph_documents_obey_the_same_limits_and_type_checks():
    expression = LiteralExpression(value=1)
    for _ in range(40):
        expression = CallExpression(operation="negate", arguments=[expression])
    program = Program(
        bindings=[Binding(target="stable-title-id", property="height", expression=expression)]
    )
    with pytest.raises(LogicError, match="depth"):
        validate_program(program, FIELDS, TARGETS)
    bad = Program(variables={"value1": CallExpression(operation="execute", arguments=[])})
    with pytest.raises(LogicError, match="Unknown operation"):
        validate_program(bad, FIELDS, TARGETS)
    cyclic = Program(
        variables={
            "first": ReferenceExpression(name="second"),
            "second": ReferenceExpression(name="first"),
        }
    )
    with pytest.raises(LogicError, match="Circular"):
        validate_program(cyclic, FIELDS, TARGETS)


def test_output_ids_survive_alias_rename():
    program = compile_source("text1.height = 12;", FIELDS, TARGETS)
    renamed = {"title": TARGETS["text1"]}
    assert format_source(program, FIELDS, renamed) == "title.height = 12.0;"
    assert evaluate_program(program, FIELDS, renamed, {}).properties == {
        "stable-title-id": {"height": 12}
    }


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("count", [32, 33])
def test_dependency_depth_is_independent_of_declaration_order(reverse, count):
    definitions = ["let value0 = 1;"] + [f"let value{i} = value{i - 1};" for i in range(1, count)]
    if reverse:
        definitions.reverse()
    source = "\n".join([*definitions, f"text1.height = value{count - 1};"])
    if count == 33:
        with pytest.raises(LogicError, match="depth"):
            evaluate(source)
    else:
        assert evaluate(source).properties["stable-title-id"]["height"] == 1


def test_maximum_depth_graph_can_be_edited_as_source():
    expression = ReferenceExpression(name="itemCount")
    for _ in range(32):
        expression = CallExpression(operation="negate", arguments=[expression])
    program = Program(
        bindings=[Binding(target="stable-title-id", property="height", expression=expression)]
    )
    formatted = format_source(program, FIELDS, TARGETS)
    assert evaluate(formatted).properties["stable-title-id"]["height"] == 3


def test_graphs_that_cannot_fit_source_budget_are_rejected_before_editing():
    program = Program(
        variables={f"value{i}": LiteralExpression(value="x" * 2000) for i in range(10)}
    )
    with pytest.raises(LogicError, match="source-size"):
        validate_program(program, FIELDS, TARGETS)


@pytest.mark.parametrize("alias", ["let", "bad alias", "true", "x" * 41])
def test_output_aliases_must_round_trip_through_the_language(alias):
    with pytest.raises(LogicError, match="aliases"):
        validate_program(Program(), FIELDS, {alias: TARGETS["text1"]})


def test_variable_and_target_names_cannot_collide():
    with pytest.raises(LogicError, match="conflicts"):
        validate_program(Program(), FIELDS, {"itemCount": TARGETS["text1"]})
