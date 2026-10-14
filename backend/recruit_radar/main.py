"""``python -m recruit_radar``: run the API with uvicorn on loopback (spec 03)."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from alembic.util.exc import CommandError
from sqlalchemy.exc import SQLAlchemyError

from .api import create_app
from .config import LOOPBACK_HOSTS, ConfigError, Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m recruit_radar",
        description="Run the RecruitRadar backend. Settings come from RECRUIT_RADAR_* variables; "
        "these options override them.",
    )
    parser.add_argument("--host", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port (default 8787)")
    parser.add_argument("--db-path", type=Path, help="SQLite file (default backend/data/...)")
    return parser


def build_settings(argv: Sequence[str] | None = None) -> Settings:
    args = _parser().parse_args(argv)
    settings = Settings.from_env()
    changes: dict[str, object] = {}
    if args.host:
        changes["host"] = args.host
    if args.port is not None:
        changes["port"] = args.port
    if args.db_path is not None:
        changes["db_path"] = args.db_path.expanduser().resolve()
    return settings.with_overrides(**changes) if changes else settings


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = build_settings(argv)
    except ConfigError as exc:
        print(f"recruit_radar: configuration error: {exc}")
        return 2
    if settings.host not in LOOPBACK_HOSTS:
        logging.getLogger("recruit_radar").warning(
            "Binding to %s: the API has no authentication and is meant for loopback only",
            settings.host,
        )
    try:
        app = create_app(settings)
    except (SQLAlchemyError, CommandError, OSError) as exc:
        # A garbage file, a read-only folder or a full disk: say which file and why, not a trace.
        print(
            f"recruit_radar: cannot open the database at {settings.db_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return 2
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    return 0
