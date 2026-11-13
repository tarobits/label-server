"""Lossless binary envelopes for database backup rows and migration checksums."""

import base64
from typing import Any

from app.i18n import Message


def encode_binary(value: Any) -> dict[str, str]:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$label_bytes": base64.b64encode(value).decode("ascii")}
    raise TypeError(f"Unsupported database value type: {type(value).__name__}")


def decode_binary(value: dict[str, Any]) -> Any:
    if set(value) == {"$label_bytes"}:
        return base64.b64decode(value["$label_bytes"], validate=True)
    return value


def check_packet_size(values: list[Any] | tuple[Any, ...], limit: int | None) -> None:
    if limit is None or not any(
        isinstance(value, (bytes, bytearray, memoryview)) for value in values
    ):
        return
    # PyMySQL escapes literal values. Reserve room for SQL and at most two bytes
    # per input byte, including escaping, rather than waiting for a disconnect.
    needed = 65536 + 2 * sum(
        len(value)
        if isinstance(value, (bytes, bytearray, memoryview))
        else len(str(value).encode("utf-8"))
        for value in values
    )
    if needed > limit:
        raise ValueError(
            Message(
                "logicErrors.mariadbMaxAllowedPacketIsTooSmallForAnAssetIncreaseItToAtLeastValue1BytesAndRetry",
                value1=needed,
            )
        )
