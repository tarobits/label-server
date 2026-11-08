"""Bounded, typed interpretation of template logic. Never executes source code."""

import json
import operator
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import TypeAdapter, ValidationError

from app.logic_schema import (
    MAX_DEPTH,
    MAX_NODES,
    MAX_SOURCE,
    RESERVED,
    Expression,
    ImageValue,
    LiteralExpression,
    LogicInput,
    Program,
    PropertyExpression,
    ReferenceExpression,
    Target,
    Value,
    ValueType,
    bounded_value,
    value_type,
)


class LogicError(ValueError):
    def __init__(
        self, message: str, expression: Expression | None = None, *, offset: int | None = None
    ):
        super().__init__(message)
        self.offset = expression.span.start if expression and expression.span else offset
        self.node_id = expression.node_id if expression else None

    def location(self, source: str) -> tuple[int, int] | None:
        """One-based line and column for an IDE diagnostic."""
        if self.offset is None:
            return None
        before = source[: self.offset]
        return before.count("\n") + 1, len(before.rsplit("\n", 1)[-1]) + 1


@dataclass(frozen=True)
class Operation:
    name: str
    minimum_arguments: int
    maximum_arguments: int
    signature: Literal["numeric", "comparison", "equality", "boolean", "conditional", "presence"]
    description: str


# Shared metadata for node search, completions, and contextual reference entries.
OPERATIONS = {
    item.name: item
    for item in (
        Operation("add", 2, 2, "numeric", "Add two numbers."),
        Operation("subtract", 2, 2, "numeric", "Subtract the second number from the first."),
        Operation("multiply", 2, 2, "numeric", "Multiply two numbers."),
        Operation("divide", 2, 2, "numeric", "Divide numbers; a zero divisor is an error."),
        Operation("negate", 1, 1, "numeric", "Negate a number."),
        Operation("min", 2, 2, "numeric", "Return the smaller of two numbers."),
        Operation("max", 2, 2, "numeric", "Return the larger of two numbers."),
        Operation("abs", 1, 1, "numeric", "Return the absolute value."),
        Operation("round", 1, 1, "numeric", "Round to the nearest integer; ties round to even."),
        Operation("less", 2, 2, "comparison", "Test whether the first number is smaller."),
        Operation(
            "less_equal", 2, 2, "comparison", "Test whether the first number is smaller or equal."
        ),
        Operation("greater", 2, 2, "comparison", "Test whether the first number is larger."),
        Operation(
            "greater_equal", 2, 2, "comparison", "Test whether the first number is larger or equal."
        ),
        Operation("equal", 2, 2, "equality", "Compare values of the same type, or test for null."),
        Operation("not_equal", 2, 2, "equality", "Test values for inequality, or test for null."),
        Operation(
            "and", 2, 2, "boolean", "True when both inputs are true; short-circuits on false."
        ),
        Operation("or", 2, 2, "boolean", "True when either input is true; short-circuits on true."),
        Operation("not", 1, 1, "boolean", "Invert a boolean."),
        Operation(
            "if",
            3,
            3,
            "conditional",
            "Choose one of two compatible values using a boolean condition.",
        ),
        Operation(
            "filled", 1, 1, "presence", "False for null or blank text; zero and false are filled."
        ),
    )
}

ResolvedType = ValueType | Literal["null"]
_VALUE: TypeAdapter[Value] = TypeAdapter(Value)
INFIX_SYMBOLS = {
    "add": "+",
    "subtract": "-",
    "multiply": "*",
    "divide": "/",
    "less": "<",
    "less_equal": "<=",
    "greater": ">",
    "greater_equal": ">=",
    "equal": "==",
    "not_equal": "!=",
    "and": "and",
    "or": "or",
}


