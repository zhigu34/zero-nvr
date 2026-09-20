from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class FrigateIntegrationError(RuntimeError):
    """Sanitized Frigate transport/integration failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class FrigateVersion:
    version: str | None


class FrigateHttpAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise FrigateIntegrationError(
                "frigate_url_invalid",
                "Frigate base URL must use http:// or https://.",
                status_code=400,
            )
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise FrigateIntegrationError(
                "frigate_timeout_invalid",
                "Frigate timeout is invalid.",
                status_code=400,
            )

        headers = {"Accept": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        auth = (
            httpx.BasicAuth(username, password or "")
            if username is not None
            else None
        )
        self.base_url = normalized
        self._client = httpx.Client(
            base_url=normalized,
            timeout=timeout_seconds,
            headers=headers,
            auth=auth,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FrigateHttpAdapter":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _response(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.get(
                path,
                params={
                    key: value
                    for key, value in (params or {}).items()
                    if value is not None
                },
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise FrigateIntegrationError(
                "frigate_timeout",
                "Frigate did not respond in time.",
                status_code=504,
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise FrigateIntegrationError(
                "frigate_request_failed",
                "Frigate request failed.",
                status_code=(
                    401
                    if status in {401, 403}
                    else 503
                    if status >= 500
                    else 502
                ),
            ) from exc
        except httpx.HTTPError as exc:
            raise FrigateIntegrationError(
                "frigate_unavailable",
                "Frigate is unavailable.",
                status_code=503,
            ) from exc

        return response

    def _get(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> Any:
        response = self._response(
            path,
            params=params,
        )
        try:
            return response.json()
        except ValueError as exc:
            raise FrigateIntegrationError(
                "frigate_invalid_response",
                "Frigate returned an invalid response.",
            ) from exc

    def version(self) -> FrigateVersion:
        response = self._response("/api/version")
        value = response.text.strip()
        return FrigateVersion(
            version=value or None,
        )

    def events(
        self,
        *,
        after: float | None = None,
        before: float | None = None,
        cameras: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise FrigateIntegrationError(
                "frigate_events_limit_invalid",
                "Frigate event batch limit is invalid.",
                status_code=400,
            )
        if offset < 0:
            raise FrigateIntegrationError(
                "frigate_events_offset_invalid",
                "Frigate event offset is invalid.",
                status_code=400,
            )

        payload = self._get(
            "/api/events",
            params={
                "after": after,
                "before": before,
                "cameras": (
                    ",".join(cameras)
                    if cameras
                    else None
                ),
                "limit": limit,
                "offset": offset,
                "sort": "date_asc",
            },
        )
        if not isinstance(payload, list):
            raise FrigateIntegrationError(
                "frigate_invalid_response",
                "Frigate returned an invalid event list.",
            )
        return [
            item
            for item in payload
            if isinstance(item, dict)
        ]

    def snapshot_url(
        self,
        event_id: str,
        *,
        clean: bool = False,
    ) -> str:
        normalized = event_id.strip()
        if (
            not normalized
            or len(normalized) > 512
            or "/" in normalized
            or "\\" in normalized
            or "?" in normalized
            or "#" in normalized
        ):
            raise FrigateIntegrationError(
                "frigate_event_id_invalid",
                "Frigate event id is invalid.",
                status_code=400,
            )
        suffix = (
            "snapshot-clean.webp"
            if clean
            else "snapshot.jpg"
        )
        return f"{self.base_url}/api/events/{normalized}/{suffix}"
