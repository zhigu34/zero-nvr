from __future__ import annotations

import uuid
from urllib.parse import unquote, urlsplit

from sqlalchemy.orm import Session

from app.core.db.types import utc_now
from app.core.errors import ApiError
from app.integrations.onvif import OnvifDiscoveryCandidate

from .models import DiscoveryCandidate, DiscoverySession


class CameraDiscoveryService:
    @staticmethod
    def start(
        session: Session,
        *,
        created_by: uuid.UUID,
    ) -> DiscoverySession:
        discovery = DiscoverySession(
            method="onvif_ws_discovery",
            status="running",
            created_by=created_by,
        )
        session.add(discovery)
        session.flush()
        return discovery

    @staticmethod
    def get(
        session: Session,
        discovery_id: uuid.UUID,
    ) -> DiscoverySession:
        discovery = session.get(DiscoverySession, discovery_id)
        if discovery is None:
            raise ApiError(
                status_code=404,
                code="discovery_session_not_found",
                message="Discovery session was not found.",
            )
        return discovery

    @staticmethod
    def _display_info(
        candidate: OnvifDiscoveryCandidate,
    ) -> dict[str, object]:
        info: dict[str, object] = {}
        for scope in candidate.scopes:
            try:
                parsed = urlsplit(scope)
                parts = [
                    unquote(part)
                    for part in parsed.path.split("/")
                    if part
                ]
            except Exception:
                continue

            if len(parts) < 2:
                continue

            category = parts[0].lower()
            value = "/".join(parts[1:]).strip()
            if not value:
                continue

            if category in {"name", "hardware", "location"}:
                info.setdefault(category, value)

        if candidate.host:
            info["host"] = candidate.host
        return info

    @classmethod
    def complete(
        cls,
        session: Session,
        *,
        discovery_id: uuid.UUID,
        candidates: list[OnvifDiscoveryCandidate],
    ) -> DiscoverySession:
        discovery = cls.get(session, discovery_id)

        discovery.candidates.clear()

        for candidate in candidates:
            discovery.candidates.append(
                DiscoveryCandidate(
                    discovery_session_id=discovery.id,
                    candidate_key=candidate.candidate_key,
                    host=candidate.host,
                    device_identity={
                        "epr": candidate.epr,
                    },
                    display_info=cls._display_info(candidate),
                    state="discovered",
                    metadata_json={
                        "xaddrs": list(candidate.xaddrs),
                        "scopes": list(candidate.scopes),
                        "port": candidate.port,
                        "device_service_url": candidate.device_service_url,
                    },
                )
            )

        discovery.status = "completed"
        discovery.completed_at = utc_now()
        session.flush()
        return discovery

    @classmethod
    def fail(
        cls,
        session: Session,
        *,
        discovery_id: uuid.UUID,
    ) -> DiscoverySession:
        discovery = cls.get(session, discovery_id)
        discovery.status = "failed"
        discovery.completed_at = utc_now()
        session.flush()
        return discovery
