"""Source diagnostics and expression identity for the two authoring surfaces."""

from collections.abc import Iterator
from uuid import uuid4

from app.templates.logic_engine import LogicError
from app.templates.logic_schema import CallExpression, Expression, LiteralExpression, Program


def expressions(program: Program) -> Iterator[Expression]:
    def walk(expression: Expression) -> Iterator[Expression]:
        yield expression
        if isinstance(expression, CallExpression):
            for argument in expression.arguments:
                yield from walk(argument)

    for expression in program.variables.values():
        yield from walk(expression)
    for binding in program.bindings:
        yield from walk(binding.expression)


def identity(expression: Expression) -> str:
    # Source spans and canvas IDs do not affect the meaning of an expression.
    if isinstance(expression, CallExpression):
        return f"{expression.operation}({','.join(identity(arg) for arg in expression.arguments)})"
    if (
        isinstance(expression, LiteralExpression)
        and isinstance(expression.value, (int, float))
        and not isinstance(expression.value, bool)
    ):
        return f"number:{float(expression.value)}"
    return expression.model_dump_json(exclude={"span", "node_id"})


def same_program(left: Program, right: Program) -> bool:
    def signature(program: Program) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
        return (
            sorted((name, identity(value)) for name, value in program.variables.items()),
            sorted(
                (item.target, item.property, identity(item.expression)) for item in program.bindings
            ),
        )

    return signature(left) == signature(right)


def reconcile_program(previous: Program, program: Program) -> Program:
    """Preserve matching node IDs; changed siblings must not share an old identity."""
    result = program.model_copy(deep=True)
    old_nodes = list(expressions(previous))
    exact = {identity(node): node.node_id for node in old_nodes if node.node_id}
    retained = {identity(node) for node in expressions(result)}
    old_meanings = {node.node_id: identity(node) for node in old_nodes if node.node_id}
    used: dict[str, str] = {}

    def reconcile(node: Expression, old: Expression | None = None) -> None:
        meaning = identity(node)
        identifier = (
            old.node_id if old is not None and identity(old) == meaning else None
        ) or exact.get(meaning)
        if identifier is None and old is not None and type(old) is type(node):
            candidate = old.node_id
            if candidate and (
                old_meanings[candidate] not in retained or old_meanings[candidate] == meaning
            ):
                identifier = candidate
        if identifier is None or used.get(identifier, meaning) != meaning:
            identifier = str(uuid4())
        node.node_id = identifier
        used[identifier] = meaning
        if isinstance(node, CallExpression):
            before = old.arguments if isinstance(old, CallExpression) else []
            for index, argument in enumerate(node.arguments):
                reconcile(argument, before[index] if index < len(before) else None)

    for name, expression in result.variables.items():
        reconcile(expression, previous.variables.get(name))
    bindings = {
        (binding.target, binding.property): binding.expression for binding in previous.bindings
    }
    for binding in result.bindings:
        reconcile(binding.expression, bindings.get((binding.target, binding.property)))
    return result


def source_diagnostic(error: LogicError, source: str) -> dict[str, str | int]:
    start = max(0, min(error.offset or 0, len(source)))
    end = min(start + 1, len(source))
    prefix = source[:start]
    # Browser editors index UTF-16 code units, whereas Python indexes code points.
    return {
        "message": str(error),
        "from": len(prefix.encode("utf-16-le", errors="surrogatepass")) // 2,
        "to": len(source[:end].encode("utf-16-le", errors="surrogatepass")) // 2,
        "line": prefix.count("\n") + 1,
        "column": len(prefix.rsplit("\n", 1)[-1].encode("utf-16-le", errors="surrogatepass")) // 2
        + 1,
        "severity": "error",
    }
