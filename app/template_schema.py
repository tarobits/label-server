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


class Element(Input):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["text", "qr", "rectangle", "line", "image"]
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=100)
    width: float = Field(gt=0, le=1000)
    height: float = Field(gt=0, le=100)
    rotation: Literal[0, 90, 180, 270] = 0
    content: str = Field(default="", max_length=2000)
    font: str = Field(default="Noto Sans", pattern=r"^(Noto Sans|[a-f0-9]{64})$")
    font_size: float = Field(default=3, ge=1, le=24)
    bold: bool = False
    align: Literal["left", "center", "right"] = "left"
    vertical_align: Literal["top", "center", "bottom"] = "top"
    auto_width: bool = False
    wrap: bool = True
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
    width_mm: Literal[4, 6, 9, 12, 18, 24] = 24
    length_mm: float = Field(default=60, ge=10, le=300)
    auto_length: bool = False
    out_of_bounds: Literal["error", "clip"] = "error"
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
        return self


class TemplateInput(Input):
    name: str = Field(min_length=1, max_length=100)
    document: TemplateDocument
    expected_revision: int | None = Field(default=None, ge=1)


class PreviewInput(Input):
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
