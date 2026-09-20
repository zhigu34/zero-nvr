from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

import app.cli as cli_module
from app.core.config import Settings
from app.core.db import Database
from app.modules.auth.models import User


def _config() -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(
        str(root / "alembic.ini")
    )
    config.set_main_option(
        "script_location",
        str(root / "alembic"),
    )
    return config


def _upgrade(url: str) -> None:
    previous = os.environ.get(
        "ZERO_NVR_DATABASE_URL"
    )
    os.environ[
        "ZERO_NVR_DATABASE_URL"
    ] = url
    try:
        command.upgrade(
            _config(),
            "head",
        )
    finally:
        if previous is None:
            os.environ.pop(
                "ZERO_NVR_DATABASE_URL",
                None,
            )
        else:
            os.environ[
                "ZERO_NVR_DATABASE_URL"
            ] = previous


def _database(
    tmp_path: Path,
    name: str,
) -> tuple[Settings, Database]:
    url = (
        f"sqlite:///{tmp_path / name}"
    )
    _upgrade(url)
    settings = Settings(
        secret_key=(
            "database-transfer-cli-test-"
            "secret-key-32-bytes-minimum"
        ),
        environment="test",
        database_url=url,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    database = Database(settings)
    database.initialize_runtime()
    return settings, database


def test_database_transfer_command_uses_env_url_and_preserves_data(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    settings, source = _database(
        tmp_path,
        "source.db",
    )
    target_url = (
        f"sqlite:///{tmp_path / 'target.db'}"
    )

    with source.session() as session:
        session.add(
            User(
                username="transfer-cli-user",
                display_name="Transfer CLI User",
                email=None,
                password_hash=None,
                enabled=True,
            )
        )
        session.commit()

    monkeypatch.setattr(
        cli_module,
        "_settings_database",
        lambda: (settings, source),
    )
    monkeypatch.setenv(
        "TEST_DATABASE_TRANSFER_TARGET",
        target_url,
    )

    result = (
        cli_module.database_transfer_command(
            argparse.Namespace(
                target_url_env=(
                    "TEST_DATABASE_TRANSFER_TARGET"
                ),
                batch_size=2,
                allow_same_backend=True,
            )
        )
    )
    assert result == 0

    output = capsys.readouterr().out
    assert '"transferred": true' in output
    assert '"source_backend": "sqlite"' in output
    assert '"target_backend": "sqlite"' in output
    assert target_url not in output

    target_settings = settings.model_copy(
        update={
            "database_url": target_url,
        }
    )
    target = Database(target_settings)
    try:
        with target.session() as session:
            copied = session.scalar(
                select(User).where(
                    User.username
                    == "transfer-cli-user"
                )
            )
            assert copied is not None
            assert (
                copied.display_name
                == "Transfer CLI User"
            )
    finally:
        target.close()


def test_database_transfer_command_requires_target_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, source = _database(
        tmp_path,
        "missing-target.db",
    )
    monkeypatch.setattr(
        cli_module,
        "_settings_database",
        lambda: (settings, source),
    )
    monkeypatch.delenv(
        "MISSING_DATABASE_TRANSFER_TARGET",
        raising=False,
    )

    with pytest.raises(
        RuntimeError,
        match="environment variable is empty",
    ):
        cli_module.database_transfer_command(
            argparse.Namespace(
                target_url_env=(
                    "MISSING_DATABASE_TRANSFER_TARGET"
                ),
                batch_size=500,
                allow_same_backend=False,
            )
        )

    source.close()


def test_database_transfer_command_refuses_same_backend_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, source = _database(
        tmp_path,
        "same-source.db",
    )
    target_url = (
        f"sqlite:///{tmp_path / 'same-target.db'}"
    )
    monkeypatch.setattr(
        cli_module,
        "_settings_database",
        lambda: (settings, source),
    )
    monkeypatch.setenv(
        "SAME_DATABASE_TRANSFER_TARGET",
        target_url,
    )

    with pytest.raises(
        RuntimeError,
        match="must differ",
    ):
        cli_module.database_transfer_command(
            argparse.Namespace(
                target_url_env=(
                    "SAME_DATABASE_TRANSFER_TARGET"
                ),
                batch_size=500,
                allow_same_backend=False,
            )
        )
