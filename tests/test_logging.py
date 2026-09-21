import json
import logging

from cinegate.logging import JsonLogFormatter, sanitized_request_path


def test_adsgram_callback_secret_path_is_redacted() -> None:
    secret = "super_secret_callback_value_123456789"
    path = f"/providers/adsgram/reward/{secret}"

    sanitized = sanitized_request_path(path)

    assert sanitized == "/providers/adsgram/reward/[REDACTED]"
    assert secret not in sanitized


def test_adsgram_callback_secret_is_redacted_on_redirect_or_extra_path() -> None:
    secret = "super_secret_callback_value_123456789"

    for suffix in ("/", "/unexpected"):
        sanitized = sanitized_request_path(
            f"/providers/adsgram/reward/{secret}{suffix}"
        )

        assert sanitized == "/providers/adsgram/reward/[REDACTED]"
        assert secret not in sanitized


def test_normal_request_path_is_unchanged() -> None:
    assert sanitized_request_path("/telegram/webhook") == "/telegram/webhook"


def test_json_formatter_only_emits_allowlisted_extra_fields() -> None:
    record = logging.LogRecord(
        name="cinegate.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )
    record.event = "http_request"
    record.path = "/providers/adsgram/reward/[REDACTED]"
    record.status_code = 204
    record.init_data = "MUST_NOT_APPEAR"
    record.bot_token = "MUST_NOT_APPEAR"

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["event"] == "http_request"
    assert payload["path"] == "/providers/adsgram/reward/[REDACTED]"
    assert payload["status_code"] == 204
    assert "init_data" not in payload
    assert "bot_token" not in payload
    assert "MUST_NOT_APPEAR" not in json.dumps(payload)


def test_json_formatter_records_exception_class_without_trace_payload() -> None:
    try:
        raise RuntimeError("sensitive details")
    except RuntimeError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="cinegate.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="operation failed",
        args=(),
        exc_info=exc_info,
    )

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["exception_class"] == "RuntimeError"
    assert "sensitive details" not in json.dumps(payload)
