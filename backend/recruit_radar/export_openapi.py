"""``python -m recruit_radar.export_openapi``: write ``contracts/openapi.json`` (spec 03).

The schema is generated from the live FastAPI app (no database is created or touched) and
printed the way the repository's Prettier configuration prints JSON (width 100, objects always
expanded, arrays collapsed when they fit), so ``prettier --check`` stays green after an export.
A pytest compares the committed file with the live schema and fails on drift.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from .api import create_app
from .config import BACKEND_DIR, Settings

DEFAULT_OUTPUT: Final = BACKEND_DIR.parent / "contracts" / "openapi.json"
PRINT_WIDTH: Final = 100


def build_schema() -> dict[str, Any]:
    """The OpenAPI document of the app, built without opening the real database."""
    with tempfile.TemporaryDirectory(prefix="recruit-radar-openapi-") as scratch:
        settings = Settings(db_path=Path(scratch) / "schema.sqlite3")
        app = create_app(settings, run_migrations=False)
        schema = app.openapi()
        app.state.recruit_radar.engine.dispose()
    return schema


def _scalar(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _is_flat(value: object) -> bool:
    if isinstance(value, dict):
        return not value
    if isinstance(value, list):
        return not value
    return True


def _format(value: object, indent: int, column: int, trailing: int) -> str:
    """Prettier-style JSON: ``column`` is where the value starts, ``trailing`` the characters
    (a comma) that must still fit on the same line."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = " " * (indent + 2)
        items = list(value.items())
        lines: list[str] = []
        for position, (key, child) in enumerate(items):
            prefix = f"{inner}{_scalar(key)}: "
            last = position == len(items) - 1
            lines.append(prefix + _format(child, indent + 2, len(prefix), 0 if last else 1))
        return "{\n" + ",\n".join(lines) + "\n" + " " * indent + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(_is_flat(child) for child in value):
            flat = "[" + ", ".join(_format(child, 0, 0, 0) for child in value) + "]"
            if column + len(flat) + trailing <= PRINT_WIDTH:
                return flat
        inner = " " * (indent + 2)
        lines = []
        for position, child in enumerate(value):
            last = position == len(value) - 1
            lines.append(inner + _format(child, indent + 2, indent + 2, 0 if last else 1))
        return "[\n" + ",\n".join(lines) + "\n" + " " * indent + "]"
    return _scalar(value)


def render(schema: dict[str, Any]) -> str:
    """The exact text of ``contracts/openapi.json`` for ``schema``."""
    return _format(schema, 0, 0, 0) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recruit_radar.export_openapi")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="file to write")
    parser.add_argument(
        "--check", action="store_true", help="do not write; exit 1 when the file differs"
    )
    args = parser.parse_args(argv)
    text = render(build_schema())
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else None
        if current != text:
            print(f"{args.output} is out of date; run python -m recruit_radar.export_openapi")
            return 1
        print(f"{args.output} is up to date")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {args.output} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
