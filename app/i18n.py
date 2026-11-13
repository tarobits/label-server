"""Shared message catalogs; stored identifiers and user content are never translated."""

import json
import re
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Sequence, cast

from fastapi import Request

Language = Literal["en", "de"]


def negotiate(value: str) -> Language:
    candidates = []
    for position, part in enumerate(value[:2048].split(",")):
        bits = part.strip().split(";")
        base = bits[0].lower().split("-")[0]
        try:
            quality = float(
                next((b.strip()[2:] for b in bits[1:] if b.strip().startswith("q=")), "1")
            )
        except ValueError:
            continue
        if base in ("en", "de") and 0 < quality <= 1:
            candidates.append((-quality, position, base))
    return cast(Language, min(candidates)[2]) if candidates else "en"


def request_language(request: Request) -> Language:
    return negotiate(request.headers.get("accept-language", "en"))


def user_language(user: Any) -> Language:
    preference = getattr(user, "language", "browser")
    return negotiate(
        preference
        if preference in ("en", "de")
        else (getattr(user, "browser_language", "en") or "en")
    )


@lru_cache(maxsize=2)
def catalog(language: Language) -> dict[str, str]:
    root = Path(__file__).resolve().parents[1] / "lang"
    if not root.is_dir():
        root = Path(sysconfig.get_path("data")) / "share" / "label-printer-server" / "lang"
    data = json.loads((root / f"{language}.json").read_text(encoding="utf-8"))
    result: dict[str, str] = {}

    def flatten(value: dict, prefix: str = "") -> None:
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(child, dict):
                flatten(child, path)
            else:
                result[path] = child

    flatten(data)
    return result


def render(key: str, language: Language = "en", **parameters: Any) -> str:
    parameters = {name: translate(value, language) for name, value in parameters.items()}
    message = catalog(language).get(key, catalog("en").get(key, key))
    # Both supported languages use singular for one and plural otherwise.
    variants = re.split(r"\s+\|\s+", message)
    if len(variants) > 1:
        count = parameters.get("count", 0)
        index = (
            (0 if count == 1 else 1)
            if len(variants) == 2
            else (0 if count == 0 else 1 if count == 1 else 2)
        )
        message = variants[min(index, len(variants) - 1)]
    # One substitution pass prevents parameters containing braces from being interpreted.
    return re.sub(
        r"\{'([^']*)'\}|\{(\w+)\}",
        lambda match: match[1] if match[1] is not None else str(parameters.get(match[2], match[0])),
        message,
    )


class Message(str):
    """English-compatible value with a durable, parameterized localization descriptor."""

    key: str
    parameters: dict[str, Any]

    def __new__(cls, key: str, **parameters: Any):
        value = super().__new__(cls, render(key, **parameters))
        value.key = key
        value.parameters = parameters
        return value

    def descriptor(self) -> dict[str, Any]:
        nested = {
            name: value.descriptor()
            for name, value in self.parameters.items()
            if isinstance(value, (Message, JoinedMessages))
        }
        return {
            "key": self.key,
            "parameters": {
                name: str(value) if name in nested else value
                for name, value in self.parameters.items()
            },
            **({"localized_parameters": nested} if nested else {}),
        }


class JoinedMessages(str):
    """A list of explicit messages; user-supplied strings never become descriptors."""

    messages: Sequence["Message | JoinedMessages"]
    separator: str

    def __new__(cls, messages: Sequence["Message | JoinedMessages"], separator: str = "; "):
        value = super().__new__(cls, separator.join(messages))
        value.messages = messages
        value.separator = separator
        return value

    def descriptor(self) -> dict[str, Any]:
        return {
            "messages": [message.descriptor() for message in self.messages],
            "separator": self.separator,
        }


def translate(value: Any, language: Language) -> Any:
    if isinstance(value, JoinedMessages):
        return value.separator.join(translate(message, language) for message in value.messages)
    if isinstance(value, Message):
        return render(value.key, language, **value.parameters)
    if isinstance(value, dict):
        return {key: translate(child, language) for key, child in value.items()}
    if isinstance(value, list):
        return [translate(child, language) for child in value]
    return value


def validation_details(
    errors: Sequence[dict[str, Any]], language: Language, *, sensitive: bool
) -> list[dict[str, Any]]:
    """Localize validation without adding submitted values to sensitive responses."""
    result = []
    for issue in errors:
        detail = {key: issue[key] for key in ("type", "loc", "msg")} if sensitive else dict(issue)
        context = issue.get("ctx", {})
        error = context.get("error")
        if isinstance(error, Exception) and isinstance(error_detail(error), Message):
            detail["msg"] = render(
                "validationMessages.valueError",
                language,
                message=translate(error_detail(error), language),
            )
        else:
            parts = issue["type"].split("_")
            key = "validationMessages." + parts[0] + "".join(part.title() for part in parts[1:])
            if key in catalog(language):
                detail["msg"] = render(
                    key,
                    language,
                    **{
                        name: value
                        for name, value in context.items()
                        if name != "error" or not isinstance(value, Exception)
                    },
                )
        result.append(detail)
    return result


def error_detail(error: Exception) -> str:
    """Retain an explicit descriptor when a domain error crosses an HTTP boundary."""
    if len(error.args) == 1 and isinstance(error.args[0], Message):
        return error.args[0]
    return str(error)


async def http_error(request: Request, error: Any) -> Any:
    """Translate explicit messages without guessing at user content or changing status/headers."""
    from starlette.responses import JSONResponse, Response

    if error.status_code in (204, 304):
        return Response(status_code=error.status_code, headers=error.headers)
    return JSONResponse(
        {"detail": translate(error.detail, request_language(request))},
        status_code=error.status_code,
        headers=error.headers,
    )


def notice_text(notice: Any, field: str, language: Language) -> str:
    descriptor = (notice.context or {}).get("i18n", {}).get(field)
    if isinstance(descriptor, dict) and isinstance(descriptor.get("key"), str):
        return render_descriptor(descriptor, language)
    # Historical notices have no descriptor; preserve the recorded text.
    return getattr(notice, field)


def render_descriptor(descriptor: dict[str, Any], language: Language) -> str:
    if "messages" in descriptor:
        return descriptor.get("separator", "; ").join(
            render_descriptor(message, language) for message in descriptor["messages"]
        )
    parameters = dict(descriptor.get("parameters", {}))
    parameters.update(
        {
            name: render_descriptor(value, language)
            for name, value in descriptor.get("localized_parameters", {}).items()
        }
    )
    return render(descriptor["key"], language, **parameters)
