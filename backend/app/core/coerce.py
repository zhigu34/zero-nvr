"""Lenient coercion for values returned by third-party integrations.

Validation of user input remains at its call site: those callers have
different error codes, length limits, and required-field semantics.
"""

from typing import Any


def as_text(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None
