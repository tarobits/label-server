"""Bounded, optional translation metadata for durable printer reasons."""

import json
from typing import Any, overload

from app.i18n import JoinedMessages, Language, Message, catalog, translate


def reason_descriptor(reason: object) -> dict[str, Any] | None:
    return reason.descriptor() if isinstance(reason, (Message, JoinedMessages)) else None


def restore_reason(text: str | None, descriptor: Any) -> str | None:
    """Keep legacy text and ignore corrupt, unsupported or stale metadata safely."""
    if not text or descriptor is None:
        return text

    def read(value: Any, depth: int = 0) -> Message | JoinedMessages:
        if depth > 4 or not isinstance(value, dict):
            raise ValueError
        if "messages" in value:
            children = value["messages"]
            separator = value.get("separator", "; ")
            if not isinstance(children, list) or not 1 <= len(children) <= 16:
                raise ValueError
            if separator not in ("; ", ", ", ". "):
                raise ValueError
            return JoinedMessages([read(child, depth + 1) for child in children], separator)
        key = value.get("key")
        if (
            not isinstance(key, str)
            or not key.startswith("printerMessages.")
            or key not in catalog("en")
        ):
            raise ValueError
        parameters = value.get("parameters", {})
        nested = value.get("localized_parameters", {})
        if not isinstance(parameters, dict) or not isinstance(nested, dict) or len(parameters) > 16:
            raise ValueError
        if not set(nested).issubset(parameters):
            raise ValueError
        if any(
            not isinstance(item, (str, int, float, bool, type(None)))
            for item in parameters.values()
        ):
            raise ValueError
        return Message(
            key, **{**parameters, **{name: read(item, depth + 1) for name, item in nested.items()}}
        )

    try:
        if len(json.dumps(descriptor, allow_nan=False)) > 8192:
            return text
        message = read(descriptor)
        return message if str(message) == text else text
    except (ValueError, TypeError, KeyError, RecursionError):
        return text


@overload
def localize_status(status: dict[str, Any], language: Language) -> dict[str, Any]: ...


@overload
def localize_status(status: None, language: Language) -> None: ...


def localize_status(status: dict[str, Any] | None, language: Language) -> dict[str, Any] | None:
    if status is None:
        return None
    result = dict(status)
    for field in ("error", "blocker", "printer_error"):
        if field in result:
            result[field] = translate(
                restore_reason(result[field], result.get(field + "_translation")), language
            )
    return result
