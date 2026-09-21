from __future__ import annotations

from functools import lru_cache
import ipaddress
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bootstrap settings only.

    User-editable product settings belong in the product database/UI rather
    than growing this environment contract indefinitely.
    """

    model_config = SettingsConfigDict(
        env_prefix="ZERO_NVR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "zero-nvr"
    app_version: str = "0.1.0"
    environment: str = "production"

    secret_key: SecretStr
    secret_key_previous: list[SecretStr] = Field(default_factory=list)

    data_dir: Path = Path("/var/lib/zero-nvr")
    cache_dir: Path = Path("/var/cache/zero-nvr")
    playback_cache_max_bytes: int = 4 * 1024 * 1024 * 1024
    playback_cache_ttl_seconds: int = 6 * 60 * 60
    playback_restore_lock_ttl_seconds: int = 15 * 60
    recordings_dir: Path = Path("/recordings")
    prebuffer_dir: Path = Path("/prebuffer")
    prebuffer_fragment_seconds: int = 5
    prebuffer_buffer_seconds: int = 35
    prebuffer_require_tmpfs: bool = True
    huey_db_path: Path = Path("/var/lib/zero-nvr/huey.db")

    database_url: str | None = None
    sqlite_busy_timeout_ms: int = 5000
    sqlite_synchronous: str = "NORMAL"

    session_cookie_name: str = "zero_nvr_session"
    session_cookie_secure: bool = True
    session_ttl_hours: int = 24 * 30

    zlm_base_url: str = "http://zlmediakit"
    zlm_rtsp_base_url: str = "rtsp://zlmediakit:554"
    zlm_public_base_url: str = "/zlm"
    zlm_webrtc_port: int = 8000
    zlm_webrtc_extern_ip: str | None = None
    zlm_api_secret: SecretStr | None = None
    zlm_hook_secret: SecretStr | None = None
    zlm_timeout_seconds: float = 8.0
    zlm_probe_timeout_seconds: float = 12.0

    onvif_timeout_seconds: float = 10.0
    onvif_discovery_timeout_seconds: float = 3.0

    rclone_binary: str = "rclone"
    rclone_timeout_seconds: float = 300.0

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    ffmpeg_timeout_seconds: float = 3600.0

    restic_binary: str = "restic"
    restic_timeout_seconds: float = 3600.0
    pg_dump_binary: str = "pg_dump"
    database_backup_timeout_seconds: float = 1800.0
    deployment_config_dir: Path | None = None

    log_level: str = "INFO"

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw.encode("utf-8")) < 32:
            raise ValueError("ZERO_NVR_SECRET_KEY must be at least 32 bytes")
        return value

    @field_validator("secret_key_previous")
    @classmethod
    def validate_previous_secret_keys(
        cls,
        values: list[SecretStr],
    ) -> list[SecretStr]:
        for value in values:
            if len(value.get_secret_value().encode("utf-8")) < 32:
                raise ValueError(
                    "every ZERO_NVR_SECRET_KEY_PREVIOUS entry must be at least 32 bytes"
                )
        return values

    @field_validator("zlm_hook_secret")
    @classmethod
    def validate_zlm_hook_secret(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError(
                "ZERO_NVR_ZLM_HOOK_SECRET must be at least 32 bytes"
            )
        return value

    @field_validator("prebuffer_fragment_seconds")
    @classmethod
    def validate_prebuffer_fragment_seconds(cls, value: int) -> int:
        if value < 2 or value > 30:
            raise ValueError(
                "ZERO_NVR_PREBUFFER_FRAGMENT_SECONDS must be between 2 and 30"
            )
        return value

    @field_validator("prebuffer_buffer_seconds")
    @classmethod
    def validate_prebuffer_buffer_seconds(cls, value: int) -> int:
        if value < 10 or value > 600:
            raise ValueError(
                "ZERO_NVR_PREBUFFER_BUFFER_SECONDS must be between 10 and 600"
            )
        return value

    @field_validator("playback_cache_max_bytes")
    @classmethod
    def validate_playback_cache_max_bytes(cls, value: int) -> int:
        minimum = 64 * 1024 * 1024
        maximum = 1024 * 1024 * 1024 * 1024
        if value < minimum or value > maximum:
            raise ValueError(
                "ZERO_NVR_PLAYBACK_CACHE_MAX_BYTES must be between "
                "67108864 and 1099511627776"
            )
        return value

    @field_validator(
        "playback_cache_ttl_seconds",
        "playback_restore_lock_ttl_seconds",
    )
    @classmethod
    def validate_playback_cache_timeouts(cls, value: int) -> int:
        if value < 60 or value > 7 * 24 * 60 * 60:
            raise ValueError(
                "playback cache timeouts must be between 60 and 604800 seconds"
            )
        return value

    @field_validator("session_ttl_hours")
    @classmethod
    def validate_session_ttl_hours(cls, value: int) -> int:
        if value < 1 or value > 24 * 365:
            raise ValueError(
                "ZERO_NVR_SESSION_TTL_HOURS must be between 1 and 8760"
            )
        return value

    @field_validator(
        "zlm_timeout_seconds",
        "zlm_probe_timeout_seconds",
        "onvif_timeout_seconds",
        "onvif_discovery_timeout_seconds",
    )
    @classmethod
    def validate_positive_timeout(cls, value: float) -> float:
        if value <= 0 or value > 120:
            raise ValueError("integration timeouts must be greater than 0 and at most 120 seconds")
        return value

    @field_validator("zlm_public_base_url")
    @classmethod
    def validate_zlm_public_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if normalized.startswith("/"):
            return normalized or "/"
        if normalized.startswith(("http://", "https://")):
            return normalized
        raise ValueError(
            "ZERO_NVR_ZLM_PUBLIC_BASE_URL must be same-origin /path or http(s) URL"
        )

    @field_validator("zlm_webrtc_port")
    @classmethod
    def validate_zlm_webrtc_port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError(
                "ZERO_NVR_ZLM_WEBRTC_PORT must be between 1 and 65535"
            )
        return value

    @field_validator("zlm_webrtc_extern_ip")
    @classmethod
    def validate_zlm_webrtc_extern_ip(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            ipaddress.ip_address(normalized)
        except ValueError as exc:
            raise ValueError(
                "ZERO_NVR_ZLM_WEBRTC_EXTERN_IP must be an IPv4 or IPv6 address"
            ) from exc
        return normalized

    @field_validator(
        "restic_timeout_seconds",
        "database_backup_timeout_seconds",
    )
    @classmethod
    def validate_backup_timeouts(cls, value: float) -> float:
        if value <= 0 or value > 21600:
            raise ValueError(
                "backup timeouts must be greater than 0 and at most 21600"
            )
        return value

    @field_validator("ffmpeg_timeout_seconds")
    @classmethod
    def validate_ffmpeg_timeout(cls, value: float) -> float:
        if value <= 0 or value > 21600:
            raise ValueError(
                "ZERO_NVR_FFMPEG_TIMEOUT_SECONDS must be greater than 0 and at most 21600"
            )
        return value

    @field_validator("rclone_timeout_seconds")
    @classmethod
    def validate_rclone_timeout(cls, value: float) -> float:
        if value <= 0 or value > 3600:
            raise ValueError(
                "ZERO_NVR_RCLONE_TIMEOUT_SECONDS must be greater than 0 and at most 3600"
            )
        return value

    @field_validator("zlm_base_url")
    @classmethod
    def validate_zlm_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("ZERO_NVR_ZLM_BASE_URL must use http:// or https://")
        return normalized

    @field_validator("zlm_rtsp_base_url")
    @classmethod
    def validate_zlm_rtsp_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith("rtsp://"):
            raise ValueError(
                "ZERO_NVR_ZLM_RTSP_BASE_URL must use rtsp://"
            )
        if "@" in normalized:
            raise ValueError(
                "ZERO_NVR_ZLM_RTSP_BASE_URL must not contain credentials"
            )
        return normalized

    @field_validator("sqlite_synchronous")
    @classmethod
    def validate_sqlite_synchronous(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
            raise ValueError(
                "ZERO_NVR_SQLITE_SYNCHRONOUS must be OFF, NORMAL, FULL, or EXTRA"
            )
        return normalized

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url

        db_path = (self.data_dir / "zero-nvr.db").resolve()
        return f"sqlite:///{db_path}"

    def ensure_runtime_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
