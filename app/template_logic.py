"""Resolve version 2 templates to immutable geometry and literal label content."""

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from app.element_geometry import element_geometry, local_geometry
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
    targets = {
        "label": Target(
            id="label",
            properties={"length_mm": "number"},
            readable_properties={
                "width_mm": "number",
                "auto_length": "boolean",
                **({} if document.auto_length else {"length_mm": "number"}),
            },
            disabled_properties={
                "length_mm": "Disable automatic label length before binding label.length_mm"
            }
            if document.auto_length
            else {},
        )
    }
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
        disabled = {}
        if element.kind == "text":
            disabled["auto_width"] = "Configure automatic text width in Layout before running logic"
            if element.auto_width:
                axis = "height" if element.rotation in (90, 270) else "width"
                disabled[axis] = f"Disable automatic text width before binding {alias}.{axis}"
        if element.kind == "line":
            axis = "width" if element.rotation in (90, 270) else "height"
            disabled[axis] = "Use stroke to set line thickness"
        targets[alias] = Target(id=element.id, properties=properties, disabled_properties=disabled)
    return targets


def logic_property_values(document: "TemplateDocument") -> dict[str, dict[str, Value]]:
    """Saved fallbacks; rendering replaces automatic geometry with measured values."""
    targets = logic_targets(document)
    values: dict[str, dict[str, Value]] = {
        "label": {
            "length_mm": document.length_mm,
            "width_mm": document.width_mm,
            "auto_length": document.auto_length,
        }
    }
    for element in document.elements:
        properties: dict[str, Value] = {}
        for name in targets[element.logic_name or ""].properties:
            value: Value
            if name == "image_asset":
                value = ImageValue(image_asset=element.image_asset) if element.image_asset else None
            elif name == "gap_mm":
                assert element.distance_holder is not None
                value = element.distance_holder.gap_mm
            else:
                value = getattr(element, name)
            properties[name] = cast(Value, value)
        values[element.id] = properties
        properties.update(element_geometry(element))
    return values


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
    document: "TemplateDocument",
    data: Mapping[str, object],
    *,
    samples: bool = False,
    measured: "TemplateDocument | None" = None,
) -> tuple["TemplateDocument", Evaluation]:
    from app.template_schema import TOKEN, TemplateDocument

    property_values = logic_property_values(document)
    if measured is not None:
        property_values["label"]["length_mm"] = measured.length_mm
        for element in measured.elements:
            property_values[element.id].update(element_geometry(element))
    result = evaluate_program(
        document.logic or Program(),
        logic_fields(document),
        logic_targets(document),
        data,
        samples=samples,
        property_values=property_values,
    )
    resolved = (measured or document).model_dump()
    if measured is not None:
        # Positioning can still follow logic-controlled gaps; automatic sizes
        # have already been measured and are frozen for this render.
        originals = {element.id: element for element in document.elements}
        for element in resolved["elements"]:
            holder = originals[element["id"]].distance_holder
            element["distance_holder"] = holder.model_dump() if holder else None
    resolved["logic"] = None
    resolved["logic_editor"] = None
    resolved.update(result.properties.get("label", {}))
    values = {**result.inputs, **result.variables}
    originals = {element.id: element for element in document.elements}
    for element in resolved["elements"]:
        changes = dict(result.properties.get(element["id"], {}))
        # Logic speaks label axes. Persist the established local geometry so
        # existing saved prints keep exactly the same rendering convention.
        base = property_values[element["id"]]
        rotation = changes.get("rotation", element["rotation"])
        quarter_turn = rotation in (90, 270)
        geometry = {
            "x": cast(float, base["x"]),
            "y": cast(float, base["y"]),
            "width": element["height"] if quarter_turn else element["width"],
            "height": element["width"] if quarter_turn else element["height"],
        }
        original = originals[element["id"]]
        if original.kind == "text" and original.auto_width:
            axis = "height" if quarter_turn else "width"
            if axis in changes:
                raise ValueError(
                    f"Disable automatic text width before binding {original.logic_name}.{axis}"
                )
        if original.kind == "line":
            axis = "width" if quarter_turn else "height"
            if axis in changes:
                raise ValueError("Use stroke to set line thickness")
            geometry[axis] = cast(float, changes.get("stroke", original.stroke))
        geometry_changed = any(
            name in changes for name in ("x", "y", "width", "height", "rotation")
        )
        if original.kind == "line" and "stroke" in changes:
            geometry_changed = True
        for name in geometry:
            if name in changes:
                geometry[name] = cast(float, changes.pop(name))
        if geometry_changed:
            element.update(local_geometry(geometry, cast(int, rotation)))
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
