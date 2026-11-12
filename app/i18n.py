"""Shared message catalogs; stored identifiers and user content are never translated."""

import json
import re
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

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
        return {"key": self.key, "parameters": self.parameters}


def translate(value: Any, language: Language) -> Any:
    if isinstance(value, Message):
        return render(value.key, language, **value.parameters)
    return value


def notice_text(notice: Any, field: str, language: Language) -> str:
    descriptor = (notice.context or {}).get("i18n", {}).get(field)
    if isinstance(descriptor, dict) and isinstance(descriptor.get("key"), str):
        return render(descriptor["key"], language, **descriptor.get("parameters", {}))
    # Historical notices have no descriptor; preserve the recorded text.
    return getattr(notice, field)
