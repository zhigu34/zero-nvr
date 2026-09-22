from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime

from app.core.security import is_sensitive_key, redact_sensitive_value, redact_text


_STANDARD_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }

        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _STANDARD_RECORD_FIELDS:
                continue
            if key in {"args", "exc_info", "exc_text", "stack_info"}:
                continue
            payload[key] = (
                "***"
                if is_sensitive_key(key)
                else redact_sensitive_value(value)
            )

        if record.exc_info:
            exc_type, _exc_value, exc_tb = record.exc_info
            payload["exception"] = {
                "type": (
                    exc_type.__name__
                    if exc_type is not None
                    else "Exception"
                ),
                "traceback": [
                    redact_text(frame)
                    for frame in traceback.format_tb(exc_tb)
                ]
                if exc_tb is not None
                else [],
            }

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> logging.Logger:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    return logging.getLogger("zero_nvr")
