from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.db.base import Base

# Import canonical model modules so their tables are registered in Base.metadata.
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
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

    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        if is_sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            connection.exec_driver_sql("PRAGMA busy_timeout = 5000")

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
