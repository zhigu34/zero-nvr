from __future__ import annotations

import uuid

from app.core.config import Settings
from app.integrations.zlm import ZlmMediaAccess


def settings() -> Settings:
    return Settings(
        secret_key=(
            "zlm-media-access-test-secret-key-"
            "32-bytes-minimum"
        ),
        environment="test",
    )


def test_session_bound_media_grant_cannot_drop_or_swap_session_id() -> None:
    access = ZlmMediaAccess(settings())
    session_id = uuid.uuid4()
    signed, _expires_at = access.sign_url(
        "http://media.local/zero-nvr/profile-test/hls.m3u8",
        app="zero-nvr",
        stream="profile-test",
        ttl_seconds=300,
        now_epoch=1_000,
        session_id=session_id,
    )
    from urllib.parse import (
        parse_qs,
        urlencode,
        urlsplit,
    )

    params = urlsplit(signed).query
    assert access.verify(
        app="zero-nvr",
        stream="profile-test",
        params=params,
        now_epoch=1_001,
    )
    assert (
        access.session_id_from_params(
            params
        )
        == session_id
    )

    query = parse_qs(params)
    query.pop("zn_sid")
    without_session = urlencode(
        {
            key: values[0]
            for key, values in query.items()
        }
    )
    assert not access.verify(
        app="zero-nvr",
        stream="profile-test",
        params=without_session,
        now_epoch=1_001,
    )

    query = parse_qs(params)
    query["zn_sid"] = [
        str(uuid.uuid4())
    ]
    swapped_session = urlencode(
        {
            key: values[0]
            for key, values in query.items()
        }
    )
    assert not access.verify(
        app="zero-nvr",
        stream="profile-test",
        params=swapped_session,
        now_epoch=1_001,
    )


def test_legacy_unscoped_grant_remains_valid_for_non_live_callers() -> None:
    access = ZlmMediaAccess(settings())
    signed, _expires_at = access.sign_url(
        "http://media.local/zero-nvr-vod/archive/hls.m3u8",
        app="zero-nvr-vod",
        stream="archive",
        ttl_seconds=300,
        now_epoch=2_000,
    )
    from urllib.parse import urlsplit

    params = urlsplit(signed).query
    assert access.verify(
        app="zero-nvr-vod",
        stream="archive",
        params=params,
        now_epoch=2_001,
    )
    assert (
        access.session_id_from_params(
            params
        )
        is None
    )
