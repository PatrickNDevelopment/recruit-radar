#!/usr/bin/env python3
"""Cross-implementation differential fuzz for ``analyze()``.

Three independent artifacts implement the same pure function from the same spec:

* the oracle            ``contracts/tools/oracle.py``            (stdlib, deliberately naive)
* the Python engine     ``backend/recruit_radar/engine``
* the TypeScript engine ``src/engine`` (run through ``tests/fuzz-diff.test.ts``)

This tool generates seeded random analyze inputs, runs all three and compares the outputs
*exactly* (JSON-strict: ``true`` is not ``1``; arrays are ordered; object key order is ignored).
It is deliberately outside the default test run: nothing in pytest or vitest imports it, and the
vitest leg is skipped unless ``RR_FUZZ_FILE`` is set.

    python contracts/tools/fuzz_diff.py all --seed 1 --count 800
    python contracts/tools/fuzz_diff.py all --seed 1 --count 800 --workdir C:/tmp/fuzz
    python contracts/tools/fuzz_diff.py generate --seed 7 --count 100 --out cases.json
    python contracts/tools/fuzz_diff.py compare --cases cases.json --ts cases.json.ts.json
    python contracts/tools/fuzz_diff.py shrink --cases cases.json --id fz-000012

Exit status is 0 only when every case agrees on all three artifacts.

Case kinds
----------
``conforming``  input satisfies ``oracle.validate_input`` (the vectors' own contract).
``extended``    still valid for the engines but outside that contract: padded strings, ``""`` for
                null, omitted optional keys, unknown keys, exclude-only profiles, keywords that
                normalize to nothing, duplicate decisions, whitespace probes. The oracle receives
                the *intake-normalized* form (:func:`intake`), which is this tool's statement of
                spec 01 section 1 / D-rules in ``docs/spec/ambiguities/differential.md``.
``validity``    single, deliberate violations (see :data:`VALIDITY_CATALOGUE`); only
                accept/reject is compared between the two engines.

Unicode note: Node 24 ships Unicode 17, Python 3.14 ships Unicode 16. Code points assigned in 17
are unassigned (``Cn``) for Python, so the generator never emits a code point that Python reports
as ``Cn``; see ``docs/spec/ambiguities/differential.md``.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EPOCH0 = datetime(1970, 1, 1, tzinfo=UTC)
ATS_KINDS = ("greenhouse", "lever", "ashby")

# --------------------------------------------------------------------------------------------
# Loading the two Python artifacts
# --------------------------------------------------------------------------------------------
_ORACLE: Any = None
_ENGINE: Any = None


def oracle_module() -> Any:
    global _ORACLE
    if _ORACLE is None:
        spec = importlib.util.spec_from_file_location("rr_oracle", HERE / "oracle.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["rr_oracle"] = module
        spec.loader.exec_module(module)
        _ORACLE = module
    return _ORACLE


def engine_module() -> Any:
    global _ENGINE
    if _ENGINE is None:
        backend = str(REPO / "backend")
        if backend not in sys.path:
            sys.path.insert(0, backend)
        from recruit_radar import engine

        _ENGINE = engine
    return _ENGINE


# --------------------------------------------------------------------------------------------
# Time helpers (explicit integer arithmetic; no strftime, no local time)
# --------------------------------------------------------------------------------------------
def fmt_ts(epoch: int) -> str:
    d = EPOCH0 + timedelta(seconds=epoch)
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}T{d.hour:02d}:{d.minute:02d}:{d.second:02d}Z"


def fmt_date(epoch: int) -> str:
    return fmt_ts(epoch)[:10]


def safe_ts(epoch: int) -> str | None:
    try:
        return fmt_ts(epoch)
    except (OverflowError, ValueError):
        return None


# --------------------------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------------------------
SOURCE_POOL = [
    ("greenhouse", "acme"),
    ("greenhouse", "acme-2"),
    ("greenhouse", "acme eu"),
    ("lever", "acme"),
    ("lever", "Z\u00fcrich Board"),
    ("ashby", "acme-careers"),
    ("csv", "leads-a"),
    ("csv", "leads-b"),
    ("csv", "Q3 prospects"),
    ("manual", "manual"),
    # Code-point order versus UTF-16 code-unit order. U+10000 is the pair D800 DC00 in UTF-16,
    # so by code unit it sorts *before* U+FF21 (a single unit, FF21); by code point it sorts
    # *after*. Source refs, snapshot ids, posting ids and tokens like these make the
    # (source_kind, source_ref) processing order and every "string compare" depend on the
    # difference; an engine that compares UTF-16 units disagrees with the spec here.
    ("csv", "Ａ leads"),
    ("csv", "\U00010000 leads"),
    ("csv", "\U0001f600 leads"),
    ("lever", "￠ board"),
    ("lever", "\U00020000 board"),
]

# Groups of spellings of "the same" company, plus look-alike families that exercise the three
# merge-candidate reasons and the exotic normalization paths.
FAMILIES: list[list[str]] = [
    ["Acme", "ACME Inc.", "acme, inc", "The Acme Corporation"],
    ["Door Dash", "DoorDash", "Doordash, Inc."],
    ["Acme Robotics", "Acme Robotic", "ACME ROBOTICS LLC"],
    ["Blue Ocean Shipping", "Blue Ocean Shipping Group", "Blue-Ocean Shipping Co."],
    ["Nordic", "Nordik"],
    ["Quantum Leaf", "Quantom Leaf"],
    ["Northwind Traders", "North Wind Traders", "Northwind Trading"],
    ["\u00c9mile Works", "Emile Works", "\u00c9MILE WORKS GmbH"],
    ["\u03a9mega Works", "\u03c9mega works"],
    ["7 Seas", "Seven Seas"],
    ["Caf\u00e9 M\u00fcller", "Cafe Muller", "M\u00fcller Caf\u00e9"],
    ["\u682a\u5f0f\u4f1a\u793e\u30c6\u30b9\u30c8", "\u30c6\u30b9\u30c8"],
    ["AT&T", "AT & T", "ATT"],
    ["O'Neil & Sons", "ONeil and Sons"],
    ["\ufb01nch Group", "Finch Group Ltd"],
    ["\uff26ullwidth \uff23o", "Fullwidth Co"],
    ["\u0130stanbul Tech", "Istanbul Tech", "ISTANBUL TECH"],
    [
        "\u03a3\u03af\u03c3\u03c5\u03c6\u03bf\u03c2 SA",
        "\u03a3\u038a\u03a3\u03a5\u03a6\u039f\u03a3",
    ],
    ["Inc", "The Inc", "Co"],
    ["!!!", "???", "..."],
    ["The", "the Company"],
    ["Lumen", "Lumen Labs", "Lumen Labs Inc"],
    ["Kestrel", "Kestrel Group", "Kestrel Group LLP"],
    ["Zeta Zeta", "Zeta  Zeta", "ZETA-ZETA"],
    ["A B C D", "A B C E", "A B C", "A-B-C-D"],
    ["Alpha Beta Gamma Delta", "Alpha Beta Gamma Epsilon"],
    ["Rocket \ufe0f", "Rocket \U00020000"],
    ["\U0001f600 Smile Labs", "Smile Labs"],
    ["Na\u00efve Co", "Naive Co"],
    ["Zebra Works", "Alpha Works", "7 Works"],
    ["Cobalt", "Cobalt Systems"],
    ["Cobalt Systems", "Cobalt Systemz"],
    ["Ma\u00df GmbH", "MASS GmbH"],
    ["\u1e9eigma Co", "\u00dfigma Co"],
    # NFKC folds these onto the ASCII/Latin spelling, so they join the family of the plain name.
    [
        "\U0001d400\U0001d41c\U0001d426\U0001d41e",
        "\uff21\uff23\uff2d\uff25 Inc",
        "Acme",
    ],
    ["\u216b Labs", "XII Labs", "xii labs inc"],
    ["\u2460\u2461 Works", "12 Works", "1 2 Works"],
    ["\ufb03 Group", "ffi Group", "FFI Group Ltd"],
    ["\u212b Works", "\u00c5 Works", "A\u030a Works", "\u00e5 works"],
    ["\u212a Works", "K Works", "k works"],
    ["\U00010400\U00010401 Works", "\U00010428\U00010429 Works"],
    ["Zeta\u00b2 Co", "Zeta2 Co", "zeta 2"],
    ["\u00bd Moon", "1\u20442 Moon", "1 2 Moon"],
]
TITLE_BASES = [
    "Software Engineer",
    "Senior Software Engineer",
    "Backend Engineer",
    "Frontend Engineer",
    "Data Analyst",
    "Data Engineer",
    "Engineering Manager",
    "Product Designer",
    "Recruiter",
    "Engineer Intern",
    "Staff Engineer",
    "Sales Engineer",
    "DevOps Engineer",
    "Machine Learning Engineer",
    "Account Executive",
    "Customer Support",
    "Ing\u00e9nieur Logiciel",
    "D\u00e9veloppeur",
    "\u30bd\u30d5\u30c8\u30a6\u30a7\u30a2\u30a8\u30f3\u30b8\u30cb\u30a2",
    "C++ Developer",
    "Office Manager",
    "Engineer",
    "Designer",
    # variation selector (BMP, above the surrogates) / astral letters: token order by code point
    "Engineer ️",
    "Engineer \U00020000",
    "\U00020000 Engineer",
    "\U0001d412oftware \U0001d404ngineer",
    "Ｅngineer （Remote）",
]
TITLE_DECOR = [
    "",
    "",
    "",
    " (Remote)",
    " [US]",
    " (Remote) [EU]",
    " (Contract (6 months))",
    " - Berlin",
    ", Platform",
    " (m/f/d)",
    " [Remote]",
    "(x)",
]
LOCATIONS = [
    None,
    None,
    "New York, NY",
    "NY - New York",
    "Remote",
    "Remote, US",
    "London, UK",
    "Berlin",
    "San Francisco, CA",
    "Anywhere",
    "Z\u00fcrich",
    "ZURICH",
    "\u6771\u4eac",
    "New York",
    "Tokyo \ufe0f",
    "Tokyo \U00020000",
    "\U00020000 \ufe0f Tokyo",
    "\U0001d40d\U0001d41e\U0001d430 \U0001d418\U0001d428\U0001d42b\U0001d424",
]
DEPARTMENTS = [None, None, "Engineering", "Sales", "Design", "Data"]
WORK_MODES = ["remote", "hybrid", "onsite", "unknown", "unknown"]
INCLUDE_POOL = [
    "engineer",
    "software engineer",
    "data",
    "designer",
    "backend",
    "machine learning",
    "ing\u00e9nieur",
    "d\u00e9veloppeur",
    "developer",
    "c",
    "senior engineer",
    "engineering manager",
    "ENGINEER",
    "Software-Engineer",
]
EXCLUDE_POOL = ["intern", "manager", "staff", "junior", "contract", "Sales"]
ID_STYLES = [
    "{n}",
    "J-{n}",
    "{n:08d}",
    "id|{n}",
    "L-{n}a",
    "\u00e9{n}",
    "{n:x}-{n:x}-{n:x}",
    "UP{n}",
    "\uff21{n}",
    "\U00010000{n}",
    "\ufe0f{n}",
]

# Whitespace the two engines are known to agree on, and the code points they were known to
# disagree on before reconciliation (see the ambiguities file).
TRIM_COMMON = [
    "\u0020",
    "\t",
    "\n",
    "\r",
    "\u000b",
    "\u000c",
    "\u00a0",
    "\u1680",
    "\u2000",
    "\u2003",
    "\u200a",
    "\u2028",
    "\u2029",
    "\u202f",
    "\u205f",
    "\u3000",
]
TRIM_PROBE = ["\ufeff", "\u0085", "\u001c", "\u001d", "\u001e", "\u001f"]
# The reading adopted by the engines (docs/spec/ambiguities/differential.md, D-1): the set that
# ECMAScript String.prototype.trim removes.
ADOPTED_TRIM = set(TRIM_COMMON) | {"\ufeff"}

WILD_RANGES = [
    (0x0020, 0x024F),
    (0x0370, 0x03FF),
    (0x0400, 0x04FF),
    (0x0590, 0x06FF),
    (0x0900, 0x097F),
    (0x1E00, 0x1FFF),
    (0x2000, 0x206F),
    (0x20A0, 0x20CF),
    (0x2100, 0x218F),
    (0x2460, 0x24FF),
    (0x3000, 0x30FF),
    (0x4E00, 0x4F00),
    (0xAC00, 0xAC40),
    (0xFB00, 0xFB4F),
    (0xFE00, 0xFE0F),
    (0xFF00, 0xFFEF),
    (0x1F300, 0x1F64F),
    (0x20000, 0x20040),
    (0xE0100, 0xE0110),
]


def wild_char(rnd: random.Random) -> str:
    """A random assigned code point (never ``Cn`` for Python's Unicode, never a surrogate)."""
    for _ in range(50):
        lo, hi = rnd.choice(WILD_RANGES)
        ch = chr(rnd.randint(lo, hi))
        if unicodedata.category(ch) not in ("Cn", "Cs", "Cc"):
            return ch
    return "x"


# --------------------------------------------------------------------------------------------
# Conforming-case generator
# --------------------------------------------------------------------------------------------
AS_OF_EDGE = [
    "2024-02-29T23:59:59Z",
    "2000-03-01T00:00:00Z",
    "2100-03-01T00:00:00Z",
    "1970-01-01T00:00:00Z",
    "1969-12-31T23:59:59Z",
    "2025-12-31T23:59:59Z",
    "2026-01-01T00:00:00Z",
    "0100-03-01T00:00:00Z",
    "9990-06-01T00:00:00Z",
    "2026-10-13T00:00:00Z",
]


def typo(rnd: random.Random, text: str) -> str:
    if len(text) < 3:
        return text + "x"
    i = rnd.randrange(len(text))
    op = rnd.choice(("del", "sub", "ins"))
    if op == "del":
        return text[:i] + text[i + 1 :]
    if op == "sub":
        return text[:i] + rnd.choice("aeioustnrl") + text[i + 1 :]
    return text[:i] + rnd.choice("aeioustnrl") + text[i:]


def vary_case(rnd: random.Random, text: str) -> str:
    return rnd.choice([text, text, text.upper(), text.lower(), text.title()])


def make_entities(rnd: random.Random) -> list[list[str]]:
    entities = [list(rnd.choice(FAMILIES)) for _ in range(rnd.randint(1, 5))]
    if rnd.random() < 0.3:  # a typo twin of an existing entity
        base = rnd.choice(entities)
        entities.append([typo(rnd, base[0])])
    if rnd.random() < 0.15:  # an entity made of arbitrary assigned code points
        entities.append(
            ["".join(wild_char(rnd) for _ in range(rnd.randint(1, 6))) + " Co"]
        )
    # Names must be non-empty after trimming; families already are.
    return [[n.strip() for n in names if n.strip()] or ["Acme"] for names in entities]


def instant_pool(rnd: random.Random, as_of: int) -> list[int]:
    days = [
        0,
        0,
        1,
        2,
        3,
        7,
        8,
        13,
        14,
        15,
        20,
        28,
        29,
        30,
        30,
        31,
        32,
        40,
        44,
        45,
        46,
        59,
        60,
    ]
    days += [61, 75, 90, 120]
    out: set[int] = set()
    for d in rnd.sample(days, rnd.randint(3, 9)):
        base = as_of - d * 86400
        for delta in rnd.choice(
            [(0,), (0, -1), (0, 1), (0, 3600), (-3600, 0), (0, 12 * 3600)]
        ):
            out.add(base + delta)
    if rnd.random() < 0.3:
        out.add(as_of)
    if rnd.random() < 0.3:
        out.add(as_of + rnd.choice([1, 3600, 86400, 5 * 86400]))
    return sorted(t for t in out if safe_ts(t) is not None)


LOCATION_VARIANTS = {
    "New York, NY": "NY - New York",
    "NY - New York": "new york ny",
    "Remote, US": "US (Remote)",
    "Zürich": "ZURICH",
    "Berlin": "BERLIN",
}


def make_role(
    rnd: random.Random,
    kind: str,
    entities: list[list[str]],
    used: set[str],
    openings: list[dict],
) -> dict:
    """A role of one source. Half the time it re-reports an opening that another source (or
    this one, as a second headcount) already has, so cross-source matching is exercised."""
    pid: str | None = None
    if openings and rnd.random() < 0.55:
        base = rnd.choice(openings)
        entity = base["entity"]
        location = base["location"]
        if location in LOCATION_VARIANTS and rnd.random() < 0.5:
            location = LOCATION_VARIANTS[location]
        role = {
            "entity": entity,
            "name": rnd.choice(entities[entity]),
            "title": vary_case(rnd, base["title"]).strip(),
            "location": location,
            "work_mode": base["work_mode"],
            "department": base["department"],
            "url": None,
            "posted_at": base["posted_at"],
            "serial": rnd.randint(1000, 9999),
        }
    else:
        entity = rnd.randrange(len(entities))
        title = rnd.choice(TITLE_BASES) + rnd.choice(TITLE_DECOR)
        role = {
            "entity": entity,
            "name": rnd.choice(entities[entity]),
            "title": vary_case(rnd, title).strip(),
            "location": rnd.choice(LOCATIONS),
            "work_mode": rnd.choice(WORK_MODES),
            "department": rnd.choice(DEPARTMENTS),
            "url": None,
            "posted_at": None,
            "serial": rnd.randint(1000, 9999),
        }
        if rnd.random() < 0.6:
            openings.append(role)
    if kind in ATS_KINDS or rnd.random() > 0.45:
        for _ in range(20):
            style = rnd.choice(ID_STYLES)
            candidate = style.format(n=rnd.randint(1, 400))
            if candidate not in used:
                pid = candidate
                used.add(candidate)
                break
    role["pid"] = pid
    return role


def roll_dates(rnd: random.Random, role: dict, as_of: int) -> None:
    if rnd.random() < 0.45:
        role["posted_at"] = None
        return
    offset = rnd.choice([0, 1, 5, 13, 14, 29, 30, 31, 44, 45, 46, 60, 100, 150, -1, -3])
    stamp = safe_ts(as_of - offset * 86400)
    role["posted_at"] = stamp[:10] if stamp else None


def roll_url(rnd: random.Random, role: dict, kind: str, ref: str) -> None:
    if rnd.random() < 0.35:
        role["url"] = None
    else:
        scheme = rnd.choice(["https", "https", "http"])
        slug = re.sub(r"[^a-z0-9]+", "-", ref.lower()).strip("-") or "x"
        role["url"] = f"{scheme}://jobs.example.com/{slug}/{role['serial']}"


def mutate_role(
    rnd: random.Random,
    role: dict,
    entities: list[list[str]],
    as_of: int,
    kind: str,
    ref: str,
) -> None:
    if rnd.random() < 0.2:
        role["title"] = vary_case(
            rnd, rnd.choice(TITLE_BASES) + rnd.choice(TITLE_DECOR)
        ).strip()
    if rnd.random() < 0.1:
        role["location"] = rnd.choice(LOCATIONS)
    if rnd.random() < 0.08:
        role["work_mode"] = rnd.choice(WORK_MODES)
    if rnd.random() < 0.08:
        role["department"] = rnd.choice(DEPARTMENTS)
    if rnd.random() < 0.1:
        roll_url(rnd, role, kind, ref)
    if rnd.random() < 0.07:
        roll_dates(rnd, role, as_of)
    if rnd.random() < 0.1:
        role["name"] = rnd.choice(entities[role["entity"]])
    if (
        rnd.random() < 0.02
    ):  # the role moves to another company under the same posting id
        role["entity"] = rnd.randrange(len(entities))
        role["name"] = rnd.choice(entities[role["entity"]])


def posting_of(role: dict, kind: str, ref: str) -> dict:
    return {
        "source_kind": kind,
        "source_ref": ref,
        "source_posting_id": role["pid"],
        "company_name": role["name"],
        "title": role["title"],
        "location": role["location"],
        "work_mode": role["work_mode"],
        "department": role["department"],
        "url": role["url"],
        "posted_at": role["posted_at"],
    }


SNAPSHOT_ID_PREFIXES = [
    "s",
    "S",
    "snap-",
    "\u00e9",
    "z",
    "0",
    "10-",
    "\uff21",  # BMP above the surrogates: sorts after U+10000 by UTF-16 code unit only
    "\U00010000",
    "\U0001f600",
]


def gen_snapshots(
    rnd: random.Random,
    as_of: int,
    entities: list[list[str]],
    heavy: bool = False,
) -> list[dict[str, Any]]:
    """Snapshots of 1..4 sources. ``heavy`` gives a few companies many roles each (so scope
    sizes cross the ``volume`` table's cap of 10 and corroboration is common)."""
    pool = instant_pool(rnd, as_of)
    sources = rnd.sample(SOURCE_POOL, rnd.randint(1, 4))
    snaps: list[dict[str, Any]] = []
    prefix = rnd.choice(SNAPSHOT_ID_PREFIXES)
    openings: list[dict] = []
    counter = 0
    total = 0
    for kind, ref in sources:
        used: set[str] = set()
        world: list[dict] = []
        n_snaps = rnd.randint(1, 5)
        instants = sorted(rnd.choices(pool, k=n_snaps)) if pool else []
        for position, instant in enumerate(instants):
            observed = safe_ts(instant)
            if observed is None:
                continue
            if position == 0 or rnd.random() < 0.5:
                for _ in range(rnd.randint(8, 22) if heavy else rnd.randint(1, 4)):
                    role = make_role(rnd, kind, entities, used, openings)
                    roll_dates(rnd, role, as_of)
                    roll_url(rnd, role, kind, ref)
                    world.append(role)
            else:
                for role in world:
                    mutate_role(rnd, role, entities, as_of, kind, ref)
            mode = (
                "full"
                if kind in ATS_KINDS
                else rnd.choice(["full", "additive", "additive"])
            )
            keep = 0.8 if mode == "full" else 0.5
            listed = [r for r in world if position == 0 or rnd.random() < keep]
            postings = [posting_of(r, kind, ref) for r in listed]
            if (
                postings and rnd.random() < 0.15
            ):  # duplicate key in one snapshot: last wins
                dup = dict(rnd.choice(postings))
                if rnd.random() < 0.5:
                    dup["title"] = dup["title"] + " II"
                postings.append(dup)
            rnd.shuffle(postings)
            counter += 1
            total += len(postings)
            snaps.append(
                {
                    "snapshot_id": f"{prefix}{counter}",
                    "source_kind": kind,
                    "source_ref": ref,
                    "observed_at": observed,
                    "mode": mode,
                    "postings": postings,
                }
            )
        if total > (400 if heavy else 90):
            break
    rnd.shuffle(snaps)
    return snaps


def company_keys(snaps: list[dict]) -> list[str]:
    oracle = oracle_module()
    return sorted(
        {oracle.company_key(p["company_name"]) for s in snaps for p in s["postings"]}
    )


def gen_decisions(rnd: random.Random, snaps: list[dict]) -> list[dict[str, str]]:
    oracle = oracle_module()
    present = company_keys(snaps)
    decisions: list[dict[str, str]] = []

    def add(a: str, b: str, kind: str) -> None:
        if a == b:
            return
        lo, hi = sorted((a, b))
        decisions.append({"a_key": lo, "b_key": hi, "decision": kind})

    if len(present) >= 2 and rnd.random() < 0.55:
        for _ in range(rnd.randint(1, 3)):
            a, b = rnd.sample(present, 2)
            add(a, b, rnd.choice(["merge", "not_same"]))
    # not_same naming a non-canonical member of a merged group
    candidates = [
        (a, b)
        for i, a in enumerate(present)
        for b in present[i + 1 :]
        if oracle.candidate_reason(a, b) is not None
    ]
    if candidates and len(present) >= 3 and rnd.random() < 0.25:
        x, z = rnd.choice(candidates)
        others = [k for k in present if k not in (x, z)]
        y = rnd.choice(others)
        add(z, y, "merge")
        add(x, y, "not_same")
    if len(present) >= 2 and rnd.random() < 0.1:  # a merge through a key no posting has
        ghost = rnd.choice(["0 ghost", "aaa", "zzz ghost", "ac"])
        add(ghost, rnd.choice(present), "merge")
    if rnd.random() < 0.08:  # stale not_same between absent keys
        add("ghost one", "ghost two", "not_same")
    return decisions


def gen_conforming(rnd: random.Random) -> dict[str, Any]:
    oracle = oracle_module()
    as_of_text = (
        rnd.choice(AS_OF_EDGE)
        if rnd.random() < 0.15
        else fmt_ts(
            oracle.epoch("2026-10-13T12:00:00Z")
            + rnd.choice([0, 0, 0, 1, 3600, -86400])
        )
    )
    as_of = oracle.epoch(as_of_text)
    entities = make_entities(rnd)
    heavy = rnd.random() < 0.12
    if heavy:
        entities = entities[: rnd.randint(1, 2)]
    snaps = gen_snapshots(rnd, as_of, entities, heavy)
    include = rnd.sample(INCLUDE_POOL, rnd.choice([0, 0, 1, 1, 2, 3]))
    exclude = rnd.sample(EXCLUDE_POOL, rnd.choice([0, 1, 2])) if include else []
    return {
        "as_of": as_of_text,
        "profile": {"include_keywords": include, "exclude_keywords": exclude},
        "decisions": gen_decisions(rnd, snaps),
        "snapshots": snaps,
    }


# --------------------------------------------------------------------------------------------
# Extended cases: valid for the engines, outside the oracle's input contract
# --------------------------------------------------------------------------------------------
OPTIONAL_TEXT = ("source_posting_id", "location", "department", "url", "posted_at")


def trim_with(text: str, trim_set: set[str]) -> str:
    start, end = 0, len(text)
    while start < end and text[start] in trim_set:
        start += 1
    while end > start and text[end - 1] in trim_set:
        end -= 1
    return text[start:end]


def intake(raw: dict[str, Any], trim_set: set[str] = ADOPTED_TRIM) -> dict[str, Any]:
    """Spec 01 section 1 applied to a raw input: the form the oracle can be given.

    Strings are trimmed, ``""`` of an optional field is null, ``work_mode`` defaults to
    ``unknown``, posting-level source fields are filled from the snapshot, unknown keys are
    dropped, absent collections become empty.
    """
    out: dict[str, Any] = {
        "as_of": raw["as_of"],
        "profile": {
            "include_keywords": [
                trim_with(k, trim_set)
                for k in raw.get("profile", {}).get("include_keywords", [])
            ],
            "exclude_keywords": [
                trim_with(k, trim_set)
                for k in raw.get("profile", {}).get("exclude_keywords", [])
            ],
        },
        "decisions": [
            {"a_key": d["a_key"], "b_key": d["b_key"], "decision": d["decision"]}
            for d in raw.get("decisions", [])
        ],
        "snapshots": [],
    }
    for snap in raw.get("snapshots", []):
        ref = trim_with(snap["source_ref"], trim_set)
        postings = []
        for posting in snap.get("postings", []):
            item: dict[str, Any] = {
                "source_kind": snap["source_kind"],
                "source_ref": ref,
                "company_name": trim_with(posting["company_name"], trim_set),
                "title": trim_with(posting["title"], trim_set),
            }
            for name in OPTIONAL_TEXT:
                value = posting.get(name)
                item[name] = (
                    (trim_with(value, trim_set) or None)
                    if isinstance(value, str)
                    else None
                )
            mode = posting.get("work_mode")
            mode = trim_with(mode, trim_set) if isinstance(mode, str) else None
            item["work_mode"] = mode or "unknown"
            postings.append(item)
        out["snapshots"].append(
            {
                "snapshot_id": snap["snapshot_id"],
                "source_kind": snap["source_kind"],
                "source_ref": ref,
                "observed_at": snap["observed_at"],
                "mode": snap["mode"],
                "postings": postings,
            }
        )
    return out


LENGTH_LIMITS = {
    "source_ref": (1, 200),
    "company_name": (1, 200),
    "title": (1, 300),
    "location": (0, 300),
    "department": (0, 200),
}


def limit_problems(oracle_input: dict[str, Any]) -> list[str]:
    """Length violations in an intake-normalized input (a generator bug, never a finding).

    ``extended`` cases are *meant* to be valid; the oracle does not validate lengths itself, so
    an accidentally overlong field would otherwise show up as an engine-versus-oracle mismatch.
    """
    problems: list[str] = []
    for s_index, snap in enumerate(oracle_input["snapshots"]):
        fields: list[tuple[str, str | None]] = [("source_ref", snap["source_ref"])]
        for posting in snap["postings"]:
            fields += [
                (name, posting.get(name))
                for name in LENGTH_LIMITS
                if name != "source_ref"
            ]
        for name, value in fields:
            low, high = LENGTH_LIMITS[name]
            length = len(value) if isinstance(value, str) else 0
            if not low <= length <= high:
                problems.append(f"snapshots[{s_index}].{name} has {length} code points")
    return problems


def pad(rnd: random.Random, text: str, pool: list[str]) -> str:
    return (
        "".join(rnd.choices(pool, k=rnd.randint(0, 2)))
        + text
        + "".join(rnd.choices(pool, k=rnd.randint(0, 2)))
    )


def extend_case(
    rnd: random.Random, base: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Return ``(raw_input, applied_mutator_names)``; ``base`` is not modified."""
    raw = copy.deepcopy(base)
    applied: list[str] = []
    mutators = [
        "pad",
        "null_to_empty",
        "omit_optional",
        "drop_posting_source",
        "extra_keys",
        "drop_defaults",
        "dup_decisions",
        "exclude_only",
        "empty_keyword",
        "ws_probe",
        "null_ats_id",
        "work_mode_blank",
        "url_variants",
        "long_text",
    ]
    chosen = rnd.sample(mutators, rnd.randint(1, 4))
    # Ordering constraints, applied with a stable sort:
    # * long_text replaces whole fields at the length limit, so it must run after pad/ws_probe
    #   (which would otherwise push a 300-code-point title over the limit by adding characters
    #   that are *not* trimmed, e.g. U+0085);
    # * drop_defaults removes keys the other mutators read, so it always runs last.
    chosen.sort(key=lambda m: {"long_text": 1, "drop_defaults": 2}.get(m, 0))
    for name in chosen:
        applied.append(name)
        postings = [p for s in raw["snapshots"] for p in s["postings"]]
        if name == "pad":
            for p in postings:
                for f in (
                    "company_name",
                    "title",
                    "location",
                    "department",
                    "url",
                    "posted_at",
                ):
                    if isinstance(p.get(f), str) and rnd.random() < 0.5:
                        p[f] = pad(rnd, p[f], TRIM_COMMON)
                if isinstance(p.get("source_posting_id"), str) and rnd.random() < 0.3:
                    p["source_posting_id"] = pad(
                        rnd, p["source_posting_id"], TRIM_COMMON
                    )
            for s in raw["snapshots"]:
                if rnd.random() < 0.3:
                    s["source_ref"] = pad(rnd, s["source_ref"], TRIM_COMMON)
            for key in ("include_keywords", "exclude_keywords"):
                raw["profile"][key] = [
                    pad(rnd, k, TRIM_COMMON) if rnd.random() < 0.4 else k
                    for k in raw["profile"][key]
                ]
        elif name == "null_to_empty":
            for p in postings:
                for f in OPTIONAL_TEXT + ("work_mode",):
                    if p.get(f) is None and rnd.random() < 0.6:
                        p[f] = rnd.choice(["", " ", "\t"])
        elif name == "omit_optional":
            for p in postings:
                for f in OPTIONAL_TEXT:
                    if p.get(f) is None and rnd.random() < 0.7:
                        p.pop(f, None)
                if p.get("work_mode") == "unknown" and rnd.random() < 0.5:
                    p.pop("work_mode", None)
        elif name == "drop_posting_source":
            for p in postings:
                if rnd.random() < 0.7:
                    p.pop("source_kind", None)
                    p.pop("source_ref", None)
        elif name == "extra_keys":
            raw["note"] = "ignored"
            raw["profile"]["updated_at"] = "2026-01-01"
            for s in raw["snapshots"]:
                if rnd.random() < 0.5:
                    s["label"] = "ignored"
            for p in postings:
                if rnd.random() < 0.2:
                    p["description"] = "ignored"
            for d in raw["decisions"]:
                if rnd.random() < 0.5:
                    d["note"] = "ignored"
        elif name == "drop_defaults":
            if (
                not raw["profile"]["include_keywords"]
                and not raw["profile"]["exclude_keywords"]
            ):
                raw.pop("profile", None)
            if not raw["decisions"]:
                raw.pop("decisions", None)
            for s in raw["snapshots"]:
                if not s["postings"]:
                    s.pop("postings", None)
            if not raw["snapshots"]:
                raw.pop("snapshots", None)
        elif name == "dup_decisions":
            raw["decisions"] = raw["decisions"] + [
                dict(d) for d in raw["decisions"] if rnd.random() < 0.7
            ]
            if raw["decisions"] and rnd.random() < 0.5:
                d = dict(rnd.choice(raw["decisions"]))
                d["decision"] = "not_same" if d["decision"] == "merge" else "merge"
                raw["decisions"].append(d)
        elif name == "exclude_only":
            if raw["profile"]["exclude_keywords"] or rnd.random() < 0.5:
                raw["profile"]["include_keywords"] = []
                if not raw["profile"]["exclude_keywords"]:
                    raw["profile"]["exclude_keywords"] = rnd.sample(EXCLUDE_POOL, 1)
        elif name == "empty_keyword":
            target = rnd.choice(["include_keywords", "exclude_keywords"])
            raw["profile"][target] = raw["profile"][target] + [
                rnd.choice(["!!!", "  ", "...", "()"])
            ]
        elif name == "ws_probe":
            for p in postings:
                for f in ("company_name", "title", "location", "department"):
                    if isinstance(p.get(f), str) and rnd.random() < 0.35:
                        p[f] = (
                            rnd.choice(TRIM_PROBE)
                            + p[f]
                            + rnd.choice(TRIM_PROBE + [""])
                        )
        elif name == "null_ats_id":
            for s in raw["snapshots"]:
                if s["source_kind"] in ATS_KINDS:
                    for p in s["postings"]:
                        if rnd.random() < 0.3:
                            p["source_posting_id"] = None
        elif name == "work_mode_blank":
            for p in postings:
                if rnd.random() < 0.3:
                    p["work_mode"] = rnd.choice([None, "", "  "])
        elif name == "url_variants":
            for p in postings:
                url = p.get("url")
                # (an earlier null_to_empty may have left " " or "\t" here)
                if isinstance(url, str) and ":" in url and rnd.random() < 0.5:
                    scheme = rnd.choice(["HTTPS", "Http", "https"])
                    p["url"] = scheme + ":" + url.split(":", 1)[1]
        elif name == "long_text":
            for p in postings:
                if rnd.random() < 0.1:
                    p["title"] = ("\U0001f600" * rnd.choice([150, 300])).strip()
                if rnd.random() < 0.05:
                    p["company_name"] = "N" * rnd.choice([199, 200])
    return raw, applied


# --------------------------------------------------------------------------------------------
# Validity catalogue: one deliberate fault each; only accept/reject is compared
# --------------------------------------------------------------------------------------------
def _base_valid() -> dict[str, Any]:
    return {
        "as_of": "2026-10-13T12:00:00Z",
        "profile": {"include_keywords": ["engineer"], "exclude_keywords": []},
        "decisions": [],
        "snapshots": [
            {
                "snapshot_id": "s1",
                "source_kind": "greenhouse",
                "source_ref": "acme",
                "observed_at": "2026-09-01T08:00:00Z",
                "mode": "full",
                "postings": [
                    {
                        "source_posting_id": "1",
                        "company_name": "Acme",
                        "title": "Engineer",
                        "location": "Berlin",
                        "work_mode": "remote",
                        "department": "Eng",
                        "url": "https://example.com/1",
                        "posted_at": "2026-08-30",
                    }
                ],
            }
        ],
    }


def _mut(path: str, value: Any) -> Any:
    """Build a mutator that sets a dotted path (``snapshots.0.postings.0.title``)."""

    def apply(doc: dict[str, Any]) -> None:
        node: Any = doc
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[int(part)] if part.isdigit() else node[part]
        last = parts[-1]
        if value is _DELETE:
            if isinstance(node, dict):
                node.pop(last, None)
        elif last.isdigit():
            node[int(last)] = value
        else:
            node[last] = value

    return apply


_DELETE = object()
P = "snapshots.0.postings.0."
S = "snapshots.0."
# (name, mutator, spec_expectation) where expectation is "accept", "reject" or "open" (spec silent)
VALIDITY_CATALOGUE: list[tuple[str, Any, str]] = [
    ("baseline", lambda d: None, "accept"),
    ("as_of missing", _mut("as_of", _DELETE), "reject"),
    ("as_of padded", _mut("as_of", " 2026-10-13T12:00:00Z "), "reject"),
    ("as_of date only", _mut("as_of", "2026-10-13"), "reject"),
    ("as_of no Z", _mut("as_of", "2026-10-13T12:00:00"), "reject"),
    ("as_of offset", _mut("as_of", "2026-10-13T12:00:00+00:00"), "reject"),
    ("as_of fractional", _mut("as_of", "2026-10-13T12:00:00.000Z"), "reject"),
    ("as_of lowercase", _mut("as_of", "2026-10-13t12:00:00z"), "reject"),
    ("as_of hour 24", _mut("as_of", "2026-10-13T24:00:00Z"), "reject"),
    ("as_of second 60", _mut("as_of", "2026-10-13T12:00:60Z"), "reject"),
    ("as_of feb 30", _mut("as_of", "2026-02-30T12:00:00Z"), "reject"),
    ("as_of year 0000", _mut("as_of", "0000-01-01T00:00:00Z"), "reject"),
    ("as_of leap day ok", _mut("as_of", "2024-02-29T00:00:00Z"), "accept"),
    ("as_of non-leap feb 29", _mut("as_of", "2026-02-29T00:00:00Z"), "reject"),
    ("as_of number", _mut("as_of", 1760000000), "reject"),
    ("as_of null", _mut("as_of", None), "reject"),
    ("profile missing", _mut("profile", _DELETE), "accept"),
    ("profile null", _mut("profile", None), "reject"),
    ("profile empty object", _mut("profile", {}), "accept"),
    ("decisions missing", _mut("decisions", _DELETE), "accept"),
    ("decisions null", _mut("decisions", None), "reject"),
    ("snapshots missing", _mut("snapshots", _DELETE), "accept"),  # D-7
    ("snapshots null", _mut("snapshots", None), "reject"),
    ("snapshots empty", _mut("snapshots", []), "accept"),
    ("postings missing", _mut(S + "postings", _DELETE), "accept"),  # D-7
    ("postings null", _mut(S + "postings", None), "reject"),
    ("postings empty", _mut(S + "postings", []), "accept"),
    ("unknown top-level key", _mut("surprise", 1), "accept"),  # D-5
    ("unknown profile key", _mut("profile.surprise", 1), "accept"),  # D-5
    ("unknown snapshot key", _mut(S + "surprise", 1), "accept"),  # D-5
    ("unknown posting key", _mut(P + "surprise", 1), "accept"),  # D-5
    ("snapshot_id empty", _mut(S + "snapshot_id", ""), "reject"),
    ("snapshot_id missing", _mut(S + "snapshot_id", _DELETE), "reject"),
    ("snapshot_id number", _mut(S + "snapshot_id", 7), "reject"),
    ("source_kind unknown", _mut(S + "source_kind", "workday"), "reject"),
    ("source_kind uppercase", _mut(S + "source_kind", "Greenhouse"), "reject"),
    ("source_ref empty", _mut(S + "source_ref", ""), "reject"),
    ("source_ref blank", _mut(S + "source_ref", "   "), "reject"),
    ("source_ref padded", _mut(S + "source_ref", "  acme  "), "accept"),
    ("source_ref 200 cp", _mut(S + "source_ref", "r" * 200), "accept"),
    ("source_ref 201 cp", _mut(S + "source_ref", "r" * 201), "reject"),
    ("source_ref 200 astral", _mut(S + "source_ref", "\U0001f600" * 200), "accept"),
    ("source_ref 201 astral", _mut(S + "source_ref", "\U0001f600" * 201), "reject"),
    ("observed_at padded", _mut(S + "observed_at", " 2026-09-01T08:00:00Z"), "reject"),
    ("observed_at bad", _mut(S + "observed_at", "yesterday"), "reject"),
    ("mode unknown", _mut(S + "mode", "partial"), "reject"),
    ("mode uppercase", _mut(S + "mode", "FULL"), "reject"),
    ("mode missing", _mut(S + "mode", _DELETE), "reject"),
    ("posting source_kind same", _mut(P + "source_kind", "greenhouse"), "accept"),
    ("posting source_kind differs", _mut(P + "source_kind", "lever"), "reject"),
    ("posting source_kind null", _mut(P + "source_kind", None), "accept"),
    ("posting source_ref same", _mut(P + "source_ref", "acme"), "accept"),
    ("posting source_ref padded same", _mut(P + "source_ref", " acme "), "accept"),
    ("posting source_ref differs", _mut(P + "source_ref", "other"), "reject"),
    ("posting source_ref empty", _mut(P + "source_ref", ""), "reject"),  # D-10
    ("posting source_ref blank", _mut(P + "source_ref", "  "), "reject"),  # D-10
    ("posting source_ref null", _mut(P + "source_ref", None), "accept"),
    ("posting id null", _mut(P + "source_posting_id", None), "accept"),
    ("posting id empty", _mut(P + "source_posting_id", ""), "accept"),
    ("posting id number", _mut(P + "source_posting_id", 12), "reject"),
    ("posting id padded", _mut(P + "source_posting_id", " 12 "), "accept"),
    ("company_name missing", _mut(P + "company_name", _DELETE), "reject"),
    ("company_name empty", _mut(P + "company_name", ""), "reject"),
    ("company_name blank", _mut(P + "company_name", " \t "), "reject"),
    ("company_name null", _mut(P + "company_name", None), "reject"),
    ("company_name number", _mut(P + "company_name", 5), "reject"),
    ("company_name 200", _mut(P + "company_name", "n" * 200), "accept"),
    ("company_name 201", _mut(P + "company_name", "n" * 201), "reject"),
    ("company_name 200 astral", _mut(P + "company_name", "\U0001f600" * 200), "accept"),
    ("company_name 201 astral", _mut(P + "company_name", "\U0001f600" * 201), "reject"),
    ("company_name only punctuation", _mut(P + "company_name", "!!!"), "accept"),
    ("title missing", _mut(P + "title", _DELETE), "reject"),
    ("title blank", _mut(P + "title", "  "), "reject"),
    ("title 300", _mut(P + "title", "t" * 300), "accept"),
    ("title 301", _mut(P + "title", "t" * 301), "reject"),
    ("title 300 astral", _mut(P + "title", "\U0001f600" * 300), "accept"),
    ("title 301 astral", _mut(P + "title", "\U0001f600" * 301), "reject"),
    ("title 300 after trim", _mut(P + "title", " " + "t" * 300 + " "), "accept"),
    ("location null", _mut(P + "location", None), "accept"),
    ("location empty", _mut(P + "location", ""), "accept"),
    ("location 300", _mut(P + "location", "l" * 300), "accept"),
    ("location 301", _mut(P + "location", "l" * 301), "reject"),
    ("location number", _mut(P + "location", 3), "reject"),
    ("department 200", _mut(P + "department", "d" * 200), "accept"),
    ("department 201", _mut(P + "department", "d" * 201), "reject"),
    ("work_mode missing", _mut(P + "work_mode", _DELETE), "accept"),
    ("work_mode null", _mut(P + "work_mode", None), "accept"),
    ("work_mode empty", _mut(P + "work_mode", ""), "accept"),
    ("work_mode padded", _mut(P + "work_mode", " remote "), "accept"),
    ("work_mode uppercase", _mut(P + "work_mode", "Remote"), "reject"),
    ("work_mode other", _mut(P + "work_mode", "telework"), "reject"),
    ("work_mode number", _mut(P + "work_mode", 1), "reject"),
    ("url ftp", _mut(P + "url", "ftp://example.com/x"), "reject"),
    ("url javascript", _mut(P + "url", "javascript:alert(1)"), "reject"),
    ("url data", _mut(P + "url", "data:text/html,hi"), "reject"),
    ("url relative", _mut(P + "url", "/jobs/1"), "reject"),
    ("url scheme-less", _mut(P + "url", "example.com/jobs"), "reject"),
    ("url mailto", _mut(P + "url", "mailto:a@b.c"), "reject"),
    ("url http upper", _mut(P + "url", "HTTP://EXAMPLE.COM/X"), "accept"),
    # D-8: only the scheme is constrained.
    ("url https scheme only", _mut(P + "url", "https:"), "accept"),
    ("url https no host", _mut(P + "url", "https://"), "accept"),
    ("url http no slashes", _mut(P + "url", "http:example.com"), "accept"),
    ("url with space", _mut(P + "url", "https://exa mple.com/a b"), "accept"),
    ("url control char", _mut(P + "url", "https://example.com/\u0001"), "accept"),
    ("url tab-smuggled scheme", _mut(P + "url", "ht\ttps://example.com"), "reject"),
    (
        "url leading control char",
        _mut(P + "url", "\u0001https://example.com"),
        "reject",
    ),
    ("url long s scheme", _mut(P + "url", "http\u017f://example.com"), "reject"),
    ("url fullwidth colon", _mut(P + "url", "https\uff1a//example.com"), "reject"),
    ("url empty", _mut(P + "url", ""), "accept"),
    ("url padded", _mut(P + "url", "  https://example.com/x "), "accept"),
    ("posted_at feb 30", _mut(P + "posted_at", "2026-02-30"), "reject"),
    ("posted_at short month", _mut(P + "posted_at", "2026-1-5"), "reject"),
    ("posted_at timestamp", _mut(P + "posted_at", "2026-01-05T00:00:00Z"), "reject"),
    ("posted_at year 0000", _mut(P + "posted_at", "0000-01-01"), "reject"),
    ("posted_at year 0001", _mut(P + "posted_at", "0001-01-01"), "accept"),
    ("posted_at leap day", _mut(P + "posted_at", "2024-02-29"), "accept"),
    ("posted_at non-leap", _mut(P + "posted_at", "2026-02-29"), "reject"),
    ("posted_at century non-leap", _mut(P + "posted_at", "2100-02-29"), "reject"),
    ("posted_at 2000 leap", _mut(P + "posted_at", "2000-02-29"), "accept"),
    (
        "posted_at arabic digits",
        _mut(P + "posted_at", "\u0662\u0660\u0662\u0666-01-05"),
        "reject",
    ),
    ("posted_at padded", _mut(P + "posted_at", " 2026-01-05 "), "accept"),
    ("posted_at empty", _mut(P + "posted_at", ""), "accept"),
    ("posted_at number", _mut(P + "posted_at", 20260105), "reject"),
    ("posted_at in the future", _mut(P + "posted_at", "2027-01-01"), "accept"),
    (
        "decision a==b",
        _mut("decisions", [{"a_key": "x", "b_key": "x", "decision": "merge"}]),
        "reject",
    ),
    (
        "decision a>b",
        _mut("decisions", [{"a_key": "y", "b_key": "x", "decision": "merge"}]),
        "reject",
    ),
    (
        "decision a<b",
        _mut("decisions", [{"a_key": "x", "b_key": "y", "decision": "merge"}]),
        "accept",
    ),
    (
        "decision unknown kind",
        _mut("decisions", [{"a_key": "x", "b_key": "y", "decision": "join"}]),
        "reject",
    ),
    (
        "decision missing key",
        _mut("decisions", [{"a_key": "x", "decision": "merge"}]),
        "reject",
    ),
    (
        "decision key number",
        _mut("decisions", [{"a_key": 1, "b_key": "y", "decision": "merge"}]),
        "reject",
    ),
    (
        "decision empty a_key",
        _mut("decisions", [{"a_key": "", "b_key": "y", "decision": "merge"}]),
        "accept",
    ),
    (
        "decision astral order",
        _mut(
            "decisions",
            [{"a_key": "\ufb00", "b_key": "\U00010000", "decision": "merge"}],
        ),
        "accept",
    ),
    (
        "decision astral order bad",
        _mut(
            "decisions",
            [{"a_key": "\U00010000", "b_key": "\ufb00", "decision": "merge"}],
        ),
        "reject",
    ),
    ("keywords number", _mut("profile.include_keywords", [1]), "reject"),
    ("keywords not list", _mut("profile.include_keywords", "engineer"), "reject"),
    # D-9: the profile limits of spec 03 hold at the engine boundary too.
    (
        "keywords 50",
        _mut("profile.include_keywords", [f"k{i}" for i in range(50)]),
        "accept",
    ),
    (
        "keywords 51",
        _mut("profile.include_keywords", [f"k{i}" for i in range(51)]),
        "reject",
    ),
    (
        "exclude keywords 51",
        _mut("profile.exclude_keywords", [f"k{i}" for i in range(51)]),
        "reject",
    ),
    ("keyword 60", _mut("profile.include_keywords", ["k" * 60]), "accept"),
    ("keyword 61", _mut("profile.include_keywords", ["k" * 61]), "reject"),
    (
        "keyword 60 astral",
        _mut("profile.include_keywords", ["\U0001f600" * 60]),
        "accept",
    ),
    (
        "keyword 61 astral",
        _mut("profile.include_keywords", ["\U0001f600" * 61]),
        "reject",
    ),
    (
        "keyword 60 after trim",
        _mut("profile.include_keywords", [" " + "k" * 60 + " "]),
        "accept",
    ),
    ("keyword empty", _mut("profile.include_keywords", [""]), "accept"),
    (
        "exclude only",
        _mut("profile", {"include_keywords": [], "exclude_keywords": ["intern"]}),
        "accept",
    ),
    (
        "duplicate snapshot_id",
        lambda d: d["snapshots"].append(copy.deepcopy(d["snapshots"][0])),
        "reject",
    ),
    (
        "future snapshot invalid posting",
        lambda d: d["snapshots"].append(
            {
                **copy.deepcopy(d["snapshots"][0]),
                "snapshot_id": "s2",
                "observed_at": "2027-01-01T00:00:00Z",
                "postings": [{"company_name": "", "title": "x"}],
            }
        ),
        "reject",
    ),
    ("input is a list", None, "reject"),
]


def validity_inputs() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for index, (name, mutator, expectation) in enumerate(VALIDITY_CATALOGUE):
        if mutator is None:
            doc: Any = []
        else:
            doc = _base_valid()
            mutator(doc)
        cases.append(
            {
                "id": f"vd-{index:03d}",
                "kind": "validity",
                "label": name,
                "expectation": expectation,
                "input": doc,
            }
        )
    return cases


# --------------------------------------------------------------------------------------------
# Case-set generation
# --------------------------------------------------------------------------------------------
def generate(seed: int, count: int, validity: bool = True) -> list[dict[str, Any]]:
    rnd = random.Random(seed)
    oracle = oracle_module()
    cases: list[dict[str, Any]] = []
    for index in range(count):
        base = gen_conforming(random.Random(rnd.getrandbits(64)))
        problems = oracle.validate_input(base)
        if problems:  # a generator bug, never silently dropped
            raise SystemExit(
                f"generator produced a non-conforming input #{index}: {problems[:3]}"
            )
        case: dict[str, Any] = {
            "id": f"fz-{index:06d}",
            "kind": "conforming",
            "input": base,
        }
        if index % 10 >= 7:  # 30 % extended
            sub = random.Random(rnd.getrandbits(64))
            raw, applied = extend_case(sub, base)
            oracle_input = intake(raw)
            problems = limit_problems(oracle_input)
            if problems:  # a generator bug, never silently dropped
                raise SystemExit(
                    f"generator produced an over-limit extended input #{index} "
                    f"({applied}): {problems[:3]}"
                )
            case = {
                "id": f"fz-{index:06d}",
                "kind": "extended",
                "mutators": applied,
                "input": raw,
                "oracle_input": oracle_input,
            }
        cases.append(case)
    if validity:
        cases.extend(validity_inputs())
    return cases


# --------------------------------------------------------------------------------------------
# Running the three artifacts
# --------------------------------------------------------------------------------------------
def _roundtrip(value: Any) -> Any:
    return json.loads(json.dumps(value))


def run_python(cases: list[dict[str, Any]]) -> dict[str, Any]:
    engine = engine_module()
    results: dict[str, Any] = {}
    for case in cases:
        original = copy.deepcopy(case["input"])
        payload = copy.deepcopy(case["input"])
        try:
            output = _roundtrip(engine.analyze(payload))
            results[case["id"]] = {
                "ok": True,
                "output": output,
                "mutated": payload != original,
            }
        except Exception as error:  # noqa: BLE001 - an engine may raise anything; record it
            results[case["id"]] = {
                "ok": False,
                "error": f"{type(error).__name__}: {str(error)[:300]}",
                "mutated": payload != original,
            }
    return {"engine": "python", "results": results}


def run_oracle(cases: list[dict[str, Any]]) -> dict[str, Any]:
    oracle = oracle_module()
    results: dict[str, Any] = {}
    for case in cases:
        if case["kind"] == "validity":
            results[case["id"]] = {
                "ok": None,
                "error": "oracle does not judge validity",
            }
            continue
        payload = copy.deepcopy(case.get("oracle_input", case["input"]))
        try:
            results[case["id"]] = {
                "ok": True,
                "output": _roundtrip(oracle.analyze(payload)),
            }
        except Exception as error:  # noqa: BLE001
            results[case["id"]] = {
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
            }
    return {"engine": "oracle", "results": results}


def run_typescript(cases_file: Path, out_file: Path) -> dict[str, Any]:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        raise SystemExit(
            "npx not found on PATH (Node is needed for the TypeScript leg)"
        )
    env = dict(os.environ)
    env["RR_FUZZ_FILE"] = str(cases_file)
    env["RR_FUZZ_OUT"] = str(out_file)
    env.pop("NO_COLOR", None)
    env.pop("FORCE_COLOR", None)
    if out_file.exists():
        out_file.unlink()
    proc = subprocess.run(
        [npx, "vitest", "run", "tests/fuzz-diff.test.ts"],
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
    return json.loads(out_file.read_text(encoding="utf-8"))


def write_cases(
    path: Path, cases: list[dict[str, Any]], seed: int | None = None
) -> None:
    payload = {"seed": seed, "cases": cases}
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def evaluate(
    cases: list[dict[str, Any]], workdir: Path, tag: str
) -> dict[str, dict[str, Any]]:
    """Run all three artifacts over ``cases``; returns ``{id: {python, ts, oracle}}``."""
    workdir.mkdir(parents=True, exist_ok=True)
    cases_file = workdir / f"{tag}.cases.json"
    write_cases(cases_file, cases)
    py = run_python(cases)["results"]
    orc = run_oracle(cases)["results"]
    ts = run_typescript(cases_file, workdir / f"{tag}.ts.json")["results"]
    return {
        case["id"]: {
            "python": py[case["id"]],
            "ts": ts[case["id"]],
            "oracle": orc[case["id"]],
        }
        for case in cases
    }


# --------------------------------------------------------------------------------------------
# Strict comparison and clustering
# --------------------------------------------------------------------------------------------
def strict_diff(a: Any, b: Any, path: str = "$") -> tuple[str, Any, Any] | None:
    """First JSON-strict difference ``(path, a_value, b_value)`` or ``None``."""
    if type(a) is not type(b):
        return path, a, b
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                return f"{path}.{key}", "<missing>", b[key]
            if key not in b:
                return f"{path}.{key}", a[key], "<missing>"
            found = strict_diff(a[key], b[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}.length", len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = strict_diff(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else (path, a, b)


def outcome(result: dict[str, Any]) -> tuple[str, Any]:
    if result.get("ok") is True:
        return "ok", result["output"]
    return "error", result.get("error")


def compare_pair(
    left: dict[str, Any], right: dict[str, Any]
) -> tuple[str, Any, Any] | None:
    lkind, lval = outcome(left)
    rkind, rval = outcome(right)
    if lkind != rkind:
        return f"<outcome {lkind} vs {rkind}>", str(lval)[:160], str(rval)[:160]
    if lkind == "error":
        return None  # both rejected: messages are not part of the contract
    return strict_diff(lval, rval)


def signature(path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", path)


def compare_all(
    cases: list[dict[str, Any]], results: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Per-case verdicts. Output cases compare three ways; validity cases compare two."""
    findings: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for case in cases:
        res = results[case["id"]]
        pairs = [("python", "ts")]
        if case["kind"] != "validity":
            pairs += [("python", "oracle"), ("ts", "oracle")]
        diffs = {}
        for left, right in pairs:
            found = compare_pair(res[left], res[right])
            if found:
                diffs[f"{left}!={right}"] = found
        mutated = [e for e in ("python", "ts") if res[e].get("mutated")]
        if mutated:
            diffs["input-mutated"] = (",".join(mutated), None, None)
        counts[case["kind"]] += 1
        if diffs:
            counts["mismatch:" + case["kind"]] += 1
            for pair in diffs:
                counts["pair:" + pair] += 1
            findings.append({"id": case["id"], "kind": case["kind"], "diffs": diffs})
    return findings, counts


def print_report(
    cases: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    counts: Counter[str],
    results: dict[str, dict[str, Any]],
    limit: int = 25,
) -> None:
    by_id = {c["id"]: c for c in cases}
    total = len(cases)
    bad = len(findings)
    print(
        f"cases: {total}  "
        + "  ".join(f"{k}={v}" for k, v in counts.items() if ":" not in k)
    )
    print(f"all artifacts agree: {total - bad}   mismatching cases: {bad}")
    for key in sorted(counts):
        if key.startswith(("pair:", "mismatch:")):
            print(f"  {key} = {counts[key]}")
    clusters: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in findings:
        for pair, (path, _a, _b) in item["diffs"].items():
            clusters.setdefault((pair, signature(path)), []).append(item)
    if clusters:
        print("clusters (pair, first differing path):")
    for (pair, path), items in sorted(clusters.items(), key=lambda kv: -len(kv[1]))[
        :limit
    ]:
        first = items[0]
        _p, a, b = first["diffs"][pair]
        label = by_id[first["id"]].get("label", "")
        print(f"  [{pair}] {path}  x{len(items)}  e.g. {first['id']} {label}")
        print(f"      {str(a)[:110]!r}  vs  {str(b)[:110]!r}")


def validity_report(
    cases: list[dict[str, Any]], results: dict[str, dict[str, Any]]
) -> int:
    """Print the accept/reject table; return the number of python/ts disagreements."""
    disagreements = 0
    rows = []
    for case in cases:
        if case["kind"] != "validity":
            continue
        res = results[case["id"]]
        py = "accept" if res["python"].get("ok") else "reject"
        ts = "accept" if res["ts"].get("ok") else "reject"
        spec = case["expectation"]
        flag = ""
        if py != ts:
            disagreements += 1
            flag = "DIFFER"
        elif spec in ("accept", "reject") and py != spec:
            flag = "VS-SPEC"
        rows.append((flag, case["id"], case["label"], spec, py, ts))
    print(f"validity catalogue: {len(rows)} cases, python!=ts: {disagreements}")
    for flag, ident, label, spec, py, ts in rows:
        if flag:
            print(
                f"  {flag:8} {ident} {label:36} spec={spec:7} python={py:7} ts={ts:7}"
            )
    return disagreements


# --------------------------------------------------------------------------------------------
# Shrinking
# --------------------------------------------------------------------------------------------
def reductions(raw: dict[str, Any]) -> list[tuple[Any, ...]]:
    ops: list[tuple[Any, ...]] = []
    snaps = raw.get("snapshots", [])
    for i, snap in enumerate(snaps):
        for j in range(len(snap.get("postings", []))):
            ops.append(("post", i, j))
    for i in range(len(snaps)):
        ops.append(("snap", i))
    for d in range(len(raw.get("decisions", []))):
        ops.append(("dec", d))
    for name in ("include_keywords", "exclude_keywords"):
        for k in range(len(raw.get("profile", {}).get(name, []))):
            ops.append(("kw", name, k))
    return ops


def apply_reductions(raw: dict[str, Any], ops: list[tuple[Any, ...]]) -> dict[str, Any]:
    out = copy.deepcopy(raw)
    for op in sorted((o for o in ops if o[0] == "post"), key=lambda o: (-o[1], -o[2])):
        del out["snapshots"][op[1]]["postings"][op[2]]
    for op in sorted((o for o in ops if o[0] == "snap"), key=lambda o: -o[1]):
        del out["snapshots"][op[1]]
    for op in sorted((o for o in ops if o[0] == "dec"), key=lambda o: -o[1]):
        del out["decisions"][op[1]]
    for op in sorted((o for o in ops if o[0] == "kw"), key=lambda o: -o[2]):
        del out["profile"][op[1]][op[2]]
    return out


def shrink(
    case: dict[str, Any], workdir: Path, pair: str | None = None
) -> dict[str, Any]:
    """Greedy delta-debugging of one mismatching case (one vitest run per round)."""
    results = evaluate([case], workdir, "shrink0")[case["id"]]
    found = compare_all([case], {case["id"]: results})[0]
    if not found:
        raise SystemExit(f"case {case['id']} does not mismatch")
    diffs = found[0]["diffs"]
    pair = pair or next(iter(diffs))
    target = signature(diffs[pair][0])
    print(f"shrinking {case['id']} on [{pair}] {target}")
    current = copy.deepcopy(case)
    rounds = 0
    while True:
        rounds += 1
        ops = reductions(current["input"])
        if not ops:
            break
        variants = []
        for n, op in enumerate(ops):
            variant = copy.deepcopy(current)
            variant["id"] = f"shr-{n:04d}"
            variant["input"] = apply_reductions(current["input"], [op])
            if "oracle_input" in variant:
                variant["oracle_input"] = intake(variant["input"])
            variants.append(variant)
        res = evaluate(variants, workdir, "shrink")
        keep = []
        for n, variant in enumerate(variants):
            got = compare_all([variant], {variant["id"]: res[variant["id"]]})[0]
            if (
                got
                and pair in got[0]["diffs"]
                and signature(got[0]["diffs"][pair][0]) == target
            ):
                keep.append(ops[n])
        if not keep:
            break
        trial = copy.deepcopy(current)
        trial["input"] = apply_reductions(current["input"], keep)
        if "oracle_input" in trial:
            trial["oracle_input"] = intake(trial["input"])
        trial["id"] = "shr-joint"
        joint = evaluate([trial], workdir, "shrinkj")["shr-joint"]
        got = compare_all([trial], {"shr-joint": joint})[0]
        if (
            got
            and pair in got[0]["diffs"]
            and signature(got[0]["diffs"][pair][0]) == target
        ):
            current["input"] = trial["input"]
            if "oracle_input" in trial:
                current["oracle_input"] = trial["oracle_input"]
        else:
            current["input"] = apply_reductions(current["input"], [keep[0]])
            if "oracle_input" in current:
                current["oracle_input"] = intake(current["input"])
        print(f"  round {rounds}: applied {len(keep)} reductions")
    return current


# --------------------------------------------------------------------------------------------
# Normalization sweep: norm_text / title_key / location_key over code points and sequences
# --------------------------------------------------------------------------------------------
# Characters whose lowercase mapping is context sensitive (Final_Sigma) or special-cased, and
# characters NFKC rewrites into several code points.
NORM_CONTEXT_PROBES = [
    "Σ",
    "aΣ",
    "aΣb",
    "Σa",
    "AΣ B",
    "A.Σ",
    "AΣ.",
    "AΣ'",
    "A'Σ",
    "A­Σ",
    "AΣ­",
    "ÁΣ",
    "AΣ́",
    "ΑΣΑ",
    "ΑΣ Α",
    "ΑΣ\u200b",
    "ΑΣ’",
    "Α’Σ",
    "ΑΣͅ",
    "ΑΣ\ud800",
    "ΣΣ",
    "AΣΣ",
    "İ",
    "İstanbul",
    "İ",
    "ẞ",
    "ﬃ",
    "ﬁnch",
    "Ω",
    "K",
    "Å",
    "Ა",
    "Ꭰ",
    "Ꭓ",
    "\U00010400",
    "\U000104b0",
    "\U0001e900",
    "Å",
    "Å",
    "é",
    "각",
    "한",
    "क़",
    "ཱི",
    "ﷺ",
    "㎒",
    "㋌",
    "⑴",
    "①",
    "½",
    "x²",
    "Ⅰ",
    "ⅰ",
    "Ạ̊",
    "Ạ̊",
]


def norm_inputs(seed: int, random_count: int) -> list[str]:
    """Every code point on its own, marks after bases, context probes and random sequences."""
    rnd = random.Random(seed)
    inputs: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        if text not in seen:
            seen.add(text)
            inputs.append(text)

    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        add(chr(cp))
    for cp in (0xD800, 0xDBFF, 0xDC00, 0xDFFF):  # lone surrogates (as JSON escapes)
        add(chr(cp))
        add("a" + chr(cp) + "b")
    bases = ["e", "a", "K", "ᄀ", "가", "ا", "क", "あ"]
    assigned: list[int] = []
    marks: list[int] = []
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        category = unicodedata.category(chr(cp))
        if category == "Cn":
            continue
        assigned.append(cp)
        if category[0] == "M":
            marks.append(cp)
    for cp in marks:
        for base in bases:
            add(base + chr(cp))
    for probe in NORM_CONTEXT_PROBES:
        add(probe)
        add(probe.upper())
        add(probe.lower())
        add("Acme " + probe + " Co")
    interesting = [cp for cp in assigned if unicodedata.category(chr(cp))[0] in "LMNZ"]
    for _ in range(random_count):
        length = rnd.randint(2, 7)
        text = "".join(
            chr(rnd.choice(interesting if rnd.random() < 0.7 else assigned))
            for _ in range(length)
        )
        if rnd.random() < 0.3:
            text = text.upper()
        add(text)
    return inputs


def run_norm_python(inputs: list[str]) -> list[list[str]]:
    engine_norm = importlib.import_module("recruit_radar.engine.normalize")
    rows = []
    for text in inputs:
        rows.append(
            [
                engine_norm.norm_text(text),
                engine_norm.title_key(text),
                engine_norm.location_key(text),
            ]
        )
    return rows


def run_norm_oracle(inputs: list[str]) -> list[list[str]]:
    oracle = oracle_module()
    return [
        [oracle.norm_text(t), oracle.title_key(t), oracle.location_key(t)]
        for t in inputs
    ]


def run_norm_typescript(inputs_file: Path, out_file: Path) -> list[list[str]]:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        raise SystemExit(
            "npx not found on PATH (Node is needed for the TypeScript leg)"
        )
    env = dict(os.environ)
    env["RR_NORM_FILE"] = str(inputs_file)
    env["RR_NORM_OUT"] = str(out_file)
    env.pop("NO_COLOR", None)
    env.pop("FORCE_COLOR", None)
    if out_file.exists():
        out_file.unlink()
    proc = subprocess.run(
        [npx, "vitest", "run", "tests/fuzz-diff.test.ts"],
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
    return json.loads(out_file.read_text(encoding="utf-8"))["rows"]


def describe_text(text: str) -> str:
    if len(text) <= 3:
        return " ".join(f"U+{ord(c):04X}[{unicodedata.category(c)}]" for c in text)
    return repr(text)[:60]


def cmd_norm_sweep(args: argparse.Namespace) -> int:
    workdir = (
        Path(args.workdir)
        if args.workdir
        else Path(tempfile.mkdtemp(prefix="rr-norm-"))
    )
    workdir.mkdir(parents=True, exist_ok=True)
    inputs = norm_inputs(args.seed, args.random)
    engine_module()  # puts backend/ on sys.path
    inputs_file = workdir / "norm.inputs.json"
    inputs_file.write_text(
        json.dumps({"inputs": inputs}, ensure_ascii=True), encoding="utf-8"
    )
    python_rows = run_norm_python(inputs)
    oracle_rows = run_norm_oracle(inputs)
    ts_rows = run_norm_typescript(inputs_file, workdir / "norm.ts.json")
    if not (len(inputs) == len(python_rows) == len(oracle_rows) == len(ts_rows)):
        raise SystemExit("the three legs returned different numbers of rows")
    mismatches: list[tuple[str, list[str], list[str], list[str]]] = []
    for text, py, orc, ts in zip(
        inputs, python_rows, oracle_rows, ts_rows, strict=True
    ):
        if not (py == orc == ts):
            mismatches.append((text, py, orc, ts))
    print(f"normalization sweep: {len(inputs)} inputs, {len(mismatches)} mismatching")
    print(f"  python unicodedata = {unicodedata.unidata_version}")
    # A single code point that Python reports as unassigned (Cn) is a Unicode-version skew:
    # the TypeScript runtime may know a newer Unicode than Python does.
    skew = [
        m for m in mismatches if len(m[0]) == 1 and unicodedata.category(m[0]) == "Cn"
    ]
    real = [m for m in mismatches if m not in skew]
    print(
        f"  version skew (single code point unassigned in Python's Unicode): {len(skew)}"
    )
    print(f"  real divergences: {len(real)}")
    for text, py, orc, ts in real[:40]:
        print(f"    {describe_text(text)}  python={py}  oracle={orc}  ts={ts}")
    if skew:
        points = [ord(m[0]) for m in skew]
        print(
            f"  skew code points: {len(points)} "
            f"from U+{min(points):04X} to U+{max(points):04X}"
        )
    report = workdir / "norm.report.json"
    report.write_text(
        json.dumps(
            {
                "inputs": len(inputs),
                "skew": [f"U+{ord(m[0]):04X}" for m in skew],
                "real": [[m[0], m[1], m[2], m[3]] for m in real],
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    print(f"report: {report}")
    return 0 if not real else 1


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------
def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def cmd_all(args: argparse.Namespace) -> int:
    workdir = (
        Path(args.workdir)
        if args.workdir
        else Path(tempfile.mkdtemp(prefix="rr-fuzz-"))
    )
    workdir.mkdir(parents=True, exist_ok=True)
    cases = generate(args.seed, args.count, validity=not args.no_validity)
    tag = f"seed{args.seed}"
    results = evaluate(cases, workdir, tag)
    findings, counts = compare_all(cases, results)
    print(f"workdir: {workdir}  (cases: {tag}.cases.json, typescript: {tag}.ts.json)")
    print_report(cases, findings, counts, results)
    validity_report(cases, results)
    report = workdir / f"{tag}.report.json"
    report.write_text(
        json.dumps({"findings": findings}, ensure_ascii=True), encoding="utf-8"
    )
    print(f"report: {report}")
    output_bad = [f for f in findings if f["kind"] != "validity"]
    validity_bad = [f for f in findings if f["kind"] == "validity"]
    return 0 if not output_bad and not validity_bad else 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("all", help="generate, run all three artifacts, compare")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--count", type=int, default=800)
    p.add_argument("--workdir")
    p.add_argument("--no-validity", action="store_true")
    p.set_defaults(func=cmd_all)

    p = sub.add_parser(
        "norm-sweep",
        help="compare norm_text/title_key/location_key over every code point and sequences",
    )
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--random", type=int, default=20000, help="random sequences to add")
    p.add_argument("--workdir")
    p.set_defaults(func=cmd_norm_sweep)

    p = sub.add_parser("generate", help="write a case file")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--count", type=int, default=800)
    p.add_argument("--out", required=True)
    p.set_defaults(
        func=lambda a: (write_cases(Path(a.out), generate(a.seed, a.count), a.seed), 0)[
            1
        ]
    )

    p = sub.add_parser(
        "compare", help="compare an existing case file with a TypeScript output"
    )
    p.add_argument("--cases", required=True)
    p.add_argument("--ts", required=True)

    def cmd_compare(a: argparse.Namespace) -> int:
        cases = load_cases(Path(a.cases))
        py = run_python(cases)["results"]
        orc = run_oracle(cases)["results"]
        ts = json.loads(Path(a.ts).read_text(encoding="utf-8"))["results"]
        results = {
            c["id"]: {"python": py[c["id"]], "ts": ts[c["id"]], "oracle": orc[c["id"]]}
            for c in cases
        }
        findings, counts = compare_all(cases, results)
        print_report(cases, findings, counts, results)
        validity_report(cases, results)
        return 1 if findings else 0

    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("shrink", help="minimise one mismatching case")
    p.add_argument("--cases", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--pair", help="e.g. python!=ts (default: the first differing pair)")
    p.add_argument("--workdir")
    p.add_argument("--out", help="write the minimised input here")

    def cmd_shrink(a: argparse.Namespace) -> int:
        cases = {c["id"]: c for c in load_cases(Path(a.cases))}
        workdir = (
            Path(a.workdir)
            if a.workdir
            else Path(tempfile.mkdtemp(prefix="rr-shrink-"))
        )
        small = shrink(cases[a.id], workdir, a.pair)
        text = json.dumps(small["input"], indent=2, ensure_ascii=False)
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
        print(text)
        return 0

    p.set_defaults(func=cmd_shrink)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
