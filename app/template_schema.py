"""Bounded, data-only editor documents. No user-authored SVG or executable templates."""

import re
from typing import Literal

from pydantic import Field, model_validator

from app.schemas import Input

TOKEN = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}")


class TemplateField(Input):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=100)
    required: bool = True
    default: str = Field(default="", max_length=2000)
    sample: str = Field(default="", max_length=2000)


class DistanceHolder(Input):
    element_id: str = Field(min_length=1, max_length=80)
    axis: Literal["horizontal", "vertical"] = "horizontal"
    gap_mm: float = Field(default=2, ge=0, le=300)


class Element(Input):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["text", "qr", "rectangle", "line", "image"]
    # The unrotated origin may be negative while the rotated bounds are inside the label.
    x: float = Field(ge=-1000, le=1000)
    y: float = Field(ge=-100, le=100)
    width: float = Field(gt=0, le=1000)
    height: float = Field(gt=0, le=100)
    rotation: Literal[0, 90, 180, 270] = 0
    distance_holder: DistanceHolder | None = None
    content: str = Field(default="", max_length=2000)
    font: str = Field(default="Noto Sans", pattern=r"^(Noto Sans|[a-f0-9]{64})$")
    font_size: float = Field(default=3, ge=1, le=24)
    character_spacing: float = Field(default=0, ge=0, le=20)
    line_spacing: float = Field(default=0, ge=0, le=20)
    bold: bool = False
    align: Literal["left", "center", "right"] = "left"
    vertical_align: Literal["top", "center", "bottom"] = "top"
    auto_width: bool = False
    wrap: bool = True
    padding_top: float = Field(default=0, ge=0, le=100)
    padding_right: float = Field(default=0, ge=0, le=1000)
    padding_bottom: float = Field(default=0, ge=0, le=100)
    padding_left: float = Field(default=0, ge=0, le=1000)
    stroke: float = Field(default=0.3, ge=0.1, le=3)
    filled: bool = False
    image_asset: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    preserve_aspect: bool = True
    brightness: float = Field(default=1, ge=0, le=3)
    contrast: float = Field(default=1, ge=0, le=3)
    image_mode: Literal["threshold", "dither"] = "threshold"
    image_threshold: int = Field(default=128, ge=1, le=255)
    qr_fill_box: bool = False
    qr_margin_mm: float | None = Field(default=None, ge=0, le=50)


class TemplateDocument(Input):
    version: Literal[1] = 1
    width_mm: float = Field(default=24, gt=0, le=100)
    length_mm: float = Field(default=60, ge=10, le=300)
    auto_length: bool = False
    out_of_bounds: Literal["error", "clip"] = "error"
    print_resolution: Literal["printer", "normal", "high"] = "printer"
    elements: list[Element] = Field(default_factory=list, max_length=50)
    fields: list[TemplateField] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_document(self) -> "TemplateDocument":
        names = {field.name for field in self.fields}
        if len(names) != len(self.fields):
            raise ValueError("Variable names must be unique")
        if len({element.id for element in self.elements}) != len(self.elements):
            raise ValueError("Element IDs must be unique")
        for element in self.elements:
            if set(TOKEN.findall(element.content)) - names:
                raise ValueError(f"Element {element.id} uses an undefined variable")
            if element.kind == "qr" and abs(element.width - element.height) > 0.001:
                raise ValueError("QR elements must be square")
            if element.kind in ("line", "rectangle") and element.stroke > min(
                element.width, element.height
            ):
                raise ValueError("Stroke exceeds element dimensions")
        elements = {element.id: element for element in self.elements}
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(identifier: str) -> None:
            if identifier in visiting:
                raise ValueError("Distance holders must not form a circular dependency")
            if identifier in visited:
                return
            visiting.add(identifier)
            holder = elements[identifier].distance_holder
            if holder:
                if holder.element_id not in elements:
                    raise ValueError("Distance holder references a missing element")
                visit(holder.element_id)
            visiting.remove(identifier)
            visited.add(identifier)

        for identifier in elements:
            visit(identifier)
        return self


class TemplateInput(Input):
    scope: Literal["personal", "group", "global"] = "personal"
    group_id: str | None = None
    destination_id: str | None = None
    name: str = Field(min_length=1, max_length=100)
    document: TemplateDocument
    expected_revision: int | None = Field(default=None, ge=1)


class PreviewInput(Input):
    destination_id: str | None = None
    document: TemplateDocument | None = None
    template_id: str | None = None
    data: dict[str, str] = Field(default_factory=dict)
    use_samples: bool = False
    foreground: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")
    background: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def exactly_one_source(self) -> "PreviewInput":
        if (self.document is None) == (self.template_id is None):
            raise ValueError("Provide a document or a template ID")
        return self