def filled(value: Value) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def resolve_inputs(
    fields: list[LogicInput], data: Mapping[str, object], *, samples: bool = False
) -> dict[str, Value]:
    names = {field.name for field in fields}
    if len(names) != len(fields):
        raise LogicError("Input names must be unique")
    if len(fields) > 20:
        raise LogicError("At most 20 inputs are supported")
    if unknown := set(data) - names:
        raise LogicError("Unknown inputs: " + ", ".join(sorted(unknown)))
    values: dict[str, Value] = {}
    for field in fields:
        fallback = field.sample if samples and field.sample is not None else field.default
        try:
            value = field.check_value(_VALUE.validate_python(data.get(field.name, fallback)))
        except (ValueError, ValidationError) as error:
            # Never echo uploaded values or arbitrary payloads in validation errors.
            raise LogicError(
                f"{field.label}: invalid {field.type} input or value outside its limits"
            ) from error
        if field.required and not filled(value):
            raise LogicError(f"{field.label} is required")
        values[field.name] = value
    return values


def validate_program(
    program: Program, fields: list[LogicInput], targets: dict[str, Target]
) -> dict[str, ResolvedType]:
    types: dict[str, ResolvedType] = {field.name: field.type for field in fields}
    if len(types) != len(fields) or len(fields) > 20:
        raise LogicError("Input names must be unique, with at most 20 inputs")
    for alias in targets:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", alias) or (
            alias in RESERVED and alias != "label"
        ):
            raise LogicError("Target aliases must be valid, non-reserved identifiers")
        if alias in types:
            raise LogicError(f"Input {alias} conflicts with an output target")
    for name in program.variables:
        if name in types or name in RESERVED or name in targets:
            raise LogicError(
                f"Intermediate variable {name} conflicts with an existing or reserved name"
            )
    target_ids = {target.id: target for target in targets.values()}
    if len(target_ids) != len(targets):
        raise LogicError("Target IDs must be unique")
    aliases = {target.id: alias for alias, target in targets.items()}
    bindings = {}
    for binding in program.bindings:
        target = target_ids.get(binding.target)
        if target is None or binding.property not in target.properties:
            raise LogicError(
                f"Unknown target property {binding.target}.{binding.property}", binding.expression
            )
        if reason := target.disabled_properties.get(binding.property):
            raise LogicError(reason, binding.expression)
        key = (binding.target, binding.property)
        if key in bindings:
            raise LogicError("A property may only be bound once", binding.expression)
        bindings[key] = binding
    visiting: set[str] = set()
    property_types: dict[tuple[str, str], ResolvedType] = {}
    heights: dict[int, int] = {}
    source_sizes: dict[int, int] = {}
    nodes = 0

    def remember_height(expression: Expression, height: int) -> None:
        # Include cached dependencies so declaration order cannot bypass this limit.
        if height > MAX_DEPTH:
            raise LogicError("Logic exceeds the dependency-depth limit", expression)
        heights[id(expression)] = height

    def reference(name: str, expression: Expression, depth: int) -> ResolvedType:
        if name in visiting:
            raise LogicError(f"Circular dependency involving {name}", expression)
        if name not in types:
            if name not in program.variables:
                raise LogicError(f"Undefined variable {name}", expression)
            visiting.add(name)
            types[name] = infer(program.variables[name], depth + 1)
            visiting.remove(name)
        return types[name]

    def infer(expression: Expression, depth: int = 0) -> ResolvedType:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise LogicError("Logic exceeds the node or dependency-depth limit", expression)
        if isinstance(expression, LiteralExpression):
            remember_height(expression, 0)
            source_sizes[id(expression)] = (
                len(f"image({json.dumps(expression.value.image_asset)})")
                if isinstance(expression.value, ImageValue)
                else len(json.dumps(expression.value, ensure_ascii=False, allow_nan=False))
            )
            return value_type(expression.value)
        if isinstance(expression, ReferenceExpression):
            result = reference(expression.name, expression, depth)
            definition = program.variables.get(expression.name)
            remember_height(expression, heights[id(definition)] + 1 if definition else 0)
            source_sizes[id(expression)] = len(expression.name)
            return result
        if isinstance(expression, PropertyExpression):
            target = target_ids.get(expression.target)
            readable = (
                (
                    target.readable_properties
                    if target.readable_properties is not None
                    else target.properties
                )
                if target
                else {}
            )
            if expression.property not in readable:
                raise LogicError(
                    f"Property {aliases.get(expression.target, expression.target)}.{expression.property} cannot be read during logic",
                    expression,
                )
            result = infer_property(expression.target, expression.property, depth, expression)
            binding = bindings.get((expression.target, expression.property))
            remember_height(expression, heights[id(binding.expression)] + 1 if binding else 0)
            source_sizes[id(expression)] = (
                len(aliases[expression.target]) + 1 + len(expression.property)
            )
            return result
        operation = OPERATIONS.get(expression.operation)
        if operation is None:
            raise LogicError(f"Unknown operation {expression.operation}", expression)
        if (
            not operation.minimum_arguments
            <= len(expression.arguments)
            <= operation.maximum_arguments
        ):
            raise LogicError(f"Incorrect argument count for {operation.name}", expression)
        args: list[ResolvedType] = [infer(arg, depth + 1) for arg in expression.arguments]
        remember_height(expression, 1 + max(heights[id(arg)] for arg in expression.arguments))
        overhead = (
            len(INFIX_SYMBOLS[operation.name]) + 4
            if operation.name in INFIX_SYMBOLS
            else 3
            if operation.name == "negate"
            else 6
            if operation.name == "not"
            else len(operation.name) + 2 + 2 * (len(expression.arguments) - 1)
        )
        source_sizes[id(expression)] = overhead + sum(
            source_sizes[id(arg)] for arg in expression.arguments
        )
        if operation.signature == "presence":
            return "boolean"
        if operation.signature == "conditional":
            if args[0] != "boolean":
                raise LogicError("if requires a boolean condition", expression)
            if args[1] != args[2] and "null" not in args[1:]:
                raise LogicError("Both if branches must have compatible types", expression)
            return args[2] if args[1] == "null" else args[1]
        if operation.signature == "equality":
            if args[0] != args[1] and "null" not in args:
                raise LogicError("Equality requires compatible types", expression)
            return "boolean"
        required = "boolean" if operation.signature == "boolean" else "number"
        if any(arg != required for arg in args):
            raise LogicError(f"{operation.name} requires {required} arguments", expression)
        return "number" if operation.signature == "numeric" else "boolean"

    def infer_property(
        target_id: str, name: str, depth: int, expression: Expression
    ) -> ResolvedType:
        key = (target_id, name)
        marker = f"property:{target_id}.{name}"
        if marker in visiting:
            raise LogicError(
                f"Circular dependency involving {aliases[target_id]}.{name}", expression
            )
        if key in property_types:
            return property_types[key]
        binding = bindings.get(key)
        target = target_ids[target_id]
        if binding is None:
            readable = (
                target.readable_properties
                if target.readable_properties is not None
                else target.properties
            )
            return readable[name]
        visiting.add(marker)
        result_type = infer(binding.expression, depth + 1)
        visiting.remove(marker)
        expected = target.properties[name]
        if result_type != expected and not (expected == "image" and result_type == "null"):
            raise LogicError(f"{name} requires a {expected} value", binding.expression)
        property_types[key] = expected
        return expected

    for name, expression in program.variables.items():
        reference(name, expression, -1)
    for binding in program.bindings:
        infer_property(binding.target, binding.property, -1, binding.expression)
    lines = [
        8 + len(name) + source_sizes[id(expression)]
        for name, expression in program.variables.items()
    ]
    if lines and program.bindings:
        lines.append(0)
    lines.extend(
        5
        + len(aliases[binding.target])
        + len(binding.property)
        + source_sizes[id(binding.expression)]
        for binding in program.bindings
    )
    if sum(lines) + max(0, len(lines) - 1) > MAX_SOURCE:
        raise LogicError("Formatted logic exceeds the source-size limit")
    return types


