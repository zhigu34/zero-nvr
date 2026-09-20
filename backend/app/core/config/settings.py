from __future__ import annotations

from functools import lru_cache
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
    recordings_dir: Path = Path("/recordings")

    database_url: str | None = None
    sqlite_busy_timeout_ms: int = 5000
    sqlite_synchronous: str = "NORMAL"

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
