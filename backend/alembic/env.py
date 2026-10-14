"""Alembic environment: migrations run against the app's own engine (PRAGMAs included)."""

from __future__ import annotations

from sqlalchemy import Engine

from alembic import context
from recruit_radar.config import Settings
from recruit_radar.db.models import Base
from recruit_radar.db.session import create_db_engine

config = context.config
target_metadata = Base.metadata


def _engine() -> Engine:
    """The engine handed in by ``recruit_radar.db.migrate`` or one built from the environment."""
    supplied = config.attributes.get("engine")
    if isinstance(supplied, Engine):
        return supplied
    return create_db_engine(Settings.from_env().db_path)


def run_migrations_offline() -> None:
    url = _engine().url.render_as_string(hide_password=False)
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with _engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        if connection.in_transaction():
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
