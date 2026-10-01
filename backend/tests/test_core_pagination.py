"""Unit tests for the shared cursor-pagination codec and page-size guard.

Six modules used to carry their own copy of this logic. These tests pin the
externally visible contract that the copies agreed on: an opaque base64url
cursor, a 400 with the module's own error code for anything malformed, and a
``1..200`` page-size bound.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.errors import ApiError
from app.core.pagination import (
    PAGE_LIMIT_MAX,
    Page,
    decode_cursor,
    encode_cursor,
    normalize_page_limit,
)

TIMESTAMP = datetime(2026, 9, 20, 17, 30, tzinfo=UTC)
IDENTIFIER = uuid.UUID("3f2504e0-4f89-11d3-9a0c-0305e82c3301")


def test_cursor_round_trips_timestamp_key_and_identity() -> None:
    cursor = encode_cursor(
        timestamp=TIMESTAMP,
        identifier=IDENTIFIER,
        key="started_at",
    )
    decoded_at, decoded_id = decode_cursor(
        cursor,
        key="started_at",
        error_code="test_cursor_invalid",
        resource_label="Test",
    )
    assert decoded_at == TIMESTAMP
    assert decoded_id == IDENTIFIER


def test_cursor_is_url_safe_base64url_without_padding() -> None:
    cursor = encode_cursor(
        timestamp=TIMESTAMP,
        identifier=IDENTIFIER,
        key="created_at",
    )
    assert "=" not in cursor
    assert "+" not in cursor and "/" not in cursor
    # The padded form must decode to the same JSON document.
    padding = "=" * (-len(cursor) % 4)
    payload = json.loads(
        base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
    )
    assert payload["id"] == str(IDENTIFIER)
    assert "created_at" in payload


def test_cursor_normalises_offsets_to_utc() -> None:
    # 10:30 at -07:00 is the same instant as 17:30 UTC; the codec must store the
    # UTC form so a cursor is comparable regardless of who issued it.
    offset = datetime(
        2026,
        9,
        20,
        10,
        30,
        tzinfo=timezone(timedelta(hours=-7)),
    )
    cursor = encode_cursor(
        timestamp=offset,
        identifier=IDENTIFIER,
        key="started_at",
    )
    decoded_at, _ = decode_cursor(
        cursor,
        key="started_at",
        error_code="test_cursor_invalid",
        resource_label="Test",
    )
    assert decoded_at == TIMESTAMP
    assert decoded_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "value",
    [
        "not-base64!!",
        base64.urlsafe_b64encode(b"not json").decode("ascii"),
        base64.urlsafe_b64encode(b'{"started_at": "2026-09-20T17:30:00+00:00"}').decode("ascii"),
        base64.urlsafe_b64encode(
            b'{"started_at": "2026-09-20T17:30:00+00:00", "id": "not-a-uuid"}'
        ).decode("ascii"),
        # Naive timestamp: without an offset the instant is ambiguous.
        base64.urlsafe_b64encode(
            b'{"started_at": "2026-09-20T17:30:00", "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301"}'
        ).decode("ascii"),
    ],
)
def test_malformed_cursor_is_a_client_error(value: str) -> None:
    with pytest.raises(ApiError) as caught:
        decode_cursor(
            value,
            key="started_at",
            error_code="recording_cursor_invalid",
            resource_label="Recording",
        )
    assert caught.value.status_code == 400
    assert caught.value.code == "recording_cursor_invalid"
    assert caught.value.message == "Recording cursor is invalid."


@pytest.mark.parametrize("limit", [1, 50, PAGE_LIMIT_MAX])
def test_page_limit_accepts_in_range_values(limit: int) -> None:
    assert (
        normalize_page_limit(
            limit,
            error_code="x_limit_invalid",
            resource_label="X",
        )
        == limit
    )


@pytest.mark.parametrize("limit", [0, -1, PAGE_LIMIT_MAX + 1, 10_000])
def test_page_limit_rejects_out_of_range_values(limit: int) -> None:
    with pytest.raises(ApiError) as caught:
        normalize_page_limit(
            limit,
            error_code="export_limit_invalid",
            resource_label="Export",
        )
    assert caught.value.status_code == 400
    assert caught.value.code == "export_limit_invalid"


def test_page_defaults_to_no_next_cursor() -> None:
    page: Page[int] = Page(items=[1, 2], next_cursor=None)
    assert page.items == [1, 2]
    assert page.next_cursor is None
