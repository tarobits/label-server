"""Bounded, data-only editor documents. No user-authored SVG or executable templates."""

import re
from typing import Literal

from pydantic import Field, model_validator

from app.logic_schema import LogicEditorState, LogicInput, Program, Symbol, Value, ValueType
from app.media import MediaProperties
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
    name: str = Field(default="", max_length=100)
    logic_name: Symbol | None = None
    visible: bool = True
    literal_content: bool = False
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


class PreviewTape(Input):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    foreground: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    background: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class TemplateDocument(Input):
    version: Literal[1, 2] = 1
    width_mm: float = Field(default=24, gt=0, le=100)
    media: MediaProperties = Field(default_factory=MediaProperties)
    length_mm: float = Field(default=60, ge=10, le=300)
    auto_length: bool = False
    out_of_bounds: Literal["error", "clip"] = "error"
    print_resolution: Literal["printer", "normal", "high"] = "printer"
    preview_tape: PreviewTape | None = None
    elements: list[Element] = Field(default_factory=list, max_length=50)
    fields: list[TemplateField | LogicInput] = Field(default_factory=list, max_length=20)
    logic: Program | None = None
    logic_editor: LogicEditorState | None = None

    @model_validator(mode="after")
    def validate_document(self) -> "TemplateDocument":
        if self.media.media_kind == "fixed_label":
            if self.auto_length:
                raise ValueError("Automatic label length requires continuous media")
            if self.length_mm != self.media.label_length_mm:
                raise ValueError("Design length must match the fixed-label stock length")
        types: dict[str, ValueType | Literal["null"]] = {}
        names = {field.name for field in self.fields}
        if len(names) != len(self.fields):
            raise ValueError("Variable names must be unique")
        if len({element.id for element in self.elements}) != len(self.elements):
            raise ValueError("Element IDs must be unique")
        if self.version == 1:
            if (
                self.logic is not None
                or self.logic_editor is not None
                or any(isinstance(field, LogicInput) for field in self.fields)
                or any(
                    element.logic_name is not None or not element.visible or element.literal_content
                    for element in self.elements
                )
            ):
                raise ValueError(
                    "Typed variables, visibility, and logic require template version 2"
                )
        else:
            from app.logic_engine import validate_program
            from app.template_logic import logic_fields, logic_targets

            types = validate_program(
                self.logic or Program(), logic_fields(self), logic_targets(self)
            )
            names.update(types)
        for element in self.elements:
            tokens = set() if element.literal_content else set(TOKEN.findall(element.content))
            if tokens - names:
                raise ValueError(f"Element {element.id} uses an undefined variable")
            if self.version == 2 and any(types[name] == "image" for name in tokens):
                raise ValueError("Image variables must bind an image property, not text content")
            if (
                element.visible
                and element.kind == "qr"
                and abs(element.width - element.height) > 0.001
            ):
                raise ValueError("QR elements must be square")
            if (
                element.visible
                and element.kind in ("line", "rectangle")
                and element.stroke > min(element.width, element.height)
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


class RevisionRestoreInput(Input):
    expected_revision: int = Field(ge=1)
    destination_id: str | None = None


class LogicCompileInput(Input):
    document: TemplateDocument
    source: str = Field(max_length=16384)


class PreviewInput(Input):
    tape_profile: str | None = None
    copies: int = Field(default=1, ge=1, le=1000)
    destination_id: str | None = None
    document: TemplateDocument | None = None
    template_id: str | None = None
    data: dict[str, Value] = Field(default_factory=dict, max_length=20)
    use_samples: bool = False
    foreground: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    background: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def exactly_one_source(self) -> "PreviewInput":
        if (self.document is None) == (self.template_id is None):
            raise ValueError("Provide a document or a template ID")
        return self
