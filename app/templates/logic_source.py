"""A small source language for the same expression trees used by visual nodes.

This parser supports assignments and pure expressions only. It never calls eval,
exec, or a host-language compiler. Output target aliases resolve to stable IDs.
"""

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.i18n import Message
from app.templates.logic_engine import INFIX_SYMBOLS, LogicError, validate_program
from app.templates.logic_schema import (
    MAX_DEPTH,
    MAX_NODES,
    MAX_SOURCE,
    Binding,
    CallExpression,
    Expression,
    ImageValue,
    LiteralExpression,
    LogicInput,
    Program,
    PropertyExpression,
    ReferenceExpression,
    Span,
    Target,
)

_TOKEN = re.compile(
    r"(?P<space>\s+)|(?P<comment>//[^\n]*)|"
    r"(?P<number>(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)|"
    r'(?P<string>"(?:[^"\\\n]|\\.)*")|'
    r"(?P<name>[A-Za-z][A-Za-z0-9_]*)|"
    r"(?P<operator>==|!=|<=|>=|[+*/<>=;,.()\-])"
)
_BINARY = {
    "or": (1, "or"),
    "and": (2, "and"),
    "==": (3, "equal"),
    "!=": (3, "not_equal"),
    "<": (4, "less"),
    "<=": (4, "less_equal"),
    ">": (4, "greater"),
    ">=": (4, "greater_equal"),
    "+": (5, "add"),
    "-": (5, "subtract"),
    "*": (6, "multiply"),
    "/": (6, "divide"),
}
_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int


def tokenize(source: str) -> list[Token]:
    if len(source) > MAX_SOURCE:
        raise LogicError(
            Message("logicErrors.logicSourceExceedsValue1Characters", value1=MAX_SOURCE), offset=0
        )
    tokens: list[Token] = []
    offset = 0
    while offset < len(source):
        match = _TOKEN.match(source, offset)
        if match is None:
            raise LogicError(
                Message("logicErrors.unexpectedCharacterOrUnterminatedString"), offset=offset
            )
        kind = match.lastgroup
        assert kind is not None
        if kind not in ("space", "comment"):
            tokens.append(Token(kind, match[0], offset, match.end()))
            if len(tokens) > MAX_NODES * 6:
                raise LogicError(Message("logicErrors.logicSourceHasTooManyTokens"), offset=offset)
        offset = match.end()
    tokens.append(Token("end", "", offset, offset))
    return tokens


