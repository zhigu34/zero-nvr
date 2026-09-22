from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import SecretStr


REDACTED = "***"

_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|credential|authorization|"
    r"api[_-]?key|client[_-]?secret|access[_-]?key|private[_-]?key|"
    r"cookie|session)",
    re.IGNORECASE,
)
_KEY_VALUE = re.compile(
    r"""(?ix)
    (?P<key>
        password|passwd|secret|token|credential|authorization|
        api[_-]?key|client[_-]?secret|access[_-]?key|private[_-]?key
    )
    (?P<sep>\s*[:=]\s*)
    (?P<value>
        "[^"]*"|'[^']*'|[^\s,;&]+
    )
    """
)
_BEARER = re.compile(
    r"(?i)\bBearer\s+[^\s,;]+"
)
_URL_USERINFO = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)"
    r"(?P<userinfo>[^/@\s]+)@"
)


def is_sensitive_key(value: object) -> bool:
    return bool(_SENSITIVE_KEY.search(str(value)))


def redact_text(value: str) -> str:
    redacted = _URL_USERINFO.sub(
        lambda match: f"{match.group('scheme')}***:***@",
        value,
    )
    redacted = _BEARER.sub("Bearer ***", redacted)
    redacted = _KEY_VALUE.sub(
        lambda match: (
            f"{match.group('key')}"
            f"{match.group('sep')}"
            f"{REDACTED}"
        ),
        redacted,
    )
    return redacted


def redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if is_sensitive_key(normalized_key):
                result[normalized_key] = REDACTED
            else:
                result[normalized_key] = (
                    redact_sensitive_value(item)
                )
        return result
    if isinstance(value, list):
        return [
            redact_sensitive_value(item)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            redact_sensitive_value(item)
            for item in value
        )
    if isinstance(value, str):
        return redact_text(value)
    return value
