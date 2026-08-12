"""Structured logging.

Emits one JSON object per line in every non-development configuration so logs are
ingestible without a grok pattern. The correlation id is pulled from the request
context automatically, so call sites never have to thread it through.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from typing import Any, Final

from pathable_api.core.request_context import get_request_id

#: Attributes present on every ``LogRecord``; anything outside this set was passed
#: by a caller via ``extra=`` and is therefore worth emitting.
_STANDARD_RECORD_FIELDS: Final = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

#: Loggers whose handlers we replace so their output is structured too, rather
#: than uvicorn's default human-oriented formatting appearing alongside JSON.
_MANAGED_LOGGERS: Final = ("uvicorn", "uvicorn.error", "uvicorn.access", "alembic")


class JsonLogFormatter(logging.Formatter):
    """Render records as single-line JSON."""

    def __init__(self, *, service: str, version: str, environment: str) -> None:
        super().__init__()
        self._service = service
        self._version = version
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service,
            "version": self._version,
            "environment": self._environment,
        }

        request_id = get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info is not None:
            payload["stack"] = self.formatStack(record.stack_info)

        # `default=str` keeps a stray non-serialisable value from turning a log
        # call into a crash inside the logging machinery.
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleLogFormatter(logging.Formatter):
    """Compact human-readable format for local development."""

    def __init__(self) -> None:
        super().__init__(fmt="%(asctime)s %(levelname)-8s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        request_id = get_request_id()
        return f"{base}  [req={request_id}]" if request_id else base


def build_formatter(
    *, log_format: str, service: str, version: str, environment: str
) -> logging.Formatter:
    """Return the formatter matching the configured ``log_format``."""
    if log_format == "console":
        return ConsoleLogFormatter()
    return JsonLogFormatter(service=service, version=version, environment=environment)


def configure_logging(
    *, level: str, log_format: str, service: str, version: str, environment: str
) -> None:
    """Install the structured handler on the root logger and framework loggers.

    Safe to call more than once: existing handlers are replaced rather than
    appended, which prevents duplicated lines under uvicorn's reloader.
    """
    formatter = build_formatter(
        log_format=log_format, service=service, version=version, environment=environment
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    for logger_name in _MANAGED_LOGGERS:
        logger = logging.getLogger(logger_name)
        for existing in list(logger.handlers):
            logger.removeHandler(existing)
        logger.propagate = True
        logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced application logger."""
    return logging.getLogger(name)
