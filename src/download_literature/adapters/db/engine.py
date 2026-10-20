"""Database engine and session helpers (SQLAlchemy 2.0).

The URL comes from the config layer (`AppConfig.database_url`, default `<DATA_DIR>/db/literature.db`).
Use `session_scope()` for every unit of work: commit on success, rollback on error, never call
external services while a transaction is open.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from download_literature.adapters.db.models import Base

logger = logging.getLogger(__name__)


def create_db_engine(url: str) -> Engine:
    """Create an engine; SQLite files get their folder created and a busy timeout for concurrent use.

    Args:
        url: SQLAlchemy URL such as `sqlite:////path/literature.db` or `sqlite://` (in memory).

    Returns:
        The engine.
    """
    if url.startswith("sqlite:///") and not url.endswith(":memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"timeout": 30} if url.startswith("sqlite") else {})
    if url == "sqlite://":
        return engine

    @event.listens_for(engine, "connect")
    def _wal(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        """Use write-ahead logging so the web page can read while a job writes.

        Args:
            dbapi_conn: Raw SQLite connection.
            _record: SQLAlchemy connection record (unused).
        """
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    return engine


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def upgrade_database(url: str) -> None:
    """Bring the database to the latest schema with Alembic (run at start-up by the CLI and web app).

    Args:
        url: Database URL.
    """
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    logger.info("database schema up to date url=%s", url.split("///")[-1])


def init_schema(engine: Engine) -> None:
    """Create all tables (tests and first start; production upgrades go through Alembic).

    Args:
        engine: Database engine.
    """
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Run one transaction: commit on success, rollback on error.

    Args:
        factory: Session factory bound to the engine.

    Yields:
        The session.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("database transaction rolled back")
        raise
    finally:
        session.close()
