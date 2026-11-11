"""Shared application and HTTP access logging policy for either server role."""

import logging
from typing import Annotated, Literal

from pydantic import BeforeValidator

LogLevel = Annotated[
    Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    BeforeValidator(lambda value: value.upper() if isinstance(value, str) else value),
]


class AccessLogFilter(logging.Filter):
    def __init__(self, level: str) -> None:
        super().__init__()
        self.threshold = logging.getLevelNamesMapping()[level]

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[4], int):
            client, method, target, version, status = args
            assert isinstance(status, int)
            # Request query strings can contain secrets; never include them in logs.
            record.args = (client, method, str(target).split("?", 1)[0], version, status)
            level = (
                logging.ERROR
                if status >= 500
                else logging.WARNING
                if status >= 400
                else logging.DEBUG
                if 200 <= status < 300
                else logging.INFO
            )
            record.levelno = level
            record.levelname = logging.getLevelName(level)
        return record.levelno >= self.threshold


def configure_logging(level: str) -> None:
    threshold = logging.getLevelNamesMapping()[level]
    for name in ("app", "companion"):
        logger = logging.getLogger(name)
        logger.setLevel(threshold)
        if not logger.hasHandlers():
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
            logger.addHandler(handler)
    logging.getLogger("uvicorn.error").setLevel(threshold)
    access = logging.getLogger("uvicorn.access")
    # Uvicorn emits every access event at INFO. Classify before applying the
    # deployment threshold so ERROR-only deployments still see HTTP 5xx events.
    access.setLevel(logging.DEBUG)
    for existing in list(access.filters):
        if isinstance(existing, AccessLogFilter):
            access.removeFilter(existing)
    access.addFilter(AccessLogFilter(level))
