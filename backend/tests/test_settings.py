from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_database_is_sqlite_under_data_dir(tmp_path: Path) -> None:
    settings = Settings(
        secret_key="x" * 32,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )

    assert settings.effective_database_url.startswith("sqlite:///")
    assert settings.effective_database_url.endswith("/zero-nvr.db")


def test_runtime_directories_are_created(tmp_path: Path) -> None:
    settings = Settings(
        secret_key="x" * 32,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )

    settings.ensure_runtime_directories()

    assert settings.data_dir.is_dir()
    assert settings.cache_dir.is_dir()


def test_secret_key_is_required_and_must_be_long_enough() -> None:
    with pytest.raises(ValidationError):
        Settings(secret_key="too-short")


@pytest.mark.parametrize("value", ["OFF", "NORMAL", "FULL", "EXTRA", "normal"])
def test_sqlite_synchronous_accepts_supported_values(value: str) -> None:
    settings = Settings(secret_key="x" * 32, sqlite_synchronous=value)
    assert settings.sqlite_synchronous == value.upper()


def test_sqlite_synchronous_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Settings(secret_key="x" * 32, sqlite_synchronous="FASTEST")
