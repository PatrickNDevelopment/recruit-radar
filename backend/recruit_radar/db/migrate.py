"""Run Alembic migrations programmatically (used at start-up and by the tests)."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import Engine

from alembic import command

ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"


def alembic_config(engine: Engine) -> Config:
    """An Alembic ``Config`` bound to ``engine`` (no alembic.ini needed)."""
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("path_separator", "os")
    config.attributes["engine"] = engine
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    command.upgrade(alembic_config(engine), revision)


def downgrade(engine: Engine, revision: str = "base") -> None:
    command.downgrade(alembic_config(engine), revision)
