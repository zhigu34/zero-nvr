"""Attribute access for python-onvif-zeep response objects.

zeep does not give responses one stable shape. The same logical field can arrive
as a ``dict`` entry, a plain object attribute, or a wrapper object whose payload
sits under ``_value_1``, and the shape can change with the device, its firmware,
and the library version. The adapter, the notification normaliser, and the
subscription reader had each grown a byte-identical ``_read`` to paper over that,
so a fix for one wrapper shape would have silently missed the other two.

Keeping this in the ONVIF package (rather than a generic coercion module) is
deliberate: the fallback chain is zeep-specific and has no meaning for other
integrations.
"""

from __future__ import annotations

from typing import Any

__all__ = ["read_attribute", "read_path"]


def read_attribute(value: Any, name: str) -> Any:
    """Read ``name`` from a zeep value without assuming dict or object shape."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def read_path(value: Any, *names: str) -> Any:
    """Walk a chain of attribute names, stopping at the first missing link."""
    current = value
    for name in names:
        current = read_attribute(current, name)
        if current is None:
            return None
    return current
