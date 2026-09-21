from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from app.core.config import Settings


class TurnConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TurnCredentialBundle:
    urls: list[str]
    username: str
    credential: str
    expires_at: datetime


class TurnCredentialService:
    """Issue short-lived coturn REST credentials for authorized live sessions."""

    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self.settings = settings

    @staticmethod
    def _valid_turn_url(value: str) -> bool:
        parsed = urlsplit(value)
        return parsed.scheme in {
            "turn",
            "turns",
        } and bool(parsed.path)

    def _urls(
        self,
        *,
        request_host: str | None,
    ) -> list[str]:
        configured = [
            item.strip()
            for item in self.settings.turn_urls.split(",")
            if item.strip()
        ]
        if configured:
            if not all(
                self._valid_turn_url(item)
                for item in configured
            ):
                raise TurnConfigurationError(
                    "Configured TURN URL is invalid."
                )
            return configured

        host = (
            self.settings.turn_public_host
            or request_host
        )
        if not host:
            raise TurnConfigurationError(
                "TURN public host is not configured."
            )
        if any(
            char.isspace()
            for char in host
        ) or "/" in host:
            raise TurnConfigurationError(
                "TURN public host is invalid."
            )

        port = self.settings.turn_port
        return [
            f"turn:{host}:{port}?transport=udp",
            f"turn:{host}:{port}?transport=tcp",
        ]

    def issue(
        self,
        *,
        user_id: uuid.UUID,
        request_host: str | None,
        now_epoch: int | None = None,
    ) -> TurnCredentialBundle | None:
        if not self.settings.turn_enabled:
            return None

        secret = self.settings.turn_shared_secret
        if secret is None:
            raise TurnConfigurationError(
                "TURN shared secret is not configured."
            )

        now = (
            int(time.time())
            if now_epoch is None
            else now_epoch
        )
        expires_epoch = (
            now
            + self.settings
            .turn_credential_ttl_seconds
        )
        username = (
            f"{expires_epoch}:{user_id}"
        )
        digest = hmac.new(
            secret.get_secret_value().encode(
                "utf-8"
            ),
            username.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        credential = base64.b64encode(
            digest
        ).decode("ascii")

        return TurnCredentialBundle(
            urls=self._urls(
                request_host=request_host
            ),
            username=username,
            credential=credential,
            expires_at=datetime.fromtimestamp(
                expires_epoch,
                tz=UTC,
            ),
        )
