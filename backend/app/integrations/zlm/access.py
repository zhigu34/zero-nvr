from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import Settings


class ZlmMediaAccess:
    """Issue and verify short-lived playback grants for ZLMediaKit streams."""

    signature_param = "zn_sig"
    expiry_param = "zn_exp"
    session_param = "zn_sid"
    max_ttl_seconds = 24 * 60 * 60
    live_ttl_seconds = 30 * 60
    playback_ttl_seconds = 5 * 60

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _message(
        *,
        app: str,
        stream: str,
        expires_at: int,
        session_id: uuid.UUID | None = None,
    ) -> bytes:
        if session_id is None:
            return (
                f"zlm-play-v1\n{app}\n{stream}\n{expires_at}"
            ).encode("utf-8")
        return (
            "zlm-play-v2\n"
            f"{app}\n{stream}\n{expires_at}\n{session_id}"
        ).encode("utf-8")

    @staticmethod
    def _signature(
        key: bytes,
        *,
        app: str,
        stream: str,
        expires_at: int,
        session_id: uuid.UUID | None = None,
    ) -> str:
        return hmac.new(
            key,
            ZlmMediaAccess._message(
                app=app,
                stream=stream,
                expires_at=expires_at,
                session_id=session_id,
            ),
            hashlib.sha256,
        ).hexdigest()

    def issue_params(
        self,
        *,
        app: str,
        stream: str,
        ttl_seconds: int,
        now_epoch: int | None = None,
        session_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, str], datetime]:
        if ttl_seconds <= 0 or ttl_seconds > self.max_ttl_seconds:
            raise ValueError("invalid ZLM media token TTL")

        now = int(time.time()) if now_epoch is None else now_epoch
        expires_at = now + ttl_seconds
        key = self.settings.secret_key.get_secret_value().encode("utf-8")
        signature = self._signature(
            key,
            app=app,
            stream=stream,
            expires_at=expires_at,
            session_id=session_id,
        )
        issued = {
            self.expiry_param: str(expires_at),
            self.signature_param: signature,
        }
        if session_id is not None:
            issued[self.session_param] = str(
                session_id
            )
        return (
            issued,
            datetime.fromtimestamp(expires_at, tz=UTC),
        )

    def sign_url(
        self,
        url: str,
        *,
        app: str,
        stream: str,
        ttl_seconds: int,
        now_epoch: int | None = None,
        session_id: uuid.UUID | None = None,
    ) -> tuple[str, datetime]:
        issued, expires_at = self.issue_params(
            app=app,
            stream=stream,
            ttl_seconds=ttl_seconds,
            now_epoch=now_epoch,
            session_id=session_id,
        )

        parsed = urlsplit(url)
        query = [
            (name, value)
            for name, value in parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if name not in {
                self.expiry_param,
                self.signature_param,
                self.session_param,
            }
        ]
        query.extend(issued.items())
        signed = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query),
                parsed.fragment,
            )
        )
        return signed, expires_at

    def verify(
        self,
        *,
        app: str,
        stream: str,
        params: str,
        now_epoch: int | None = None,
        allow_expired: bool = False,
    ) -> bool:
        query = parse_qs(
            params.lstrip("?"),
            keep_blank_values=True,
        )
        expiry_values = query.get(self.expiry_param, [])
        signature_values = query.get(self.signature_param, [])
        session_values = query.get(self.session_param, [])
        if len(expiry_values) != 1 or len(signature_values) != 1:
            return False
        if len(session_values) > 1:
            return False

        session_id: uuid.UUID | None = None
        if session_values:
            try:
                session_id = uuid.UUID(
                    session_values[0]
                )
            except (TypeError, ValueError):
                return False

        try:
            expires_at = int(expiry_values[0])
        except (TypeError, ValueError):
            return False

        now = int(time.time()) if now_epoch is None else now_epoch
        if expires_at > now + self.max_ttl_seconds:
            return False
        if not allow_expired and expires_at < now:
            return False

        supplied = signature_values[0]
        keys = [
            self.settings.secret_key,
            *self.settings.secret_key_previous,
        ]
        for secret in keys:
            expected = self._signature(
                secret.get_secret_value().encode("utf-8"),
                app=app,
                stream=stream,
                expires_at=expires_at,
                session_id=session_id,
            )
            if hmac.compare_digest(supplied, expected):
                return True
        return False


    def session_id_from_params(
        self,
        params: str,
    ) -> uuid.UUID | None:
        query = parse_qs(
            params.lstrip("?"),
            keep_blank_values=True,
        )
        values = query.get(
            self.session_param,
            [],
        )
        if len(values) != 1:
            return None
        try:
            return uuid.UUID(values[0])
        except (TypeError, ValueError):
            return None
