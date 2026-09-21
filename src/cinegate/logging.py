from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_ADSGRAM_SECRET_PATH_RE = re.compile(
    r"^/providers/adsgram/reward/[^/]+(?:/.*)?$"
)
_SAFE_EXTRA_FIELDS = (
    "event",
    "request_id",
    "update_id",
    "telegram_user_id",
    "telegram_chat_id",
    "movie_id",
    "reward_id",
    "delivery_id",
    "import_job_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "exception_class",
)


class JsonLogFormatter(logging.Formatter):
    """Small JSON formatter with an explicit extra-field allowlist."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in _SAFE_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info is not None:
            payload["exception_class"] = record.exc_info[0].__name__

        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )


def configure_application_logging(level: int = logging.INFO) -> None:
    logger = logging.getLogger("cinegate")
    logger.setLevel(level)
    logger.propagate = False

    if any(
        getattr(handler, "_cinegate_json_handler", False)
        for handler in logger.handlers
    ):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    handler._cinegate_json_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)


def sanitized_request_path(path: str) -> str:
    if _ADSGRAM_SECRET_PATH_RE.fullmatch(path):
        return "/providers/adsgram/reward/[REDACTED]"
    return path
