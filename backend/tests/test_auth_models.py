from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.db import Base, Database
from app.modules.auth.models import Role, RolePermission, User, UserSession


def test_auth_models_and_utc_roundtrip(tmp_path: Path) -> None:
    settings = Settings(
        secret_key="z" * 32,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
    )
    database = Database(settings)
    database.initialize_runtime()
    Base.metadata.create_all(database.engine)

    expires_at = datetime.now(UTC) + timedelta(hours=1)

    try:
        with database.session() as session:
            role = Role(
                name="Administrator",
                description="Built-in administrator",
                built_in=True,
            )
            role.permissions.append(RolePermission(permission="system.manage"))
            user = User(
                username="admin",
                display_name="Administrator",
                password_hash="test-only-hash",
                enabled=True,
            )
            user.roles.append(role)
            session.add(user)
            session.flush()

            user_session = UserSession(
                user_id=user.id,
                expires_at=expires_at,
                client_info={"agent": "pytest"},
            )
            session.add(user_session)
            session.commit()
            session_id = user_session.id

        with database.session() as session:
            loaded = session.get(UserSession, session_id)
            assert loaded is not None
            assert loaded.expires_at.tzinfo is not None
            assert loaded.expires_at.utcoffset() == timedelta(0)
    finally:
        database.close()
