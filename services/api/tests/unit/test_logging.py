"""Structured logging output."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from pathable_api.core.logging import (
    ConsoleLogFormatter,
    JsonLogFormatter,
    build_formatter,
    configure_logging,
    get_logger,
)
from pathable_api.core.request_context import reset_request_id, set_request_id


def make_record(
    *,
    message: str = "something happened",
    level: int = logging.INFO,
    extra: dict[str, Any] | None = None,
    exc_info: Any = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="pathable_api.test",
        level=level,
        pathname=__file__,
        lineno=42,
        msg=message,
        args=(),
        exc_info=exc_info,
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return record


@pytest.fixture
def formatter() -> JsonLogFormatter:
    return JsonLogFormatter(service="pathable-api", version="0.1.0", environment="test")


class TestJsonFormatter:
    def test_emits_a_single_json_line(self, formatter: JsonLogFormatter) -> None:
        output = formatter.format(make_record())

        assert "\n" not in output
        assert json.loads(output)["message"] == "something happened"

    def test_includes_service_identity(self, formatter: JsonLogFormatter) -> None:
        payload = json.loads(formatter.format(make_record()))

        assert payload["service"] == "pathable-api"
        assert payload["version"] == "0.1.0"
        assert payload["environment"] == "test"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "pathable_api.test"

    def test_timestamp_is_utc_iso8601(self, formatter: JsonLogFormatter) -> None:
        timestamp = json.loads(formatter.format(make_record()))["timestamp"]

        assert timestamp.endswith("+00:00")

    def test_omits_request_id_outside_a_request(self, formatter: JsonLogFormatter) -> None:
        assert "request_id" not in json.loads(formatter.format(make_record()))

    def test_includes_the_active_request_id(self, formatter: JsonLogFormatter) -> None:
        token = set_request_id("trace-abcdef")
        try:
            payload = json.loads(formatter.format(make_record()))
        finally:
            reset_request_id(token)

        assert payload["request_id"] == "trace-abcdef"

    def test_forwards_caller_supplied_extras(self, formatter: JsonLogFormatter) -> None:
        record = make_record(extra={"http_status": 503, "duration_ms": 12.5})

        payload = json.loads(formatter.format(record))

        assert payload["http_status"] == 503
        assert payload["duration_ms"] == 12.5

    def test_does_not_emit_internal_record_attributes(self, formatter: JsonLogFormatter) -> None:
        payload = json.loads(formatter.format(make_record()))

        assert "pathname" not in payload
        assert "lineno" not in payload
        assert "msg" not in payload

    def test_renders_exception_information(self, formatter: JsonLogFormatter) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = make_record(level=logging.ERROR, exc_info=sys.exc_info())

        payload = json.loads(formatter.format(record))

        assert "ValueError: boom" in payload["exception"]

    def test_non_serialisable_extras_do_not_crash_logging(
        self, formatter: JsonLogFormatter
    ) -> None:
        # A logging call must never be the thing that takes the service down.
        record = make_record(extra={"weird": object()})

        payload = json.loads(formatter.format(record))

        assert isinstance(payload["weird"], str)

    def test_message_interpolation_is_applied(self, formatter: JsonLogFormatter) -> None:
        record = logging.LogRecord(
            name="pathable_api.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="probe took %d ms",
            args=(12,),
            exc_info=None,
        )

        assert json.loads(formatter.format(record))["message"] == "probe took 12 ms"


class TestConsoleFormatter:
    def test_includes_the_message(self) -> None:
        assert "something happened" in ConsoleLogFormatter().format(make_record())

    def test_appends_the_request_id_when_present(self) -> None:
        token = set_request_id("trace-abcdef")
        try:
            output = ConsoleLogFormatter().format(make_record())
        finally:
            reset_request_id(token)

        assert "[req=trace-abcdef]" in output

    def test_omits_the_marker_outside_a_request(self) -> None:
        assert "[req=" not in ConsoleLogFormatter().format(make_record())


class TestFormatterSelection:
    def test_json_is_the_default_shape(self) -> None:
        built = build_formatter(log_format="json", service="s", version="v", environment="test")

        assert isinstance(built, JsonLogFormatter)

    def test_console_can_be_requested(self) -> None:
        built = build_formatter(log_format="console", service="s", version="v", environment="test")

        assert isinstance(built, ConsoleLogFormatter)


class TestConfigureLogging:
    def test_installs_exactly_one_handler(self) -> None:
        configure_logging(
            level="INFO", log_format="json", service="s", version="v", environment="test"
        )

        assert len(logging.getLogger().handlers) == 1

    def test_is_idempotent(self) -> None:
        # uvicorn's reloader calls application setup more than once per process; a
        # handler appended each time would duplicate every log line.
        for _ in range(3):
            configure_logging(
                level="INFO", log_format="json", service="s", version="v", environment="test"
            )

        assert len(logging.getLogger().handlers) == 1

    def test_framework_loggers_delegate_to_the_root_handler(self) -> None:
        configure_logging(
            level="INFO", log_format="json", service="s", version="v", environment="test"
        )

        uvicorn_access = logging.getLogger("uvicorn.access")
        assert uvicorn_access.handlers == []
        assert uvicorn_access.propagate is True

    def test_level_is_applied(self) -> None:
        configure_logging(
            level="WARNING", log_format="json", service="s", version="v", environment="test"
        )

        assert logging.getLogger().level == logging.WARNING

    def test_get_logger_returns_a_namespaced_logger(self) -> None:
        assert get_logger("pathable_api.thing").name == "pathable_api.thing"
