"""Golden CSV import vectors: the Python importer must reproduce contracts/vectors/csv-import.json.

The TypeScript importer (src/engine/csv.ts) is held to the same file by tests/csv-vectors.test.ts,
so the two implementations cannot drift apart silently (they once did: whitespace-only lines,
trailing empty cells, spaces around quotes, tab/NBSP in headers, NUL, apostrophe-led formulas).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from recruit_radar.services.csv_io import CsvFileError, parse_postings

VECTOR_FILE = Path(__file__).resolve().parents[2] / "contracts" / "vectors" / "csv-import.json"


def _load() -> dict[str, Any]:
    if not VECTOR_FILE.exists():
        if os.environ.get("RR_REQUIRE_VECTORS") == "1":
            pytest.fail(f"RR_REQUIRE_VECTORS=1 but {VECTOR_FILE} is missing")
        pytest.skip(f"{VECTOR_FILE} is missing; set RR_REQUIRE_VECTORS=1 to make this a failure")
    loaded: dict[str, Any] = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))
    return loaded


def expand(spec: Any) -> str:
    """Turn a vector's ``text`` (a string or a generator object) into the CSV text."""
    if isinstance(spec, str):
        return spec
    if "repeat" in spec:
        repeat = spec["repeat"]
        return repeat["head"] + "".join(
            repeat["row"].replace("{i}", str(i)) for i in range(repeat["count"])
        )
    if "pad" in spec:
        pad = spec["pad"]
        prefix = ("﻿" if pad["bom"] else "") + pad["head"]
        remaining = pad["total_bytes"] - len(prefix.encode("utf-8"))
        unit = len(pad["fill"].encode("utf-8"))
        count = remaining // unit
        return prefix + pad["fill"] * count + "x" * (remaining - count * unit)
    if "parts" in spec:
        return "".join(
            part if isinstance(part, str) else part["fill"] * part["count"]
            for part in spec["parts"]
        )
    raise AssertionError(f"unknown text spec {spec!r}")


def _warning_kind(message: str) -> str:
    if "has no header name" in message:
        return "blank_header"
    if message.startswith("Unknown column"):
        return "unknown_column"
    if message.startswith("Same posting as"):
        return "duplicate_row"
    if "is after the import time" in message:
        return "future_observed"
    raise AssertionError(f"unclassified warning: {message!r}")


def run(text: str, imported_at: str) -> dict[str, Any]:
    try:
        parsed = parse_postings(text, default_observed=imported_at, now=imported_at)
    except CsvFileError as error:
        return {
            "file_error": error.code,
            "accepted": 0,
            "rejected": 0,
            "rows": [],
            "errors": [],
            "warnings": [],
        }
    rows = [
        [
            row.observed_at,
            row.posting.company_name,
            row.posting.title,
            row.posting.location,
            row.posting.work_mode,
            row.posting.department,
            row.posting.url,
            row.posting.posted_at,
            row.posting.source_posting_id,
        ]
        for row in parsed.rows
    ]
    # canonical order: effective instant ascending, then file order (sorted() is stable)
    rows.sort(key=lambda cells: cells[0] or imported_at)
    errors = sorted({(e.line, e.field) for e in parsed.errors}, key=lambda t: (t[0], t[1] or ""))
    # multiplicity is meaningful (two unknown columns are two warnings): no de-duplication
    warnings = sorted((w.line, _warning_kind(w.message)) for w in parsed.warnings)
    return {
        "file_error": None,
        "accepted": len(parsed.rows),
        "rejected": parsed.rejected,
        "rows": rows,
        "errors": [list(pair) for pair in errors],
        "warnings": [list(pair) for pair in warnings],
    }


def _cases() -> list[Any]:
    if not VECTOR_FILE.exists():
        return []
    data = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))
    return [pytest.param(case, id=case["id"]) for case in data["cases"]]


def test_the_vector_file_is_present_and_substantial() -> None:
    data = _load()
    assert data["kind"] == "csv-import"
    assert len(data["cases"]) >= 40
    assert len({case["id"] for case in data["cases"]}) == len(data["cases"])


@pytest.mark.parametrize("case", _cases())
def test_python_importer_reproduces_the_vector(case: dict[str, Any]) -> None:
    imported_at = _load()["imported_at"]
    got = run(expand(case["text"]), imported_at)
    want = case["expected"]
    assert got["file_error"] == want["file_error"]
    assert got["accepted"] == want["accepted"]
    assert got["rejected"] == want["rejected"]
    assert got["errors"] == want["errors"]
    assert got["warnings"] == want["warnings"]
    if want["rows"] is not None:
        assert got["rows"] == want["rows"]
