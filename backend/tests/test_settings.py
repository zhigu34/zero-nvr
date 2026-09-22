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


def test_blank_turn_shared_secret_means_not_configured() -> None:
    settings = Settings(
        secret_key="x" * 32,
        turn_shared_secret="",
    )

    assert settings.turn_shared_secret is None


def test_turn_shared_secret_rejects_short_non_empty_value() -> None:
    with pytest.raises(ValidationError):
        Settings(
            secret_key="x" * 32,
            turn_shared_secret="too-short",
        )


def test_turn_shared_secret_accepts_configured_value() -> None:
    settings = Settings(
        secret_key="x" * 32,
        turn_shared_secret="t" * 32,
    )

    assert settings.turn_shared_secret is not None
    assert (
        settings.turn_shared_secret.get_secret_value()
        == "t" * 32
    )


def test_secret_key_file_bootstrap(tmp_path: Path) -> None:
    key_file = tmp_path / "zero-nvr-secret-key"
    key_file.write_text(
        ("f" * 40) + "\n",
        encoding="utf-8",
    )

    settings = Settings(
        secret_key_file=key_file,
    )

    assert (
        settings.secret_key.get_secret_value()
        == "f" * 40
    )


def test_secret_key_file_rejects_direct_key_conflict(
    tmp_path: Path,
) -> None:
    key_file = tmp_path / "zero-nvr-secret-key"
    key_file.write_text(
        "f" * 40,
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match="configure only one",
    ):
        Settings(
            secret_key="x" * 40,
            secret_key_file=key_file,
        )


def test_secret_key_file_must_be_readable(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValidationError,
        match="could not be read",
    ):
        Settings(
            secret_key_file=(
                tmp_path / "missing-secret-key"
            ),
        )