@dataclass(frozen=True)
class Evaluation:
    inputs: dict[str, Value]
    variables: dict[str, Value]
    properties: dict[str, dict[str, Value]]


_BINARY_NUMERIC: dict[str, Callable[[float, float], float]] = {
    "add": operator.add,
    "subtract": operator.sub,
    "multiply": operator.mul,
    "divide": operator.truediv,
    "min": min,
    "max": max,
}
_UNARY_NUMERIC: dict[str, Callable[[float], float]] = {
    "negate": operator.neg,
    "abs": abs,
    "round": round,
}
_COMPARISONS: dict[str, Callable[[float, float], bool]] = {
    "less": operator.lt,
    "less_equal": operator.le,
    "greater": operator.gt,
    "greater_equal": operator.ge,
}


def evaluate_program(
    program: Program,
    fields: list[LogicInput],
    targets: dict[str, Target],
    data: Mapping[str, object],
    *,
    samples: bool = False,
    property_values: Mapping[str, Mapping[str, Value]] | None = None,
    property_keys: set[tuple[str, str]] | None = None,
    variable_names: set[str] | None = None,
) -> Evaluation:
    validate_program(program, fields, targets)
    inputs = resolve_inputs(fields, data, samples=samples)
    variables: dict[str, Value] = {}
    bindings = {(binding.target, binding.property): binding for binding in program.bindings}
    resolved_properties: dict[tuple[str, str], Value] = {}
    target_ids = {target.id: target for target in targets.values()}
    steps = 0

    def property_value(target: str, name: str, expression: Expression, depth: int) -> Value:
        key = (target, name)
        if key in resolved_properties:
            return resolved_properties[key]
        binding = bindings.get(key)
        if binding is not None:
            value = evaluate(binding.expression, depth + 1)
            expected = target_ids[target].properties[name]
        else:
            available = (property_values or {}).get(target, {})
            if name not in available:
                raise LogicError(f"No saved value for property {target}.{name}", expression)
            value = available[name]
            definition = target_ids[target]
            expected = (
                definition.readable_properties
                if definition.readable_properties is not None
                else definition.properties
            )[name]
        bounded_value(value)
        if value_type(value) != expected and not (
            value is None and (expected == "image" or binding is None)
        ):
            raise LogicError(f"{name} requires a present {expected} value", expression)
        resolved_properties[key] = value
        return value

    def evaluate(expression: Expression, depth: int = 0) -> Value:
        nonlocal steps
        steps += 1
        if steps > MAX_NODES * 2 or depth > MAX_DEPTH:
            raise LogicError("Logic exceeds the evaluation limit", expression)
        if isinstance(expression, LiteralExpression):
            return expression.value
        if isinstance(expression, ReferenceExpression):
            if expression.name in inputs:
                return inputs[expression.name]
            if expression.name not in variables:
                variables[expression.name] = evaluate(program.variables[expression.name], depth + 1)
            return variables[expression.name]
        if isinstance(expression, PropertyExpression):
            return property_value(expression.target, expression.property, expression, depth)
        operation, args = expression.operation, expression.arguments
        first = evaluate(args[0], depth + 1)
        if operation == "filled":
            return filled(first)
        if operation in ("if", "and", "or", "not"):
            if not isinstance(first, bool):
                raise LogicError(f"{operation} requires a present boolean condition", expression)
            if operation == "if":
                return evaluate(args[1] if first else args[2], depth + 1)
            if operation == "not":
                return not first
            if (operation == "and" and not first) or (operation == "or" and first):
                return first
            second = evaluate(args[1], depth + 1)
            if not isinstance(second, bool):
                raise LogicError(f"{operation} requires present boolean arguments", expression)
            return second
        values = [first, *(evaluate(arg, depth + 1) for arg in args[1:])]
        if operation in ("equal", "not_equal"):
            equal = values[0] == values[1]
            return equal if operation == "equal" else not equal
        numbers: list[float] = []
        for value in values:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise LogicError(f"{operation} requires present number arguments", expression)
            numbers.append(float(value))
        if operation in _COMPARISONS:
            return _COMPARISONS[operation](*numbers)
        try:
            result = (
                _UNARY_NUMERIC[operation](numbers[0])
                if operation in _UNARY_NUMERIC
                else _BINARY_NUMERIC[operation](numbers[0], numbers[1])
            )
            return bounded_value(result)
        except (ArithmeticError, ValueError) as error:
            raise LogicError(
                f"{operation} produced an invalid number (check division by zero and numeric limits)",
                expression,
            ) from error

    for name, expression in program.variables.items():
        if variable_names is not None and name not in variable_names:
            continue
        if name not in variables:
            variables[name] = evaluate(expression)
    properties: dict[str, dict[str, Value]] = {}
    for binding in program.bindings:
        if property_keys is not None and (binding.target, binding.property) not in property_keys:
            continue
        value = property_value(binding.target, binding.property, binding.expression, -1)
        properties.setdefault(binding.target, {})[binding.property] = value
    return Evaluation(inputs=inputs, variables=variables, properties=properties)
