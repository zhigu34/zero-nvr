from __future__ import annotations

import ipaddress
import re
import uuid
from dataclasses import dataclass, replace
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SecretStore
from app.modules.system.models import SystemSetting

from .models import Role


OIDC_NAMESPACE = "auth.oidc"
_PROVIDER_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class OidcProviderConfig:
    id: uuid.UUID
    key: str
    name: str
    enabled: bool
    issuer: str
    client_id: str
    secret_ref: uuid.UUID | None
    auto_provision: bool
    email_linking: bool
    default_role_ids: tuple[uuid.UUID, ...]


class OidcProviderSettingsService:
    def __init__(self, settings: Settings) -> None:
        self.secret_store = SecretStore(settings)

    @staticmethod
    def _provider_key(value: str) -> str:
        normalized = value.strip().lower()
        if not _PROVIDER_KEY.fullmatch(normalized):
            raise ApiError(
                status_code=400,
                code="oidc_provider_key_invalid",
                message="OIDC provider key is invalid.",
            )
        return normalized

    @staticmethod
    def _issuer(value: str) -> str:
        normalized = value.strip().rstrip("/")
        try:
            parsed = urlsplit(normalized)
        except ValueError as exc:
            raise ApiError(
                status_code=400,
                code="oidc_issuer_invalid",
                message="OIDC issuer URL is invalid.",
            ) from exc

        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ApiError(
                status_code=400,
                code="oidc_issuer_invalid",
                message="OIDC issuer URL is invalid.",
            )

        hostname = parsed.hostname.lower()
        loopback = hostname == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(
                hostname
            ).is_loopback
        except ValueError:
            pass

        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and loopback
        ):
            raise ApiError(
                status_code=400,
                code="oidc_issuer_insecure",
                message=(
                    "OIDC issuer must use HTTPS; HTTP is allowed "
                    "only for localhost/loopback development."
                ),
            )

        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path.rstrip("/"),
                "",
                "",
            )
        )

    @staticmethod
    def _roles(
        session: Session,
        role_ids: list[uuid.UUID],
        *,
        auto_provision: bool,
    ) -> tuple[uuid.UUID, ...]:
        unique = set(role_ids)
        if auto_provision and not unique:
            raise ApiError(
                status_code=400,
                code="oidc_default_role_required",
                message=(
                    "At least one default role is required "
                    "when OIDC auto-provisioning is enabled."
                ),
            )
        if not unique:
            return ()

        found = set(
            session.scalars(
                select(Role.id).where(
                    Role.id.in_(unique)
                )
            )
        )
        missing = unique - found
        if missing:
            raise ApiError(
                status_code=400,
                code="oidc_default_role_invalid",
                message="OIDC provider references an unknown role.",
                details={
                    "role_ids": sorted(
                        str(item)
                        for item in missing
                    )
                },
            )
        return tuple(sorted(unique, key=str))

    @staticmethod
    def _setting(
        session: Session,
    ) -> SystemSetting | None:
        return session.get(
            SystemSetting,
            OIDC_NAMESPACE,
        )

    @classmethod
    def _raw_providers(
        cls,
        session: Session,
    ) -> dict[str, dict[str, object]]:
        setting = cls._setting(session)
        if setting is None:
            return {}
        raw = (setting.value_json or {}).get(
            "providers",
            {},
        )
        if not isinstance(raw, dict):
            raise ApiError(
                status_code=409,
                code="oidc_settings_invalid",
                message="Stored OIDC settings are invalid.",
            )

        providers: dict[str, dict[str, object]] = {}
        for key, value in raw.items():
            if (
                not isinstance(key, str)
                or not isinstance(value, dict)
            ):
                raise ApiError(
                    status_code=409,
                    code="oidc_settings_invalid",
                    message="Stored OIDC settings are invalid.",
                )
            providers[key] = dict(value)
        return providers

    @staticmethod
    def _decode(
        key: str,
        raw: dict[str, object],
    ) -> OidcProviderConfig:
        try:
            provider_id = uuid.UUID(str(raw["id"]))
            secret_ref = (
                uuid.UUID(str(raw["secret_ref"]))
                if raw.get("secret_ref")
                else None
            )
            role_ids = tuple(
                uuid.UUID(str(item))
                for item in (
                    raw.get("default_role_ids")
                    or []
                )
            )
            return OidcProviderConfig(
                id=provider_id,
                key=key,
                name=str(raw["name"]),
                enabled=bool(raw.get("enabled", False)),
                issuer=str(raw["issuer"]),
                client_id=str(raw["client_id"]),
                secret_ref=secret_ref,
                auto_provision=bool(
                    raw.get("auto_provision", False)
                ),
                email_linking=bool(
                    raw.get("email_linking", False)
                ),
                default_role_ids=role_ids,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(
                status_code=409,
                code="oidc_settings_invalid",
                message="Stored OIDC settings are invalid.",
            ) from exc

    @classmethod
    def list(
        cls,
        session: Session,
    ) -> list[OidcProviderConfig]:
        return [
            cls._decode(key, value)
            for key, value in sorted(
                cls._raw_providers(session).items()
            )
        ]

    @classmethod
    def get(
        cls,
        session: Session,
        key: str,
    ) -> OidcProviderConfig:
        normalized = cls._provider_key(key)
        raw = cls._raw_providers(session).get(
            normalized
        )
        if raw is None:
            raise ApiError(
                status_code=404,
                code="oidc_provider_not_found",
                message="OIDC provider was not found.",
            )
        return cls._decode(normalized, raw)

    @staticmethod
    def _encode(
        provider: OidcProviderConfig,
    ) -> dict[str, object]:
        return {
            "id": str(provider.id),
            "name": provider.name,
            "enabled": provider.enabled,
            "issuer": provider.issuer,
            "client_id": provider.client_id,
            "secret_ref": (
                str(provider.secret_ref)
                if provider.secret_ref
                else None
            ),
            "auto_provision": provider.auto_provision,
            "email_linking": provider.email_linking,
            "default_role_ids": [
                str(item)
                for item in provider.default_role_ids
            ],
        }

    @classmethod
    def _save(
        cls,
        session: Session,
        providers: dict[str, dict[str, object]],
    ) -> None:
        setting = cls._setting(session)
        value = {
            "providers": providers,
        }
        if setting is None:
            session.add(
                SystemSetting(
                    namespace=OIDC_NAMESPACE,
                    value_json=value,
                )
            )
        else:
            setting.value_json = value
        session.flush()

    def _put_secret(
        self,
        session: Session,
        *,
        provider_id: uuid.UUID,
        existing_ref: uuid.UUID | None,
        client_secret: str,
    ) -> uuid.UUID:
        value = client_secret.strip()
        if not value:
            raise ApiError(
                status_code=400,
                code="oidc_client_secret_invalid",
                message="OIDC client secret is invalid.",
            )

        if existing_ref is not None:
            try:
                metadata = self.secret_store.metadata(
                    session,
                    existing_ref,
                )
            except KeyError:
                existing_ref = None
            else:
                if (
                    metadata.kind != "oidc_client_secret"
                    or metadata.owner_type != "oidc_provider"
                    or metadata.owner_id != provider_id
                ):
                    raise ApiError(
                        status_code=409,
                        code="oidc_client_secret_unavailable",
                        message="OIDC client secret reference is invalid.",
                    )

        return self.secret_store.create_json(
            session,
            kind="oidc_client_secret",
            owner_type="oidc_provider",
            owner_id=provider_id,
            value={"client_secret": value},
        )

    def client_secret(
        self,
        session: Session,
        provider: OidcProviderConfig,
    ) -> str:
        if provider.secret_ref is None:
            raise ApiError(
                status_code=409,
                code="oidc_client_secret_unavailable",
                message="OIDC client secret is not configured.",
            )
        try:
            payload = self.secret_store.read_json(
                session,
                provider.secret_ref,
                kind="oidc_client_secret",
                owner_type="oidc_provider",
                owner_id=provider.id,
            )
        except Exception as exc:
            raise ApiError(
                status_code=409,
                code="oidc_client_secret_unavailable",
                message="OIDC client secret could not be decrypted.",
            ) from exc
        value = payload.get("client_secret")
        if not isinstance(value, str) or not value:
            raise ApiError(
                status_code=409,
                code="oidc_client_secret_unavailable",
                message="OIDC client secret is unavailable.",
            )
        return value

    def create(
        self,
        session: Session,
        *,
        key: str,
        name: str,
        enabled: bool,
        issuer: str,
        client_id: str,
        client_secret: str,
        auto_provision: bool,
        email_linking: bool,
        default_role_ids: list[uuid.UUID],
    ) -> OidcProviderConfig:
        normalized_key = self._provider_key(key)
        providers = self._raw_providers(session)
        if normalized_key in providers:
            raise ApiError(
                status_code=409,
                code="oidc_provider_key_conflict",
                message="OIDC provider key is already in use.",
            )

        normalized_name = name.strip()
        normalized_client_id = client_id.strip()
        if not normalized_name:
            raise ApiError(
                status_code=400,
                code="oidc_provider_name_invalid",
                message="OIDC provider name is invalid.",
            )
        if not normalized_client_id:
            raise ApiError(
                status_code=400,
                code="oidc_client_id_invalid",
                message="OIDC client ID is invalid.",
            )

        provider_id = uuid.uuid4()
        secret_ref = self._put_secret(
            session,
            provider_id=provider_id,
            existing_ref=None,
            client_secret=client_secret,
        )
        provider = OidcProviderConfig(
            id=provider_id,
            key=normalized_key,
            name=normalized_name,
            enabled=enabled,
            issuer=self._issuer(issuer),
            client_id=normalized_client_id,
            secret_ref=secret_ref,
            auto_provision=auto_provision,
            email_linking=email_linking,
            default_role_ids=self._roles(
                session,
                default_role_ids,
                auto_provision=auto_provision,
            ),
        )
        providers[normalized_key] = self._encode(
            provider
        )
        self._save(session, providers)
        return provider

    def update(
        self,
        session: Session,
        *,
        provider: OidcProviderConfig,
        changes: dict[str, object],
    ) -> OidcProviderConfig:
        updated = provider

        if "name" in changes:
            name = str(changes["name"]).strip()
            if not name:
                raise ApiError(
                    status_code=400,
                    code="oidc_provider_name_invalid",
                    message="OIDC provider name is invalid.",
                )
            updated = replace(
                updated,
                name=name,
            )
        if "enabled" in changes:
            updated = replace(
                updated,
                enabled=bool(changes["enabled"]),
            )
        if "issuer" in changes:
            updated = replace(
                updated,
                issuer=self._issuer(
                    str(changes["issuer"])
                ),
            )
        if "client_id" in changes:
            client_id = str(
                changes["client_id"]
            ).strip()
            if not client_id:
                raise ApiError(
                    status_code=400,
                    code="oidc_client_id_invalid",
                    message="OIDC client ID is invalid.",
                )
            updated = replace(
                updated,
                client_id=client_id,
            )

        auto_provision = (
            bool(changes["auto_provision"])
            if "auto_provision" in changes
            else updated.auto_provision
        )
        role_ids = (
            list(changes["default_role_ids"])
            if "default_role_ids" in changes
            else list(updated.default_role_ids)
        )
        updated = replace(
            updated,
            auto_provision=auto_provision,
            email_linking=(
                bool(changes["email_linking"])
                if "email_linking" in changes
                else updated.email_linking
            ),
            default_role_ids=self._roles(
                session,
                role_ids,
                auto_provision=auto_provision,
            ),
        )

        secret_action = str(
            changes.get(
                "client_secret_action",
                "keep",
            )
        )
        if secret_action not in {
            "keep",
            "replace",
            "clear",
        }:
            raise ApiError(
                status_code=400,
                code="oidc_client_secret_update_invalid",
                message="OIDC client secret action is invalid.",
            )

        old_secret_ref = updated.secret_ref
        delete_secret_ref: uuid.UUID | None = None

        if secret_action == "replace":
            raw = changes.get("client_secret")
            if not isinstance(raw, str):
                raise ApiError(
                    status_code=400,
                    code="oidc_client_secret_invalid",
                    message="OIDC client secret is invalid.",
                )
            candidate_ref = self._put_secret(
                session,
                provider_id=updated.id,
                existing_ref=old_secret_ref,
                client_secret=raw,
            )
            updated = replace(
                updated,
                secret_ref=candidate_ref,
            )
            delete_secret_ref = old_secret_ref
        elif secret_action == "clear":
            if "client_secret" in changes:
                raise ApiError(
                    status_code=400,
                    code="oidc_client_secret_update_invalid",
                    message=(
                        "OIDC client secret clear action "
                        "does not accept a replacement value."
                    ),
                )
            delete_secret_ref = old_secret_ref
            updated = replace(
                updated,
                secret_ref=None,
            )
        elif "client_secret" in changes:
            raise ApiError(
                status_code=400,
                code="oidc_client_secret_update_invalid",
                message=(
                    "OIDC client secret value requires "
                    "action=replace."
                ),
            )

        providers = self._raw_providers(session)
        providers[provider.key] = self._encode(
            updated
        )
        self._save(session, providers)

        if (
            delete_secret_ref is not None
            and delete_secret_ref != updated.secret_ref
        ):
            try:
                self.secret_store.delete(
                    session,
                    delete_secret_ref,
                    kind="oidc_client_secret",
                    owner_type="oidc_provider",
                    owner_id=updated.id,
                )
            except KeyError:
                pass
        return updated

    def delete(
        self,
        session: Session,
        *,
        provider: OidcProviderConfig,
    ) -> None:
        providers = self._raw_providers(session)
        providers.pop(provider.key, None)
        self._save(session, providers)
        if provider.secret_ref is not None:
            try:
                self.secret_store.delete(
                    session,
                    provider.secret_ref,
                    kind="oidc_client_secret",
                    owner_type="oidc_provider",
                    owner_id=provider.id,
                )
            except KeyError:
                pass
        session.flush()
