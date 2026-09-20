from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.modules.auth.models import SecretRecord

from .models import NotificationDelivery, NotificationTarget


@dataclass(frozen=True, slots=True)
class ResolvedNotificationTarget:
    target_id: uuid.UUID
    name: str
    url: str
    notify_type: str


class NotificationTargetService:
    def __init__(self, settings: Settings) -> None:
        self.secret_store = SecretStore(settings)

    @staticmethod
    def _normalize_config(
        config: dict[str, object],
    ) -> dict[str, Any]:
        if set(config) - {"notify_type"}:
            raise ApiError(
                status_code=400,
                code="notification_target_config_invalid",
                message="Notification target contains unsupported configuration.",
            )
        notify_type = str(
            config.get("notify_type") or "info"
        ).strip().lower()
        if notify_type not in {
            "info",
            "success",
            "warning",
            "failure",
        }:
            raise ApiError(
                status_code=400,
                code="notification_target_type_invalid",
                message="Notification type is invalid.",
            )
        return {"notify_type": notify_type}

    @staticmethod
    def list(session: Session) -> list[NotificationTarget]:
        return list(
            session.scalars(
                select(NotificationTarget).order_by(
                    NotificationTarget.name,
                    NotificationTarget.id,
                )
            )
        )

    @staticmethod
    def get(
        session: Session,
        target_id: uuid.UUID,
    ) -> NotificationTarget:
        target = session.get(NotificationTarget, target_id)
        if target is None:
            raise ApiError(
                status_code=404,
                code="notification_target_not_found",
                message="Notification target was not found.",
            )
        return target

    @staticmethod
    def _name_available(
        session: Session,
        *,
        name: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        statement = select(NotificationTarget.id).where(
            NotificationTarget.name == name
        )
        if exclude_id is not None:
            statement = statement.where(
                NotificationTarget.id != exclude_id
            )
        if session.scalar(statement.limit(1)) is not None:
            raise ApiError(
                status_code=409,
                code="notification_target_name_conflict",
                message="Notification target name is already in use.",
            )

    def _replace_secret(
        self,
        session: Session,
        *,
        target: NotificationTarget,
        url: str,
    ) -> None:
        normalized = url.strip()
        if not normalized:
            raise ApiError(
                status_code=400,
                code="notification_url_invalid",
                message="Notification target URL is invalid.",
            )

        encrypted = self.secret_store.encrypt_json(
            {"url": normalized}
        )
        secret = session.get(
            SecretRecord,
            target.secret_ref,
        )
        if secret is None:
            secret = SecretRecord(
                kind="notification_url",
                owner_type="notification_target",
                owner_id=target.id,
                key_id=encrypted.key_id,
                encrypted_payload=encrypted.ciphertext,
                version=encrypted.version,
            )
            session.add(secret)
            session.flush()
            target.secret_ref = secret.id
        else:
            if (
                secret.kind != "notification_url"
                or secret.owner_type != "notification_target"
                or secret.owner_id != target.id
            ):
                raise ApiError(
                    status_code=409,
                    code="notification_secret_invalid",
                    message="Notification target secret reference is invalid.",
                )
            secret.key_id = encrypted.key_id
            secret.encrypted_payload = encrypted.ciphertext
            secret.version = encrypted.version

    def create(
        self,
        session: Session,
        *,
        name: str,
        enabled: bool,
        config: dict[str, object],
        url: str,
    ) -> NotificationTarget:
        normalized_name = name.strip()
        self._name_available(
            session,
            name=normalized_name,
        )

        normalized_url = url.strip()
        if not normalized_url:
            raise ApiError(
                status_code=400,
                code="notification_url_invalid",
                message="Notification target URL is invalid.",
            )

        target_id = uuid.uuid4()
        secret_id = uuid.uuid4()
        encrypted = self.secret_store.encrypt_json(
            {"url": normalized_url}
        )
        secret = SecretRecord(
            id=secret_id,
            kind="notification_url",
            owner_type="notification_target",
            owner_id=target_id,
            key_id=encrypted.key_id,
            encrypted_payload=encrypted.ciphertext,
            version=encrypted.version,
        )
        target = NotificationTarget(
            id=target_id,
            name=normalized_name,
            kind="apprise",
            enabled=enabled,
            config_json=self._normalize_config(config),
            secret_ref=secret_id,
        )
        session.add_all([secret, target])
        session.flush()
        return target

    def update(
        self,
        session: Session,
        *,
        target: NotificationTarget,
        changes: dict[str, object],
    ) -> NotificationTarget:
        if "name" in changes:
            raw = changes["name"]
            if not isinstance(raw, str) or not raw.strip():
                raise ApiError(
                    status_code=400,
                    code="notification_target_name_invalid",
                    message="Notification target name is invalid.",
                )
            normalized = raw.strip()
            self._name_available(
                session,
                name=normalized,
                exclude_id=target.id,
            )
            target.name = normalized

        if "enabled" in changes:
            target.enabled = bool(changes["enabled"])

        if "config" in changes:
            raw_config = changes["config"]
            if not isinstance(raw_config, dict):
                raise ApiError(
                    status_code=400,
                    code="notification_target_config_invalid",
                    message="Notification target configuration is invalid.",
                )
            target.config_json = self._normalize_config(
                raw_config
            )

        if "url" in changes:
            raw_url = changes["url"]
            if not isinstance(raw_url, str):
                raise ApiError(
                    status_code=400,
                    code="notification_url_invalid",
                    message="Notification target URL is invalid.",
                )
            self._replace_secret(
                session,
                target=target,
                url=raw_url,
            )

        session.flush()
        return target

    def resolve(
        self,
        session: Session,
        *,
        target: NotificationTarget,
    ) -> ResolvedNotificationTarget:
        if not target.enabled:
            raise ApiError(
                status_code=409,
                code="notification_target_disabled",
                message="Notification target is disabled.",
            )
        secret = session.get(
            SecretRecord,
            target.secret_ref,
        )
        if (
            secret is None
            or secret.kind != "notification_url"
            or secret.owner_type != "notification_target"
            or secret.owner_id != target.id
        ):
            raise ApiError(
                status_code=409,
                code="notification_secret_unavailable",
                message="Notification target secret is unavailable.",
            )
        try:
            payload = self.secret_store.decrypt_json(
                key_id=secret.key_id,
                ciphertext=secret.encrypted_payload,
                version=secret.version,
            )
        except Exception as exc:
            raise ApiError(
                status_code=409,
                code="notification_secret_unavailable",
                message="Notification target secret could not be decrypted.",
            ) from exc

        url = payload.get("url")
        if not isinstance(url, str) or not url:
            raise ApiError(
                status_code=409,
                code="notification_secret_unavailable",
                message="Notification target secret is unavailable.",
            )

        return ResolvedNotificationTarget(
            target_id=target.id,
            name=target.name,
            url=url,
            notify_type=str(
                (target.config_json or {}).get(
                    "notify_type",
                    "info",
                )
            ),
        )

    @staticmethod
    def delete(
        session: Session,
        *,
        target: NotificationTarget,
    ) -> None:
        in_use = session.scalar(
            select(NotificationDelivery.id)
            .where(
                NotificationDelivery.notification_target_id
                == target.id
            )
            .limit(1)
        )
        if in_use is not None:
            raise ApiError(
                status_code=409,
                code="notification_target_in_use",
                message="Notification target has delivery history and cannot be deleted.",
            )

        secret_ref = target.secret_ref
        session.delete(target)
        session.flush()
        secret = session.get(SecretRecord, secret_ref)
        if secret is not None:
            session.delete(secret)
