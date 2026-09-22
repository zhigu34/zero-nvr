from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.integrations.apprise import AppriseAdapter, AppriseIntegrationError

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
        if set(config) - {"notify_type", "password_reset"}:
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
        password_reset = config.get("password_reset", False)
        if not isinstance(password_reset, bool):
            raise ApiError(
                status_code=400,
                code="notification_target_config_invalid",
                message="Notification target configuration is invalid.",
            )
        return {
            "notify_type": notify_type,
            "password_reset": password_reset,
        }

    @staticmethod
    def is_password_reset_target(
        target: NotificationTarget,
    ) -> bool:
        return (
            (target.config_json or {}).get("password_reset")
            is True
        )

    @classmethod
    def _ensure_password_reset_unique(
        cls,
        session: Session,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        for item in session.scalars(
            select(NotificationTarget)
        ):
            if (
                item.id != exclude_id
                and cls.is_password_reset_target(item)
            ):
                raise ApiError(
                    status_code=409,
                    code="password_reset_target_conflict",
                    message=(
                        "Only one notification target can be used "
                        "for password reset email."
                    ),
                )

    @staticmethod
    def _validate_password_reset_url(url: str) -> None:
        parsed = urlsplit(url.strip())
        if (
            parsed.scheme.lower()
            not in {"mailto", "mailtos"}
            or parsed.path not in {"", "/"}
            or parsed.fragment
        ):
            raise ApiError(
                status_code=400,
                code="password_reset_target_invalid",
                message=(
                    "Password reset target must be a mailto/mailtos "
                    "SMTP URL without recipients in the URL path."
                ),
            )

    @classmethod
    def password_reset_recipient_url(
        cls,
        url: str,
        recipient: str,
    ) -> str:
        cls._validate_password_reset_url(url)
        parsed = urlsplit(url.strip())
        filtered = [
            (key, value)
            for key, value in parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if key.lower()
            not in {
                "to",
                "cc",
                "bcc",
                "+to",
                "+cc",
                "+bcc",
            }
        ]
        filtered.append(("to", recipient))
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(filtered, doseq=True),
                "",
            )
        )

    @classmethod
    def password_reset_target(
        cls,
        session: Session,
    ) -> NotificationTarget | None:
        for item in cls.list(session):
            if (
                item.enabled
                and cls.is_password_reset_target(item)
            ):
                return item
        return None

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

        try:
            AppriseAdapter(url=normalized)
        except AppriseIntegrationError as exc:
            raise ApiError(
                status_code=exc.status_code,
                code=exc.code,
                message=str(exc),
            ) from exc

        old_ref = target.secret_ref
        if old_ref is not None:
            try:
                metadata = self.secret_store.metadata(
                    session,
                    old_ref,
                )
            except KeyError:
                old_ref = None
            else:
                if (
                    metadata.kind != "notification_url"
                    or metadata.owner_type != "notification_target"
                    or metadata.owner_id != target.id
                ):
                    raise ApiError(
                        status_code=409,
                        code="notification_secret_invalid",
                        message="Notification target secret reference is invalid.",
                    )

        candidate_ref = self.secret_store.create_json(
            session,
            kind="notification_url",
            owner_type="notification_target",
            owner_id=target.id,
            value={"url": normalized},
        )
        target.secret_ref = candidate_ref
        session.flush()

        if old_ref is not None:
            try:
                self.secret_store.delete(
                    session,
                    old_ref,
                    kind="notification_url",
                    owner_type="notification_target",
                    owner_id=target.id,
                )
            except KeyError:
                pass

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

        normalized_config = self._normalize_config(
            config
        )
        if normalized_config["password_reset"] is True:
            self._ensure_password_reset_unique(session)
            self._validate_password_reset_url(
                normalized_url
            )

        target_id = uuid.uuid4()
        try:
            AppriseAdapter(url=normalized_url)
        except AppriseIntegrationError as exc:
            raise ApiError(
                status_code=exc.status_code,
                code=exc.code,
                message=str(exc),
            ) from exc

        secret_id = self.secret_store.create_json(
            session,
            kind="notification_url",
            owner_type="notification_target",
            owner_id=target_id,
            value={"url": normalized_url},
        )
        target = NotificationTarget(
            id=target_id,
            name=normalized_name,
            kind="apprise",
            enabled=enabled,
            config_json=normalized_config,
            secret_ref=secret_id,
        )
        session.add(target)
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

        candidate_config = target.config_json or {}
        if "config" in changes:
            raw_config = changes["config"]
            if not isinstance(raw_config, dict):
                raise ApiError(
                    status_code=400,
                    code="notification_target_config_invalid",
                    message="Notification target configuration is invalid.",
                )
            candidate_config = self._normalize_config(
                raw_config
            )

        url_action = str(
            changes.get("url_action", "keep")
        )
        if url_action not in {
            "keep",
            "replace",
            "clear",
        }:
            raise ApiError(
                status_code=400,
                code="notification_url_update_invalid",
                message="Notification URL action is invalid.",
            )

        candidate_url: str | None = None
        if url_action == "replace":
            raw_url = changes.get("url")
            if not isinstance(raw_url, str):
                raise ApiError(
                    status_code=400,
                    code="notification_url_invalid",
                    message="Notification target URL is invalid.",
                )
            candidate_url = raw_url.strip()
        elif url_action == "clear":
            if "url" in changes:
                raise ApiError(
                    status_code=400,
                    code="notification_url_update_invalid",
                    message=(
                        "Notification URL clear action "
                        "does not accept a replacement value."
                    ),
                )
        elif "url" in changes:
            raise ApiError(
                status_code=400,
                code="notification_url_update_invalid",
                message=(
                    "Notification URL value requires "
                    "action=replace."
                ),
            )
        elif candidate_config.get("password_reset") is True:
            candidate_url = self._secret_url(
                session,
                target=target,
            )

        if candidate_config.get("password_reset") is True:
            self._ensure_password_reset_unique(
                session,
                exclude_id=target.id,
            )
            if candidate_url is None:
                raise ApiError(
                    status_code=409,
                    code="notification_secret_unavailable",
                    message="Notification target secret is unavailable.",
                )
            self._validate_password_reset_url(
                candidate_url
            )

        if "config" in changes:
            target.config_json = candidate_config

        if url_action == "replace":
            assert candidate_url is not None
            self._replace_secret(
                session,
                target=target,
                url=candidate_url,
            )
        elif url_action == "clear":
            secret_ref = target.secret_ref
            target.secret_ref = None
            session.flush()
            if secret_ref is not None:
                try:
                    self.secret_store.delete(
                        session,
                        secret_ref,
                        kind="notification_url",
                        owner_type="notification_target",
                        owner_id=target.id,
                    )
                except KeyError:
                    pass

        session.flush()
        return target

    def _secret_url(
        self,
        session: Session,
        *,
        target: NotificationTarget,
    ) -> str:
        if target.secret_ref is None:
            raise ApiError(
                status_code=409,
                code="notification_secret_unavailable",
                message="Notification target secret is unavailable.",
            )
        try:
            payload = self.secret_store.read_json(
                session,
                target.secret_ref,
                kind="notification_url",
                owner_type="notification_target",
                owner_id=target.id,
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

        return url

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
        url = self._secret_url(
            session,
            target=target,
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

    def delete(
        self,
        session: Session,
        *,
        target: NotificationTarget,
    ) -> None:
        from app.modules.alerts.models import AlertPolicy

        for policy in session.scalars(select(AlertPolicy)):
            raw_ids = (policy.action_json or {}).get(
                "notification_target_ids",
                [],
            )
            if (
                isinstance(raw_ids, list)
                and str(target.id) in raw_ids
            ):
                raise ApiError(
                    status_code=409,
                    code="notification_target_in_policy",
                    message="Notification target is referenced by an alert policy.",
                )

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
        if secret_ref is not None:
            try:
                self.secret_store.delete(
                    session,
                    secret_ref,
                    kind="notification_url",
                    owner_type="notification_target",
                    owner_id=target.id,
                )
            except KeyError:
                pass
