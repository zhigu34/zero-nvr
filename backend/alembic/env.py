from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app.core.db.base import Base

# Import canonical model modules so their tables are registered in Base.metadata.
from app.modules.alerts import models as alert_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.backups import models as backup_models  # noqa: F401
from app.modules.cameras import models as camera_models  # noqa: F401
from app.modules.events import models as event_models  # noqa: F401
from app.modules.exports import models as export_models  # noqa: F401
from app.modules.notifications import models as notification_models  # noqa: F401
from app.modules.recordings import models as recording_models  # noqa: F401
from app.modules.storage import models as storage_models  # noqa: F401
from app.modules.system import models as system_models  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def effective_database_url() -> str:
    explicit = os.getenv("ZERO_NVR_DATABASE_URL")
    if explicit:
        return explicit

    data_dir = Path(os.getenv("ZERO_NVR_DATA_DIR", "/var/lib/zero-nvr"))
    db_path = (data_dir / "zero-nvr.db").resolve()
    return f"sqlite:///{db_path}"


config.set_main_option(
    "sqlalchemy.url",
    effective_database_url().replace("%", "%%"),
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    is_sqlite_engine = connectable.dialect.name == "sqlite"

    if is_sqlite_engine:
        @event.listens_for(connectable, "connect")
        def sqlite_migration_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA busy_timeout = 5000")
            finally:
                cursor.close()

    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=is_sqlite,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
