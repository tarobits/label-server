"""Describe template lengths without rasterizing previews or changing saved geometry."""

from typing import TypedDict

from app.font_assets import FontStore
from app.render import RenderSpec, resolve_layout
from app.template_schema import TOKEN, TemplateDocument


class TemplateDimensions(TypedDict):
    variable_length: bool
    length_mm: float | None


def template_dimensions(
    document: TemplateDocument, fonts: FontStore | None = None
) -> TemplateDimensions:
    if not document.auto_length:
        return {"variable_length": False, "length_mm": document.length_mm}

    elements = {element.id: element for element in document.elements}
    dynamic_widths = {
        element.id
        for element in document.elements
        if element.kind == "text" and element.auto_width and TOKEN.search(element.content)
    }
    dynamic_edges: dict[str, bool] = {}

    def right_edge_changes(identifier: str) -> bool:
        if identifier not in dynamic_edges:
            element = elements[identifier]
            holder = element.distance_holder
            if holder and holder.axis == "horizontal":
                # Horizontal holders pin the rotated left edge to the anchor's
                # right edge. A quarter turn projects the fixed height onto X.
                changes = right_edge_changes(holder.element_id) or (
                    identifier in dynamic_widths and element.rotation in (0, 180)
                )
            else:
                # Rotation is around the box center: even a quarter turn shifts
                # an unanchored box's right edge as its text width changes.
                changes = identifier in dynamic_widths
            dynamic_edges[identifier] = changes
        return dynamic_edges[identifier]

    if any(right_edge_changes(identifier) for identifier in elements):
        return {"variable_length": True, "length_mm": None}

    fixed = document.model_copy(deep=True)
    for element in fixed.elements:
        # These widths cannot affect the label's right edge. Keep their boxes
        # rather than measuring irrelevant sample text or requiring field values.
        if element.id in dynamic_widths:
            element.auto_width = False
    try:
        resolved = resolve_layout(fixed, {}, RenderSpec(), fonts)
    except (ValueError, OSError):
        # Missing fonts or invalid legacy layouts must not make the library fail
        # or present the stored fallback length as a measured physical size.
        return {"variable_length": False, "length_mm": None}
    return {"variable_length": False, "length_mm": resolved.length_mm}
