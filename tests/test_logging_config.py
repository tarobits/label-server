import logging

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.logging_config import AccessLogFilter, configure_logging
from companion.config import Settings as CompanionSettings


@pytest.mark.parametrize("threshold", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
@pytest.mark.parametrize("status", [200, 201, 204, 302, 304, 400, 401, 409, 500, 503])
def test_access_logs_classify_status_and_apply_deployment_threshold(threshold, status):
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("client", "GET", "/api/status?private=test-only", "1.1", status),
        None,
    )
    expected = (
        logging.ERROR
        if status >= 500
        else logging.WARNING
        if status >= 400
        else logging.DEBUG
        if status < 300
        else logging.INFO
    )
    accepted = AccessLogFilter(threshold).filter(record)
    assert accepted == (expected >= logging.getLevelNamesMapping()[threshold])
    assert record.levelno == expected
    assert record.levelname == logging.getLevelName(expected)
    assert "private" not in record.getMessage()


def test_uvicorn_info_emitter_still_logs_errors_at_error_threshold(caplog):
    names = ("app", "companion", "uvicorn.access", "uvicorn.error")
    saved = [
        (
            logging.getLogger(name),
            logging.getLogger(name).level,
            list(logging.getLogger(name).handlers),
            list(logging.getLogger(name).filters),
            logging.getLogger(name).propagate,
        )
        for name in names
    ]
    try:
        configure_logging("INFO")
        configure_logging("ERROR")
        access = logging.getLogger("uvicorn.access")
        access.handlers = [caplog.handler]
        access.propagate = False
        assert sum(isinstance(item, AccessLogFilter) for item in access.filters) == 1
        for status in (200, 404, 500):
            access.info('%s - "%s %s HTTP/%s" %d', "client", "GET", "/api/status", "1.1", status)
        assert [(record.levelname, record.args[-1]) for record in caplog.records] == [
            ("ERROR", 500)
        ]
        caplog.clear()
        configure_logging("WARNING")
        logging.getLogger("companion").info("routine")
        logging.getLogger("companion").warning("attention")
        logging.getLogger("app").error("failed")
        assert caplog.messages == ["attention", "failed"]
    finally:
        for logger, level, handlers, filters, propagate in saved:
            logger.setLevel(level)
            logger.handlers = handlers
            logger.filters = filters
            logger.propagate = propagate


def test_log_levels_are_independently_configured_and_validated(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setitem(CompanionSettings.model_config, "env_file", None)
    monkeypatch.setenv("LABEL_LOG_LEVEL", "error")
    monkeypatch.setenv("LABEL_COMPANION_LOG_LEVEL", "debug")
    assert Settings().log_level == "ERROR"
    assert (
        CompanionSettings(server_url="http://localhost", api_key=SecretStr("fixture")).log_level
        == "DEBUG"
    )
    with pytest.raises(ValidationError):
        Settings.model_validate({"log_level": "VERBOSE"})