class Parser:
    def __init__(self, source: str, targets: dict[str, Target]):
        self.tokens = tokenize(source)
        self.position = 0
        self.nodes = 0
        self.targets = targets

    @property
    def token(self) -> Token:
        return self.tokens[self.position]

    def take(self) -> Token:
        token = self.token
        if token.kind != "end":
            self.position += 1
        return token

    def expect(self, value: str) -> Token:
        if self.token.text != value:
            raise LogicError(
                Message("logicErrors.expectedValue1", value1=value), offset=self.token.start
            )
        return self.take()

    def name(self) -> Token:
        if self.token.kind != "name" or not _SYMBOL.fullmatch(self.token.text):
            raise LogicError(
                Message("logicErrors.expectedAnIdentifierOfAtMost40Characters"),
                offset=self.token.start,
            )
        return self.take()

    def count(self, expression: Expression) -> Expression:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise LogicError(Message("logicErrors.logicHasTooManyExpressionNodes"), expression)
        return expression

    def expression(self, minimum: int = 0, depth: int = 0) -> Expression:
        # Formatting adds parentheses around operators. Bound syntactic nesting
        # separately; validate_program enforces the actual expression/dependency depth.
        if depth > MAX_DEPTH * 2 + 2:
            raise LogicError(
                Message("logicErrors.expressionNestingExceedsTheLimit"), offset=self.token.start
            )
        start = self.token.start
        token = self.take()
        left: Expression
        if token.text in ("-", "not"):
            # Boolean negation binds below comparisons, as in `not count > 2`.
            argument = self.expression(7 if token.text == "-" else 3, depth + 1)
            span = Span(start=start, end=self.tokens[self.position - 1].end)
            if (
                token.text == "-"
                and isinstance(argument, LiteralExpression)
                and isinstance(argument.value, (int, float))
                and not isinstance(argument.value, bool)
            ):
                left = LiteralExpression(value=-argument.value, span=span)
            else:
                left = self.count(
                    CallExpression(
                        operation="negate" if token.text == "-" else "not",
                        arguments=[argument],
                        span=span,
                    )
                )
        elif token.text == "(":
            left = self.expression(0, depth + 1)
            self.expect(")")
        elif token.kind in ("number", "string") or token.text in ("true", "false", "null"):
            try:
                value = float(token.text) if token.kind == "number" else json.loads(token.text)
                left = self.count(
                    LiteralExpression(value=value, span=Span(start=start, end=token.end))
                )
            except (ValueError, ValidationError) as error:
                raise LogicError(
                    Message("logicErrors.invalidOrOutOfRangeLiteral"), offset=start
                ) from error
        elif token.kind == "name":
            if not _SYMBOL.fullmatch(token.text):
                raise LogicError(Message("logicErrors.identifierExceeds40Characters"), offset=start)
            if self.token.text == ".":
                self.take()
                property_name = self.name()
                target = self.targets.get(token.text)
                if target is None:
                    raise LogicError(
                        Message("logicErrors.unknownPropertyTargetValue1", value1=token.text),
                        offset=start,
                    )
                left = self.count(
                    PropertyExpression(
                        target=target.id,
                        property=property_name.text,
                        span=Span(start=start, end=property_name.end),
                    )
                )
            elif self.token.text == "(":
                self.take()
                arguments: list[Expression] = []
                if self.token.text != ")":
                    while True:
                        if len(arguments) >= 3:
                            raise LogicError(
                                Message("logicErrors.functionsAcceptAtMostThreeArguments"),
                                offset=start,
                            )
                        arguments.append(self.expression(0, depth + 1))
                        if self.token.text != ",":
                            break
                        self.take()
                end = self.expect(")").end
                span = Span(start=start, end=end)
                if token.text == "image":
                    if (
                        len(arguments) != 1
                        or not isinstance(arguments[0], LiteralExpression)
                        or not isinstance(arguments[0].value, str)
                    ):
                        raise LogicError(
                            Message("logicErrors.imageRequiresALiteralUploadedAssetID"),
                            offset=start,
                        )
                    try:
                        self.nodes -= 1  # The constructor replaces its literal argument.
                        left = self.count(
                            LiteralExpression(
                                value=ImageValue(image_asset=arguments[0].value), span=span
                            )
                        )
                    except ValidationError as error:
                        raise LogicError(
                            Message("logicErrors.invalidUploadedImageAssetID"), offset=start
                        ) from error
                else:
                    left = self.count(
                        CallExpression(operation=token.text, arguments=arguments, span=span)
                    )
            else:
                left = self.count(
                    ReferenceExpression(name=token.text, span=Span(start=start, end=token.end))
                )
        else:
            raise LogicError(
                Message("logicErrors.expectedAValueVariableOrExpression"), offset=start
            )
        while self.token.text in _BINARY:
            precedence, operation = _BINARY[self.token.text]
            if precedence < minimum:
                break
            self.take()
            right = self.expression(precedence + 1, depth + 1)
            left = self.count(
                CallExpression(
                    operation=operation,
                    arguments=[left, right],
                    span=Span(start=start, end=self.tokens[self.position - 1].end),
                )
            )
        return left

    def program(self) -> Program:
        variables: dict[str, Expression] = {}
        bindings: list[Binding] = []
        while self.token.kind != "end":
            if self.token.text == "let":
                self.take()
                name = self.name()
                if name.text in variables:
                    raise LogicError(
                        Message(
                            "logicErrors.duplicateIntermediateVariableValue1", value1=name.text
                        ),
                        offset=name.start,
                    )
                if len(variables) >= 64:
                    raise LogicError(
                        Message("logicErrors.atMost64IntermediateVariablesAreSupported"),
                        offset=name.start,
                    )
                self.expect("=")
                variables[name.text] = self.expression()
            else:
                alias = self.name()
                self.expect(".")
                property_name = self.name()
                target = self.targets.get(alias.text)
                if target is None:
                    raise LogicError(
                        Message("logicErrors.unknownOutputTargetValue1", value1=alias.text),
                        offset=alias.start,
                    )
                if len(bindings) >= 128:
                    raise LogicError(
                        Message("logicErrors.atMost128BindingsAreSupported"), offset=alias.start
                    )
                self.expect("=")
                bindings.append(
                    Binding(
                        target=target.id, property=property_name.text, expression=self.expression()
                    )
                )
            self.expect(";")
        return Program(variables=variables, bindings=bindings)


def compile_source(source: str, fields: list[LogicInput], targets: dict[str, Target]) -> Program:
    program = Parser(source, targets).program()
    validate_program(program, fields, targets)
    return program


def format_source(program: Program, fields: list[LogicInput], targets: dict[str, Target]) -> str:
    """Canonical formatting; editor layout and source spans do not affect semantics."""
    validate_program(program, fields, targets)
    aliases = {target.id: alias for alias, target in targets.items()}
    if any(not _SYMBOL.fullmatch(alias) for alias in aliases.values()):
        raise LogicError(Message("logicErrors.targetAliasesMustBeValidIdentifiers"))

    def source(expression: Expression) -> str:
        if isinstance(expression, LiteralExpression):
            value = expression.value
            if isinstance(value, ImageValue):
                return f"image({json.dumps(value.image_asset)})"
            return json.dumps(value, ensure_ascii=False, allow_nan=False)
        if isinstance(expression, ReferenceExpression):
            return expression.name
        if isinstance(expression, PropertyExpression):
            return f"{aliases[expression.target]}.{expression.property}"
        args = [source(argument) for argument in expression.arguments]
        if expression.operation in INFIX_SYMBOLS:
            return f"({args[0]} {INFIX_SYMBOLS[expression.operation]} {args[1]})"
        if expression.operation == "negate":
            return f"(-{args[0]})"
        if expression.operation == "not":
            return f"(not {args[0]})"
        return f"{expression.operation}({', '.join(args)})"

    lines = [
        f"let {name} = {source(expression)};" for name, expression in program.variables.items()
    ]
    if lines and program.bindings:
        lines.append("")
    lines.extend(
        f"{aliases[binding.target]}.{binding.property} = {source(binding.expression)};"
        for binding in program.bindings
    )
    result = "\n".join(lines)
    if len(result) > MAX_SOURCE:
        raise LogicError(Message("logicErrors.formattedLogicExceedsTheSourceSizeLimit"))
    return result
