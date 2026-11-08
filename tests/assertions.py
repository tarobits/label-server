"""Assertions that preserve the checked type for downstream test expectations."""

from typing import TypeVar

T = TypeVar("T")


def require_value(value: T | None) -> T:
    assert value is not None
    return value
