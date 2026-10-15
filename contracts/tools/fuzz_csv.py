#!/usr/bin/env python3
"""Cross-implementation differential fuzz for the two CSV importers.

The product has two independent CSV importers: the Python one the backend uses
(``backend/recruit_radar/services/csv_io.py``) and the TypeScript one local-data mode uses
(``src/engine/csv.ts``). The same file must give the same result in both modes. This tool
generates seeded, deliberately nasty CSV files, runs both importers and compares a summary of the
outcome *exactly*: file-level error code, accepted and rejected counts, the accepted rows (with
their explicit ``observed_at``), the unique ``(line, field)`` error pairs and the warning kinds.

    python contracts/tools/fuzz_csv.py --seed 1 --count 600
    python contracts/tools/fuzz_csv.py --seed 7 --count 2000 --show 5

Exit status is 0 only when every case agrees. The TypeScript leg runs through
``tests/fuzz-csv.test.ts`` (vitest), which is inert in the default test run.

The first run of this tool (before the importers were reconciled) found 426 mismatches in 1,210
cases: whitespace-only lines, trailing empty cells, spaces around quoted fields, tab/NBSP in header
names, NUL, apostrophe-led formula cells. See docs/spec/ambiguities/differential.md D-11.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
IMPORTED_AT = "2026-10-13T12:00:00Z"

KNOWN = [
    "company_name",
    "title",
    "location",
    "work_mode",
    "department",
    "url",
    "posted_at",
    "source_posting_id",
    "observed_at",
]
POOL: dict[str, list[str]] = {
    "company_name": [
        "Acme, Inc.",
        "ACME",
        "O'Brien & Sons",
        "=SUM(A1)",
        "+1 Corp",
        "-dash",
        "@home",
        "'=quoted",
        "''=twice",
        "\tTabbed",
        "  padded  ",
        "Ünïcode",
        'Foo "Bar" Ltd',
        "Cédar Point",
        "Line\nBreak Co",
        "\u00a0NBSP Co\u00a0",
        "\u0085NEL Co",
        "Zeta",
        "Beta Labs",
        "",
        "   ",
        "x" * 200,
        "x" * 201,
        "\U0001f600" * 100,
        "\U0001f600" * 101,
        "\U0001f600" * 200,
        "\U0001f600" * 201,
    ],
    "title": [
        "Engineer",
        "Senior Engineer (Remote) [US]",
        "=cmd",
        "'+1",
        "Data, Engineer",
        'He said "hi"',
        "Two\nLines",
        "  spaced  ",
        "Ingénieur",
        "データ",
        "",
        "t" * 300,
        "t" * 301,
        "\U0001f680" * 300,
        "\U0001f680" * 301,
        "Manager\r\nWindows",
    ],
    "location": [
        "Berlin",
        "New York, NY",
        "",
        "  ",
        "Remote",
        "l" * 300,
        "l" * 301,
        "\u00a0Paris",
        "\U0001f30d" * 300,
        "\U0001f30d" * 301,
    ],
    "work_mode": [
        "remote",
        "Remote",
        "REMOTE",
        "hybrid",
        "onsite",
        "on-site",
        "unknown",
        "",
        " remote ",
        "Hybrid",
        "remote\u00a0",
    ],
    "department": [
        "Eng",
        "",
        "d" * 200,
        "d" * 201,
        "\U0001f680" * 200,
        "\U0001f680" * 201,
    ],
    "url": [
        "https://x.test/a",
        "http://x.test",
        "HTTP://X.TEST",
        "HtTpS://y.test",
        "ftp://x.test",
        "javascript:alert(1)",
        "//x.test",
        "x.test",
        "https:",
        "  https://pad.test  ",
        "",
        "data:text/html,hi",
        "https://a.test/" + "p" * 5000,
    ],
    "posted_at": [
        "2026-09-01",
        "2026-9-1",
        "2026-02-30",
        "2024-02-29",
        "2026-13-01",
        "20260901",
        "2026-09-01T00:00:00Z",
        "",
        " 2026-09-01 ",
        "9999-12-31",
        "2026-00-10",
        "2026-01-00",
    ],
    "source_posting_id": ["", "123", " 12 ", "a" * 500, "id-1", "'=1", "\u00a0x"],
    "observed_at": [
        "2026-09-01T10:00:00Z",
        "2026-09-01 10:00:00",
        "2026-09-01T10:00:00+00:00",
        "2026-09-01T10:00:00z",
        "",
        "2026-02-29T00:00:00Z",
        "2026-09-01T24:00:00Z",
        " 2026-09-01T10:00:00Z ",
        "2026-09-01T10:00:00Z\u00a0",
        "2030-01-01T00:00:00Z",
        "1999-12-31T23:59:59Z",
        "2026-10-13T11:59:59Z",
    ],
}
HEADER_VARIANTS = {
    "company_name": [
        "company_name",
        "Company Name",
        "COMPANY-NAME",
        " company_name ",
        "company\u00a0name",
        "company\tname",
        "Company_Name",
        "company  name",
        "\ufeffcompany_name",
    ],
    "title": ["title", "Title", "TITLE", " title", "job title", "job_title"],
}


def _quote(value: str, mode: str) -> str:
    needs = any(c in value for c in ',"\r\n') or value != value.strip()
    if mode == "always" or (needs and mode != "never"):
        return '"' + value.replace('"', '""') + '"'
    return value


def make_case(rnd: random.Random, index: int) -> dict[str, str]:
    cols = list(KNOWN)
    rnd.shuffle(cols)
    cols = cols[: rnd.randint(3, len(cols))]
    for required in ("company_name", "title"):
        if required not in cols and rnd.random() < 0.97:
            cols.append(required)
    rnd.shuffle(cols)
    header: list[str] = []
    for col in cols:
        if col in HEADER_VARIANTS and rnd.random() < 0.35:
            header.append(rnd.choice(HEADER_VARIANTS[col]))
        elif rnd.random() < 0.15:
            header.append(col.upper().replace("_", rnd.choice(["_", " ", "-"])))
        else:
            header.append(col)
    r = rnd.random()
    if r < 0.08:
        header.append("notes")
    elif r < 0.12:
        header.append("")
    elif r < 0.15:
        header.append(header[0])
    elif r < 0.17:
        header.append("Extra Column")
    elif r < 0.18:
        header[0] = '"' + header[0] + '"x'
    qmode = rnd.choice(["auto", "auto", "auto", "always", "never"])
    eol = rnd.choice(["\n", "\r\n", "\r", "\n"])
    lines = [
        ",".join(_quote(h, qmode if rnd.random() < 0.8 else "auto") for h in header)
    ]
    simple = {
        "company_name": ["Acme", "Beta Co", "Gamma LLC", "Acme, Inc.", "Delta"],
        "title": ["Engineer", "Analyst", "Designer", "Recruiter Lead", "Data Engineer"],
        "work_mode": ["remote", "hybrid", "onsite", ""],
        "url": ["https://x.test/1", ""],
        "posted_at": ["2026-09-01", ""],
        "observed_at": ["2026-09-01T10:00:00Z", ""],
        "location": ["", "Berlin"],
    }
    for _ in range(rnd.choice([0, 1, 2, 3, 5, 8])):
        cells: list[str] = []
        for col in cols:
            if rnd.random() < 0.55:
                cells.append(rnd.choice(simple.get(col, [""])))
            else:
                cells.append(rnd.choice(POOL[col]))
        m = rnd.random()
        if m < 0.06:
            cells = cells[: max(1, len(cells) - rnd.randint(1, 2))]
        elif m < 0.12:
            cells = [*cells, rnd.choice(["", "", "extra"])]
        elif m < 0.15:
            cells = [*cells, "", ""]
        row = ",".join(
            _quote(c, qmode if rnd.random() < 0.85 else "auto") for c in cells
        )
        s = rnd.random()
        if s < 0.05:
            row = row.replace(",", ", ", 1)
        elif s < 0.08:
            row += " "
        elif s < 0.10:
            row = " " + row
        elif s < 0.12 and '"' in row:
            row = row.replace('",', '" ,', 1)
        elif s < 0.14:
            row += ","
        lines.append(row)
        t = rnd.random()
        if t < 0.06:
            lines.append("")
        elif t < 0.10:
            lines.append("   ")
        elif t < 0.12:
            lines.append("\t")
        elif t < 0.13:
            lines.append('""')
    if rnd.random() < 0.05:
        lines.insert(0, "")
    text = eol.join(lines)
    if rnd.random() < 0.5:
        text += eol
    if rnd.random() < 0.15:
        text = "\ufeff" + text
    if rnd.random() < 0.04:
        text = text.replace(eol, rnd.choice(["\n", "\r\n"]), 1)
    if rnd.random() < 0.02:
        text += '\n"unterminated,x'
    if rnd.random() < 0.02:
        text = text.replace("Acme", "Ac\x00me", 1)
    return {"id": f"c{index:05d}", "text": text}


def boundary_cases() -> list[dict[str, str]]:
    def rows(n: int, between: str = "") -> str:
        return "company_name,title\n" + "".join(
            f"Co{i},Role{i}\n{between}" for i in range(n)
        )

    head = "company_name,title\nA,B\n"
    room = 1024 * 1024 - len(head.encode())
    return [
        {"id": "b-5000", "text": rows(5000)},
        {"id": "b-5001", "text": rows(5001)},
        {"id": "b-5000-ws", "text": rows(5000, "   \n")},
        {"id": "b-5000-blank", "text": rows(5000, "\n")},
        {"id": "b-1mb-exact", "text": head + "x" * room},
        {"id": "b-1mb-plus1", "text": head + "x" * (room + 1)},
        {"id": "b-1mb-bom", "text": "\ufeff" + head + "x" * (room - 3)},
        {"id": "b-1mb-bom+1", "text": "\ufeff" + head + "x" * (room - 2)},
        {"id": "b-1mb-2byte", "text": head + "é" * (room // 2)},
        {"id": "b-1mb-2byte+1", "text": head + "é" * (room // 2 + 1)},
    ]


# --------------------------------------------------------------------------------------------
# Running both importers
# --------------------------------------------------------------------------------------------
def _warning_kind(message: str) -> str:
    if "has no header name" in message:
        return "blank_header"
    if message.startswith("Unknown column"):
        return "unknown_column"
    if message.startswith("Same posting as"):
        return "duplicate_row"
    if "is after the import time" in message:
        return "future_observed"
    return "other:" + message[:40]


def run_python(cases: list[dict[str, str]]) -> dict[str, Any]:
    backend = str(REPO / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from recruit_radar.services.csv_io import CsvFileError, parse_postings

    results: dict[str, Any] = {}
    for case in cases:
        try:
            parsed = parse_postings(
                case["text"], default_observed=IMPORTED_AT, now=IMPORTED_AT
            )
        except CsvFileError as error:
            results[case["id"]] = {
                "file_error": error.code,
                "accepted": 0,
                "rejected": 0,
                "rows": [],
                "errors": [],
                "warnings": [],
            }
            continue
        except Exception as error:  # noqa: BLE001 - record any crash as a result
            results[case["id"]] = {"thrown": f"{type(error).__name__}: {error}"[:200]}
            continue
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
        rows.sort(key=lambda cells: cells[0] or IMPORTED_AT)
        errors = sorted(
            {(e.line, e.field) for e in parsed.errors},
            key=lambda pair: (pair[0], pair[1] or ""),
        )
        results[case["id"]] = {
            "file_error": None,
            "accepted": len(parsed.rows),
            "rejected": parsed.rejected,
            "rows": rows,
            "errors": [list(pair) for pair in errors],
            "warnings": [
                list(pair)
                for pair in sorted(
                    (w.line, _warning_kind(w.message)) for w in parsed.warnings
                )
            ],
        }
    return results


def run_typescript(cases: list[dict[str, str]], workdir: Path) -> dict[str, Any]:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        raise SystemExit(
            "npx not found on PATH (Node is needed for the TypeScript leg)"
        )
    cases_file = workdir / "csv.cases.json"
    out_file = workdir / "csv.ts.json"
    cases_file.write_text(
        json.dumps({"imported_at": IMPORTED_AT, "cases": cases}, ensure_ascii=False),
        encoding="utf-8",
    )
    out_file.unlink(missing_ok=True)
    env = dict(os.environ)
    env["RR_CSV_FUZZ_FILE"] = str(cases_file)
    env["RR_CSV_FUZZ_OUT"] = str(out_file)
    env.pop("NO_COLOR", None)
    env.pop("FORCE_COLOR", None)
    proc = subprocess.run(
        [npx, "vitest", "run", "tests/fuzz-csv.test.ts"],
        check=False,
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not out_file.exists():
        sys.stderr.write(proc.stdout[-4000:] + "\n" + proc.stderr[-4000:] + "\n")
        raise SystemExit("the TypeScript leg failed (see output above)")
    loaded: dict[str, Any] = json.loads(out_file.read_text(encoding="utf-8"))["results"]
    return loaded


def signature(py: dict[str, Any], ts: dict[str, Any]) -> str:
    if "thrown" in py or "thrown" in ts:
        return f"threw py={py.get('thrown')} ts={ts.get('thrown')}"
    if py["file_error"] != ts["file_error"]:
        return f"file_error py={py['file_error']} ts={ts['file_error']}"
    parts = [
        name
        for name in ("accepted", "rejected", "rows", "errors", "warnings")
        if py[name] != ts[name]
    ]
    return "differs: " + ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--count", type=int, default=600)
    parser.add_argument(
        "--show", type=int, default=2, help="examples to print per signature"
    )
    parser.add_argument("--workdir", type=Path, default=None)
    args = parser.parse_args(argv)

    rnd = random.Random(args.seed)
    cases = [make_case(rnd, i) for i in range(args.count)] + boundary_cases()
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="rr-fuzz-csv-"))
    workdir.mkdir(parents=True, exist_ok=True)

    python_results = run_python(cases)
    ts_results = run_typescript(cases, workdir)

    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    agree = 0
    for case in cases:
        py, ts = python_results[case["id"]], ts_results[case["id"]]
        if py == ts:
            agree += 1
        else:
            groups[signature(py, ts)].append(case)

    print(
        f"seed {args.seed}: cases {len(cases)}  agree {agree}  mismatching {len(cases) - agree}"
    )
    for sig, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"\n[{len(items)}] {sig}")
        for case in items[: args.show]:
            text = case["text"]
            print(f"  {case['id']}: {text[:300]!r}")
            py, ts = python_results[case["id"]], ts_results[case["id"]]
            if "thrown" not in py and "thrown" not in ts and py["file_error"] is None:
                for name in ("rows", "errors", "warnings"):
                    if py[name] != ts[name]:
                        print(f"    {name} py: {str(py[name])[:200]}")
                        print(f"    {name} ts: {str(ts[name])[:200]}")
    return 0 if not groups else 1


if __name__ == "__main__":
    raise SystemExit(main())
