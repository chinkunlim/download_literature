"""Alembic environment: migrates the database named by the config layer (`AppConfig.database_url`).

Run `uv run alembic upgrade head` to bring the database up to date, and
`uv run alembic revision --autogenerate -m "..."` after changing `adapters/db/models.py`.
"""

from __future__ import annotations

from alembic import context

from download_literature.adapters.db.engine import create_db_engine
from download_literature.adapters.db.models import Base
from download_literature.config.settings import load_config

target_metadata = Base.metadata


def _url() -> str:
    """Database URL: the one passed by `upgrade_database`, else the config layer's.

    Returns:
        SQLAlchemy URL.
    """
    return context.config.get_main_option("sqlalchemy.url") or load_config().database_url


def run_migrations_offline() -> None:
    """Emit SQL without a database connection."""
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    engine = create_db_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
