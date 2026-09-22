from __future__ import annotations

import json
import logging
import sys

from app.core.errors import ApiError
from app.core.logging import JsonFormatter
from app.core.security import redact_sensitive_value, redact_text


def test_redact_sensitive_value_covers_nested_and_text_forms() -> None:
    value = {
        "password": "plain-password",
        "nested": {
            "api_token": "plain-token",
            "message": (
                'provider returned "client_secret": "plain-client-secret" '
                "Authorization: Bearer plain-bearer"
            ),
        },
        "url": "rtsp://camera-user:camera-pass@example.test/live",
    }

    redacted = redact_sensitive_value(value)
    encoded = json.dumps(redacted)

    for secret in (
        "plain-password",
        "plain-token",
        "plain-client-secret",
        "plain-bearer",
        "camera-user",
        "camera-pass",
    ):
        assert secret not in encoded

    assert redacted["password"] == "***"
    assert redacted["nested"]["api_token"] == "***"
    assert "***:***@" in redacted["url"]


def test_redact_text_preserves_non_sensitive_context() -> None:
    value = (
        "request failed password=plain-password "
        'payload={"token": "plain-token"} '
        "Authorization: Bearer plain-bearer"
    )

    redacted = redact_text(value)

    assert "request failed" in redacted
    assert "plain-password" not in redacted
    assert "plain-token" not in redacted
    assert "plain-bearer" not in redacted


def test_api_error_sanitizes_message_and_details() -> None:
    error = ApiError(
        status_code=400,
        code="provider_error",
        message="provider rejected password=plain-password",
        details={
            "token": "plain-token",
            "context": "Authorization: Bearer plain-bearer",
        },
    )

    assert "plain-password" not in str(error)
    assert "plain-password" not in error.message
    encoded = json.dumps(error.details)
    assert "plain-token" not in encoded
    assert "plain-bearer" not in encoded


def test_json_formatter_redacts_message_extra_and_exception_value() -> None:
    try:
        raise RuntimeError(
            "password=trace-secret"
        )
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="zero_nvr.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=(
            "request failed password=message-secret "
            "rtsp://camera:camera-pass@example.test/live"
        ),
        args=(),
        exc_info=exc_info,
    )
    record.api_token = "extra-secret"
    record.context = {
        "client_secret": "nested-secret",
    }

    payload = json.loads(
        JsonFormatter().format(record)
    )
    encoded = json.dumps(payload)

    for secret in (
        "trace-secret",
        "message-secret",
        "camera-pass",
        "extra-secret",
        "nested-secret",
    ):
        assert secret not in encoded

    assert payload["exception"]["type"] == "RuntimeError"
