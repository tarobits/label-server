"""Resolve version 2 templates to immutable geometry and literal label content."""

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from app.logic_engine import Evaluation, evaluate_program
from app.logic_schema import ImageValue, LogicInput, Program, Target, Value, ValueType

if TYPE_CHECKING:
    from app.template_schema import TemplateDocument


def logic_fields(document: "TemplateDocument") -> list[LogicInput]:
    return [
        field if isinstance(field, LogicInput) else LogicInput.model_validate(field.model_dump())
        for field in document.fields
    ]


def logic_targets(document: "TemplateDocument") -> dict[str, Target]:
    targets = {"label": Target(id="label", properties={"length_mm": "number"})}
    for element in document.elements:
        alias = element.logic_name
        if not alias or alias in targets or element.id == "label":
            raise ValueError("Version 2 elements need unique logic names; label is reserved")
        properties: dict[str, ValueType] = {
            "x": "number",
            "y": "number",
            "width": "number",
            "height": "number",
            "rotation": "number",
            "visible": "boolean",
        }
        if element.distance_holder:
            properties["gap_mm"] = "number"
        if element.kind in ("text", "qr"):
            properties["content"] = "text"
        if element.kind == "text":
            properties.update(
                {
                    name: "number"
                    for name in (
                        "font_size",
                        "character_spacing",
                        "line_spacing",
                        "padding_top",
                        "padding_right",
                        "padding_bottom",
                        "padding_left",
                    )
                }
            )
            properties.update({name: "boolean" for name in ("bold", "wrap", "auto_width")})
            properties.update({"align": "text", "vertical_align": "text"})
        elif element.kind == "qr":
            properties.update({"qr_fill_box": "boolean", "qr_margin_mm": "number"})
        elif element.kind == "image":
            properties.update(
                {
                    "image_asset": "image",
                    "preserve_aspect": "boolean",
                    "brightness": "number",
                    "contrast": "number",
                    "image_threshold": "number",
                    "image_mode": "text",
                }
            )
        elif element.kind in ("rectangle", "line"):
            properties["stroke"] = "number"
            if element.kind == "rectangle":
                properties["filled"] = "boolean"
        targets[alias] = Target(id=element.id, properties=properties)
    if (
        document.auto_length
        and document.logic
        and any(binding.target == "label" for binding in document.logic.bindings)
    ):
        raise ValueError("Choose automatic label length or an explicit length binding")
    return targets


def display_value(value: Value) -> str:
    if value is None:
        return ""
    if isinstance(value, ImageValue):
        raise ValueError("Images cannot be used as text")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return format(value, ".15g")
    return value


def resolve_logic(
    document: "TemplateDocument", data: Mapping[str, object], *, samples: bool = False
) -> tuple["TemplateDocument", Evaluation]:
    from app.template_schema import TOKEN, TemplateDocument

    result = evaluate_program(
        document.logic or Program(),
        logic_fields(document),
        logic_targets(document),
        data,
        samples=samples,
    )
    resolved = document.model_dump()
    resolved["logic"] = None
    resolved["logic_editor"] = None
    resolved.update(result.properties.get("label", {}))
    values = {**result.inputs, **result.variables}
    for element in resolved["elements"]:
        changes = dict(result.properties.get(element["id"], {}))
        if "image_asset" in changes:
            image = changes["image_asset"]
            changes["image_asset"] = image.image_asset if isinstance(image, ImageValue) else None
        if "gap_mm" in changes:
            element["distance_holder"]["gap_mm"] = changes.pop("gap_mm")
        # Bound content is a literal result, not another template to interpolate.
        if "content" in changes:
            element["literal_content"] = True
        element.update(changes)
        if not element["literal_content"]:
            element["content"] = TOKEN.sub(
                lambda match: display_value(values[match.group(1)]), element["content"]
            )
        element["literal_content"] = True
        # Rotation is discrete; Pydantic Literal intentionally rejects arbitrary angles.
        if isinstance(element["rotation"], float) and element["rotation"].is_integer():
            element["rotation"] = int(element["rotation"])
    return TemplateDocument.model_validate(resolved), result


def csv_values(
    document: "TemplateDocument",
    row: dict[str, str],
    image_mapping: dict[str, dict[str, ImageValue]],
) -> dict[str, Value]:
    """Explicit CSV conversion; never interpret cell contents as code or URLs."""
    if document.version == 1:
        return dict(row)
    fields = {field.name: field for field in logic_fields(document)}
    result: dict[str, Value] = {}
    for name, raw in row.items():
        field = fields[name]
        value = raw.strip()
        if field.type == "text":
            result[name] = raw
        elif not value:
            result[name] = None
        elif field.type == "number":
            if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?", value):
                raise ValueError(f"{field.label}: enter a number using a decimal point")
            result[name] = field.check_value(float(value))
        elif field.type == "boolean":
            if value.casefold() not in ("true", "false", "1", "0"):
                raise ValueError(f"{field.label}: use true, false, 1, or 0")
            result[name] = value.casefold() in ("true", "1")
        else:
            image = image_mapping.get(name, {}).get(raw)
            if image is None:
                raise ValueError(f"{field.label}: CSV image value has no uploaded-image mapping")
            result[name] = image
    return result
