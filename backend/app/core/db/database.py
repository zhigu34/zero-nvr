from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class SQLiteRuntimeHealth:
    journal_mode: str
    busy_timeout_ms: int
    wal_autocheckpoint_pages: int
    page_size_bytes: int
    wal_pages: int
    checkpointed_pages: int
    backlog_pages: int
    wal_bytes: int
    checkpoint_busy: bool
    write_pressure: str


class Database:
    """Owns the SQLAlchemy engine/session factory for one application process."""

    sqlite_wal_autocheckpoint_pages = 1000

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
                    cursor.execute(
                        "PRAGMA wal_autocheckpoint = "
                        f"{self.sqlite_wal_autocheckpoint_pages}"
                    )
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
            connection.exec_driver_sql(
                "PRAGMA wal_autocheckpoint = "
                f"{self.sqlite_wal_autocheckpoint_pages}"
            )

    @classmethod
    def _sqlite_write_pressure(
        cls,
        *,
        wal_pages: int,
        backlog_pages: int,
        checkpoint_busy: bool,
    ) -> str:
        threshold = cls.sqlite_wal_autocheckpoint_pages
        if (
            checkpoint_busy
            or backlog_pages >= threshold * 2
            or wal_pages >= threshold * 8
        ):
            return "high"
        if (
            backlog_pages >= threshold
            or wal_pages >= threshold * 4
        ):
            return "elevated"
        return "normal"

    def sqlite_runtime_health(
        self,
    ) -> SQLiteRuntimeHealth | None:
        """Sample bounded SQLite WAL/checkpoint state for product health."""

        if not self.is_sqlite:
            return None

        with self.engine.connect() as connection:
            journal_mode = str(
                connection.exec_driver_sql(
                    "PRAGMA journal_mode"
                ).scalar_one()
            ).lower()
            busy_timeout_ms = int(
                connection.exec_driver_sql(
                    "PRAGMA busy_timeout"
                ).scalar_one()
            )
            wal_autocheckpoint_pages = int(
                connection.exec_driver_sql(
                    "PRAGMA wal_autocheckpoint"
                ).scalar_one()
            )
            page_size_bytes = int(
                connection.exec_driver_sql(
                    "PRAGMA page_size"
                ).scalar_one()
            )
            checkpoint = connection.exec_driver_sql(
                "PRAGMA wal_checkpoint(PASSIVE)"
            ).one()

        checkpoint_busy = bool(int(checkpoint[0]))
        wal_pages = max(0, int(checkpoint[1]))
        checkpointed_pages = max(0, int(checkpoint[2]))
        backlog_pages = max(
            0,
            wal_pages - checkpointed_pages,
        )

        wal_bytes = 0
        database_path = self.url.database
        if database_path and database_path != ":memory:":
            try:
                wal_bytes = Path(
                    f"{database_path}-wal"
                ).stat().st_size
            except OSError:
                wal_bytes = 0

        write_pressure = self._sqlite_write_pressure(
            wal_pages=wal_pages,
            backlog_pages=backlog_pages,
            checkpoint_busy=checkpoint_busy,
        )
        return SQLiteRuntimeHealth(
            journal_mode=journal_mode,
            busy_timeout_ms=busy_timeout_ms,
            wal_autocheckpoint_pages=(
                wal_autocheckpoint_pages
            ),
            page_size_bytes=page_size_bytes,
            wal_pages=wal_pages,
            checkpointed_pages=checkpointed_pages,
            backlog_pages=backlog_pages,
            wal_bytes=wal_bytes,
            checkpoint_busy=checkpoint_busy,
            write_pressure=write_pressure,
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
