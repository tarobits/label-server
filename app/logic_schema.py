"""Data-only template logic contracts, independent of rendering and printer protocols.

Image references identify assets; validating these models does not grant access to
them. The integration boundary must authorize assets before preview or submission.
"""

import math
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

MAX_NUMBER = 1_000_000_000_000
MAX_NODES = 512
MAX_DEPTH = 32
MAX_SOURCE = 16384
MAX_TEXT = 2000

ValueType = Literal["text", "number", "boolean", "image"]
Symbol = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")]
RESERVED = frozenset(
    {
        "let",
        "true",
        "false",
        "null",
        "and",
        "or",
        "not",
        "if",
        "image",
        "filled",
        "min",
        "max",
        "abs",
        "round",
        "label",
    }
)


class LogicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ImageValue(LogicModel):
    image_asset: str = Field(pattern=r"^[a-f0-9]{64}$")


Value: TypeAlias = StrictStr | StrictBool | StrictInt | StrictFloat | ImageValue | None


def value_type(value: Value) -> ValueType | Literal["null"]:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, ImageValue):
        return "image"
    return "text"


def bounded_value(value: Value) -> Value:
    if isinstance(value, str) and len(value) > MAX_TEXT:
        raise ValueError(f"Text exceeds {MAX_TEXT} characters")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if abs(value) > MAX_NUMBER or not math.isfinite(value):
            raise ValueError(f"Numbers must be finite and between {-MAX_NUMBER} and {MAX_NUMBER}")
    return value


class LogicInput(LogicModel):
    name: Symbol
    label: str = Field(min_length=1, max_length=100)
    type: ValueType = "text"
    required: bool = True
    default: Value = None
    sample: Value = None
    minimum: float | None = None
    maximum: float | None = None

    def check_value(self, value: Value) -> Value:
        bounded_value(value)
        if value is None:
            return value
        if value_type(value) != self.type:
            raise ValueError(f"{self.label}: expected {self.type}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.minimum is not None and value < self.minimum:
                raise ValueError(f"{self.label}: value is below {self.minimum:g}")
            if self.maximum is not None and value > self.maximum:
                raise ValueError(f"{self.label}: value is above {self.maximum:g}")
        return value

    @model_validator(mode="after")
    def valid_input(self) -> "LogicInput":
        if self.name in RESERVED:
            raise ValueError(f"{self.name} is reserved")
        if self.type != "number" and (self.minimum is not None or self.maximum is not None):
            raise ValueError("Only number inputs may define numeric limits")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Minimum exceeds maximum")
        self.check_value(self.default)
        self.check_value(self.sample)
        return self


class Span(LogicModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> "Span":
        if self.end < self.start:
            raise ValueError("Invalid source span")
        return self


class ExpressionBase(LogicModel):
    span: Span | None = None
    node_id: str | None = Field(default=None, min_length=1, max_length=80)


class LiteralExpression(ExpressionBase):
    kind: Literal["literal"] = "literal"
    value: Value

    @model_validator(mode="after")
    def valid_value(self) -> "LiteralExpression":
        bounded_value(self.value)
        return self


class ReferenceExpression(ExpressionBase):
    kind: Literal["reference"] = "reference"
    name: Symbol


class PropertyExpression(ExpressionBase):
    kind: Literal["property"] = "property"
    target: str = Field(min_length=1, max_length=80)
    property: Symbol


class CallExpression(ExpressionBase):
    kind: Literal["call"] = "call"
    operation: str = Field(min_length=1, max_length=40)
    arguments: list["Expression"] = Field(max_length=3)


Expression: TypeAlias = Annotated[
    LiteralExpression | ReferenceExpression | PropertyExpression | CallExpression,
    Field(discriminator="kind"),
]
CallExpression.model_rebuild()


class Binding(LogicModel):
    target: str = Field(min_length=1, max_length=80)
    property: Symbol
    expression: Expression


class Program(LogicModel):
    version: Literal[1] = 1
    variables: dict[Symbol, Expression] = Field(default_factory=dict, max_length=64)
    bindings: list[Binding] = Field(default_factory=list, max_length=128)


class Target(LogicModel):
    """A renderer-owned allowlist, keyed by source alias when compiling a program."""

    id: str = Field(min_length=1, max_length=80)
    properties: dict[Symbol, ValueType] = Field(min_length=1, max_length=64)
    readable_properties: dict[Symbol, ValueType] | None = Field(default=None, max_length=64)
    disabled_properties: dict[Symbol, str] = Field(default_factory=dict, max_length=64)


class EditorNode(LogicModel):
    """Bounded authoring metadata. Never interpreted by the rendering engine."""

    id: str = Field(min_length=1, max_length=80)
    kind: Literal["input", "property", "literal", "call", "variable", "output"]
    x: float = Field(ge=-100000, le=100000)
    y: float = Field(ge=-100000, le=100000)
    type: ValueType = "number"
    name: Symbol | None = None
    operation: str | None = Field(default=None, max_length=40)
    value: Value = None
    target: str | None = Field(default=None, max_length=80)
    property: Symbol | None = None
    inputs: list[Annotated[str, Field(min_length=1, max_length=80)] | None] = Field(
        default_factory=list, max_length=3
    )
    defaults: list[Value] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def bounded_defaults(self) -> "EditorNode":
        bounded_value(self.value)
        for value in self.defaults:
            bounded_value(value)
        return self


class LogicEditorState(LogicModel):
    version: Literal[1] = 1
    source: str | None = Field(default=None, max_length=MAX_SOURCE)
    nodes: list[EditorNode] = Field(default_factory=list, max_length=512)
    x: float = Field(default=24, ge=-100000, le=100000)
    y: float = Field(default=24, ge=-100000, le=100000)
    zoom: float = Field(default=1, ge=0.25, le=2)

    @model_validator(mode="after")
    def unique_nodes(self) -> "LogicEditorState":
        if len({node.id for node in self.nodes}) != len(self.nodes):
            raise ValueError("Editor node IDs must be unique")
        return self
