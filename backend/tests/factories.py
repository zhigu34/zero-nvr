"""Shared construction helpers for backend tests.

``conftest.py`` only pinned the deployment secret, so every module rebuilt the
same fixtures by hand: ``make_app`` was defined 40 times, ``make_database`` 32
times, ``setup_admin`` 23 times. The copies had drifted — only some set
``session_cookie_secure=False``, only some set ``environment="test"`` — so a
change to application wiring had to be found and applied file by file.

The helpers take ``**settings_kwargs`` rather than a parameter per setting, so a
caller states only what is distinctive about its case (its own secret, database
file, prebuffer paths, ZLM secrets) while the defaults that every test shares
live here once. Migrated call sites keep their original literal values, so the
settings a test constructs are unchanged.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import Base, Database
from app.main import create_app

__all__ = [
    "ADMIN_PASSWORD",
    "build_test_app",
    "create_admin_and_login",
    "make_test_app",
    "make_test_database",
]

# The operator password used by every authenticated test.
ADMIN_PASSWORD = "correct-horse-battery-staple"


def build_test_app(settings: Settings) -> FastAPI:
    """Create the application and materialise the schema on its engine.

    Tests use ``Base.metadata.create_all`` instead of Alembic so each case starts
    from a clean database in its own ``tmp_path``; migration behaviour is covered
    separately by the migration tests.
    """
    app = create_app(settings)
    Base.metadata.create_all(app.state.database.engine)
    return app


def make_test_app(
    tmp_path: Path,
    **settings_kwargs: Any,
) -> FastAPI:
    """Build an application wired to a throwaway SQLite database.

    Shared defaults, and why each is shared:

    * ``environment="test"`` — selects test behaviour and relaxes prod guards;
    * ``data_dir``/``cache_dir`` under the case's ``tmp_path``;
    * ``session_cookie_secure=False`` — the TestClient speaks plain HTTP, so a
      ``Secure`` cookie is never sent back and every login would look broken.
    """
    settings = Settings(
        environment="test",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        session_cookie_secure=False,
        **settings_kwargs,
    )
    return build_test_app(settings)


def make_test_database(
    tmp_path: Path,
    **settings_kwargs: Any,
) -> tuple[Settings, Database]:
    """Build an initialised database for service-level tests.

    Returns the settings alongside it because most service tests need both to
    construct the service under test.

    Unlike :func:`make_test_app` this does not force ``environment="test"`` or
    ``session_cookie_secure``: service-level tests never drive HTTP, and the
    bodies it replaces deliberately left those unset. Only the temp directories
    are shared.
    """
    settings = Settings(
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        **settings_kwargs,
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)
    return settings, database


def create_admin_and_login(
    client: TestClient,
    *,
    password: str = ADMIN_PASSWORD,
    display_name: str = "Administrator",
    username: str = "admin",
) -> uuid.UUID:
    """Complete first-run setup and log in, returning the administrator id.

    Uses the real endpoints rather than inserting a row, so the tests exercise
    the same setup and login path the product uses.
    """
    created = client.post(
        "/api/v1/setup/administrator",
        json={
            "username": username,
            "display_name": display_name,
            "password": password,
        },
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    return uuid.UUID(created.json()["id"])
