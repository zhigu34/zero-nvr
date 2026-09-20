from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


class Database:
    """Owns the SQLAlchemy engine/session factory for one application process."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        url = make_url(settings.effective_database_url)
        # SQLAlchemy still treats bare postgresql:// as the legacy psycopg2
        # driver. zero-nvr standardizes on psycopg3, while still accepting the
        # conventional driver-less PostgreSQL URL in deployment settings.
        if url.drivername in {"postgresql", "postgres"}:
            url = url.set(drivername="postgresql+psycopg")
        self.url = url
        self.engine = self._create_engine()
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

    @property
    def is_sqlite(self) -> bool:
        return self.url.get_backend_name() == "sqlite"

    def _create_engine(self) -> Engine:
        connect_args: dict[str, object] = {}

        if self.is_sqlite:
            connect_args = {
                "check_same_thread": False,
                "timeout": self.settings.sqlite_busy_timeout_ms / 1000,
            }

        engine = create_engine(
            self.url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )

        if self.is_sqlite:
            busy_timeout_ms = self.settings.sqlite_busy_timeout_ms
            synchronous = self.settings.sqlite_synchronous

            @event.listens_for(engine, "connect")
            def sqlite_connection_pragmas(dbapi_connection, _connection_record) -> None:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA foreign_keys = ON")
                    cursor.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
                    cursor.execute(f"PRAGMA synchronous = {synchronous}")
                finally:
                    cursor.close()

        return engine

    def initialize_runtime(self) -> None:
        """Prepare runtime DB settings without running schema migrations."""

        if not self.is_sqlite:
            return

        database_path = self.url.database
        if database_path and database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)

        synchronous = self.settings.sqlite_synchronous
        with self.engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode = WAL")
            connection.exec_driver_sql(f"PRAGMA synchronous = {synchronous}")
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            connection.exec_driver_sql(
                f"PRAGMA busy_timeout = {self.settings.sqlite_busy_timeout_ms}"
            )

    @contextmanager
    def session(self) -> Iterator[Session]:
        db = self.session_factory()
        try:
            yield db
        finally:
            db.close()

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def close(self) -> None:
        self.engine.dispose()
