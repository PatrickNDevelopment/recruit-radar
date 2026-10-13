"""Seeded randomized invariant suite for analyze() (320 generated inputs)."""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from recruit_radar.engine import analyze
from recruit_radar.engine.normalize import company_key
from recruit_radar.engine.timeutil import timestamp_to_epoch

COMPANY_NAMES = [
    "Acme",
    "ACME Inc.",
    "acme, inc",
    "Acme Robotics",
    "Acme Robotic",
    "DoorDash",
    "Door Dash",
    "Globex Corporation",
    "The Globex",
    "Initech",
    "Initech LLC",
    "Umbrella",
    "Umbrella Labs",
    "Hooli",
    "Hooli XYZ Group",
    "Hooli XYZ Grp",
    "AT&T",
]
TITLES = [
    "Software Engineer",
    "Senior Software Engineer (Remote)",
    "Sales Intern",
    "Account Executive",
    "Data Engineer [US]",
    "Product Manager",
    "Engineering Manager",
    "Recruiter",
    "Staff ML Engineer",
]
LOCATIONS = [None, "New York, NY", "NY - New York", "Remote", "San Francisco, CA", "London", ""]
SOURCES = [
    ("greenhouse", "acme"),
    ("greenhouse", "globex"),
    ("lever", "acme"),
    ("ashby", "initech"),
    ("csv", "leads"),
    ("csv", "import-2"),
    ("manual", "manual"),
]
WORK_MODES = [None, "remote", "hybrid", "onsite", "unknown"]
INCLUDE_POOL = ["engineer", "software engineer", "data", "manager", "ml"]
EXCLUDE_POOL = ["intern", "senior", "sales"]
BASE_EPOCH = timestamp_to_epoch("2026-07-01T00:00:00Z")


def iso(epoch: int) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_date(epoch: int) -> str:
    return iso(epoch)[:10]


def random_input(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    day = 86_400
    # A small day pool makes equal observed_at values (sort ties) common.
    day_pool = [rng.randint(0, 120) for _ in range(rng.randint(2, 7))]
    snapshots: list[dict[str, Any]] = []
    for index in range(rng.randint(0, 9)):
        kind, ref = rng.choice(SOURCES)
        additive_bias = 0.8 if kind in {"csv", "manual"} else 0.25
        mode = "additive" if rng.random() < additive_bias else "full"
        observed = BASE_EPOCH + rng.choice(day_pool) * day + rng.choice([0, 0, 0, 1, 3600, 43_200])
        postings: list[dict[str, Any]] = []
        for _ in range(rng.randint(0, 8)):
            raw: dict[str, Any] = {
                "company_name": rng.choice(COMPANY_NAMES),
                "title": rng.choice(TITLES),
            }
            if rng.random() < (0.9 if kind not in {"csv", "manual"} else 0.3):
                raw["source_posting_id"] = str(rng.randint(1, 8))
            location = rng.choice(LOCATIONS)
            if location is not None:
                raw["location"] = location
            work_mode = rng.choice(WORK_MODES)
            if work_mode is not None:
                raw["work_mode"] = work_mode
            if rng.random() < 0.4:
                raw["posted_at"] = iso_date(BASE_EPOCH + rng.randint(-60, 135) * day)
            if rng.random() < 0.3:
                raw["department"] = rng.choice(["Eng", "Sales", "People"])
            if rng.random() < 0.3:
                raw["url"] = f"https://jobs.example.test/{rng.randint(1, 5)}"
            postings.append(raw)
        snapshots.append(
            {
                "snapshot_id": f"snap-{index}",
                "source_kind": kind,
                "source_ref": ref,
                "observed_at": iso(observed),
                "mode": mode,
                "postings": postings,
            }
        )
    keys = sorted({company_key(n) for n in COMPANY_NAMES})
    decisions: list[dict[str, str]] = []
    for _ in range(rng.choice([0, 0, 1, 2, 4])):
        a, b = sorted(rng.sample(keys, 2))
        decisions.append(
            {"a_key": a, "b_key": b, "decision": rng.choice(["merge", "not_same", "merge"])}
        )
    include = rng.sample(INCLUDE_POOL, rng.choice([0, 0, 1, 2]))
    exclude = rng.sample(EXCLUDE_POOL, rng.choice([0, 0, 1, 2]))
    as_of = iso(BASE_EPOCH + rng.randint(20, 170) * day + rng.choice([0, 0, 777, 43_200]))
    return {
        "as_of": as_of,
        "profile": {"include_keywords": include, "exclude_keywords": exclude},
        "decisions": decisions,
        "snapshots": snapshots,
    }


def check_invariants(payload: dict[str, Any], analysis: dict[str, Any]) -> None:
    as_of = payload["as_of"]
    companies: list[dict[str, Any]] = analysis["companies"]
    roles: list[dict[str, Any]] = analysis["roles"]
    evts: list[dict[str, Any]] = analysis["events"]
    keywords_configured = bool(payload["profile"]["include_keywords"])
    processed = [s for s in payload["snapshots"] if s["observed_at"] <= as_of]

    # --- companies ------------------------------------------------------------------------
    assert len({c["company_id"] for c in companies}) == len(companies)
    assert len({c["key"] for c in companies}) == len(companies)
    for comp in companies:
        assert [c["key"] for c in comp["components"]] == [
            "role_relevance",
            "volume",
            "change",
            "urgency",
            "source_confidence",
            "freshness",
        ]
        assert sum(c["weight"] for c in comp["components"]) == 100
        non_null = [c for c in comp["components"] if c["value"] is not None]
        assert comp["coverage"] == sum(c["weight"] for c in non_null)
        for c in comp["components"]:
            assert (c["value"] is None) == (c["reason_code"] is not None)
            if c["value"] is not None:
                assert isinstance(c["value"], int) and 0 <= c["value"] <= 1000
        if comp["coverage"] == 0:
            assert comp["score"] is None and comp["rank"] is None
            assert comp["active_roles"] == 0
        else:
            assert isinstance(comp["score"], int) and 0 <= comp["score"] <= 1000
            total = sum(c["weight"] * c["value"] for c in non_null)
            low = total / comp["coverage"]
            assert abs(comp["score"] - low) <= 0.5 + 1e-9
            assert comp["active_roles"] > 0
        assert (comp["relevant_roles"] is None) == (not keywords_configured)
        if comp["relevant_roles"] is not None:
            assert 0 <= comp["relevant_roles"] <= comp["active_roles"]
        assert comp["aliases"] == sorted(set(comp["aliases"]))
        assert comp["name"] in comp["aliases"]
        assert (comp["last_seen"] is None) == (comp["active_roles"] == 0)
        if comp["last_seen"] is not None:
            assert comp["first_seen"] <= comp["last_seen"] <= as_of

    # ranks contiguous, ordered, scored before unscored
    scored = [c for c in companies if c["score"] is not None]
    unscored = [c for c in companies if c["score"] is None]
    assert companies == scored + unscored
    assert [c["rank"] for c in scored] == list(range(1, len(scored) + 1))
    assert [(-c["score"], c["key"], c["company_id"]) for c in scored] == sorted(
        (-c["score"], c["key"], c["company_id"]) for c in scored
    )
    assert [(c["key"], c["company_id"]) for c in unscored] == sorted(
        (c["key"], c["company_id"]) for c in unscored
    )

    # --- roles ------------------------------------------------------------------------------
    role_ids = [r["role_id"] for r in roles]
    assert len(set(role_ids)) == len(role_ids)
    company_ids = {c["company_id"] for c in companies}
    by_company = Counter(r["company_id"] for r in roles)
    assert set(by_company) == company_ids
    for r in roles:
        assert r["observations"], "a canonical role always has at least one observation"
        statuses = {o["status"] for o in r["observations"]}
        assert r["status"] == ("active" if "active" in statuses else "removed")
        assert (r["removed_at"] is None) == (r["status"] == "active")
        assert r["first_seen"] <= r["last_seen"] <= as_of
        assert isinstance(r["age_days"], int) and r["age_days"] >= 0
        assert (r["relevant"] is None) == (not keywords_configured)
        sort_key = [
            (o["source_kind"], o["source_ref"], o["source_posting_id"] or "")
            for o in r["observations"]
        ]
        assert sort_key == sorted(sort_key)
        pairs = [(o["source_kind"], o["source_ref"]) for o in r["observations"]]
        assert len(set(pairs)) == len(pairs), "at most one observation per source"
        assert r["first_seen"] == min(o["first_seen"] for o in r["observations"])
    for comp in companies:
        mine = [r for r in roles if r["company_id"] == comp["company_id"]]
        assert comp["active_roles"] == sum(r["status"] == "active" for r in mine)
        assert comp["removed_roles"] == sum(r["status"] == "removed" for r in mine)
        order = [(0 if r["status"] == "active" else 1, r["first_seen"], r["role_id"]) for r in mine]
        assert order == sorted(order)
    company_order = [c["company_id"] for c in companies]
    positions = [company_order.index(r["company_id"]) for r in roles]
    assert positions == sorted(positions)

    # --- events ------------------------------------------------------------------------------
    role_by_id = {r["role_id"]: r for r in roles}
    assert [e["at"] for e in evts] == sorted(e["at"] for e in evts)
    full_instants = {
        (s["source_kind"], s["source_ref"], s["observed_at"])
        for s in processed
        if s["mode"] == "full"
    }
    for e in evts:
        assert e["role_id"] in role_by_id, "events reference existing roles"
        assert role_by_id[e["role_id"]]["company_id"] == e["company_id"]
        assert e["company_id"] in company_ids
        assert e["at"] <= as_of
        assert (e["fields"] is not None) == (e["type"] == "changed")
        if e["fields"] is not None:
            assert e["fields"] == sorted(set(e["fields"])) and e["fields"]
        if e["type"] == "removed":
            assert (e["source_kind"], e["source_ref"], e["at"]) in full_instants
        assert e["type"] in {"baseline", "added", "changed", "removed", "reappeared"}
    # exactly one baseline "wave" per source: baseline events share one timestamp per source
    baseline_instants: dict[tuple[str, str], set[str]] = {}
    for e in evts:
        if e["type"] == "baseline":
            baseline_instants.setdefault((e["source_kind"], e["source_ref"]), set()).add(e["at"])
    assert all(len(v) == 1 for v in baseline_instants.values())
    for (kind, ref), instants in baseline_instants.items():
        (instant,) = instants
        first = min(
            s["observed_at"]
            for s in processed
            if (s["source_kind"], s["source_ref"]) == (kind, ref)
        )
        assert instant == first

    # --- stats -------------------------------------------------------------------------------
    assert analysis["stats"] == {
        "snapshots": len(processed),
        "postings_observed": sum(len(s["postings"]) for s in processed),
        "companies": len(companies),
        "active_roles": sum(c["active_roles"] for c in companies),
    }

    # --- merge candidates --------------------------------------------------------------------
    keys = {c["key"] for c in companies}
    not_same = {
        (d["a_key"], d["b_key"]) for d in payload["decisions"] if d["decision"] == "not_same"
    }
    seen_pairs: set[tuple[str, str]] = set()
    order_rank = {"spacing_variant": 0, "token_overlap": 1, "near_typo": 2}
    previous: tuple[int, str, str] = (0, "", "")
    for cand in analysis["merge_candidates"]:
        assert cand["a_key"] < cand["b_key"]
        assert cand["a_key"] in keys and cand["b_key"] in keys
        assert (cand["a_key"], cand["b_key"]) not in not_same
        assert (cand["a_key"], cand["b_key"]) not in seen_pairs
        seen_pairs.add((cand["a_key"], cand["b_key"]))
        current = (order_rank[cand["reason"]], cand["a_key"], cand["b_key"])
        assert current >= previous
        previous = current
    assert len({c["candidate_id"] for c in analysis["merge_candidates"]}) == len(
        analysis["merge_candidates"]
    )

    # the output is plain JSON
    assert json.loads(json.dumps(analysis)) == analysis


SEEDS = list(range(320))


@pytest.mark.parametrize("seed", SEEDS)
def test_invariants_hold(seed: int) -> None:
    payload = random_input(seed)
    snapshot_of_input = copy.deepcopy(payload)

    first = analyze(payload)
    assert payload == snapshot_of_input, "analyze must not mutate its input"
    assert analyze(payload) == first, "running analyze twice must give the identical result"
    check_invariants(payload, first)

    # snapshot input order is irrelevant: (observed_at, snapshot_id) is a total order
    shuffled = copy.deepcopy(payload)
    random.Random(seed ^ 0x5EED).shuffle(shuffled["snapshots"])
    random.Random(seed ^ 0xDEC).shuffle(shuffled["decisions"])
    assert analyze(shuffled) == first


def test_generator_exercises_the_interesting_paths() -> None:
    """Guard against a degenerate generator: the corpus must contain every lifecycle path."""
    totals: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    for seed in SEEDS:
        result = analyze(random_input(seed))
        for e in result["events"]:
            totals[e["type"]] += 1
        stats = result["stats"]
        flags["has_company"] += stats["companies"] > 0
        flags["has_candidates"] += bool(result["merge_candidates"])
        flags["has_unscored"] += any(c["score"] is None for c in result["companies"])
        flags["multi_source_role"] += any(len(r["observations"]) > 1 for r in result["roles"])
        flags["change_computed"] += any(
            c["key"] == "change" and c["value"] is not None
            for comp in result["companies"]
            for c in comp["components"]
        )
        flags["future_snapshot_dropped"] += stats["snapshots"] < len(
            random_input(seed)["snapshots"]
        )
    for kind in ("baseline", "added", "changed", "removed", "reappeared"):
        assert totals[kind] > 0, f"no {kind} events in the generated corpus"
    for flag in (
        "has_company",
        "has_candidates",
        "has_unscored",
        "multi_source_role",
        "change_computed",
        "future_snapshot_dropped",
    ):
        assert flags[flag] > 0, flag


def test_result_does_not_depend_on_hash_randomization() -> None:
    """Two interpreters with different PYTHONHASHSEED values must agree byte for byte."""
    here = Path(__file__).resolve().parent
    backend = here.parent.parent
    script = (
        "import hashlib, json, sys\n"
        f"sys.path.insert(0, {str(backend)!r})\n"
        f"sys.path.insert(0, {str(here)!r})\n"
        "import test_engine_invariants as t\n"
        "from recruit_radar.engine import analyze\n"
        "h = hashlib.sha256()\n"
        "for seed in range(0, 320, 4):\n"
        "    out = analyze(t.random_input(seed))\n"
        "    h.update(json.dumps(out, sort_keys=False).encode())\n"
        "print(h.hexdigest())\n"
    )
    digests = []
    for hash_seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        done = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
            timeout=300,
        )
        digests.append(done.stdout.strip())
    assert digests[0] == digests[1]
    assert len(digests[0]) == 64


def test_shuffled_ties_are_stable_for_many_equal_observed_at_values() -> None:
    """Many snapshots at one instant: only snapshot_id decides the order, never input order."""
    rng = random.Random(7)
    snaps = []
    for index in range(12):
        snaps.append(
            {
                "snapshot_id": f"id-{index:02d}",
                "source_kind": "greenhouse",
                "source_ref": "acme",
                "observed_at": "2026-09-01T00:00:00Z",
                "mode": rng.choice(["full", "additive"]),
                "postings": [
                    {
                        "company_name": "Acme",
                        "title": f"Role {rng.randint(1, 4)}",
                        "source_posting_id": str(rng.randint(1, 4)),
                    }
                    for _ in range(rng.randint(0, 3))
                ],
            }
        )
    payload = {"as_of": "2026-10-01T00:00:00Z", "snapshots": snaps}
    expected = analyze(payload)
    for trial in range(25):
        shuffled = copy.deepcopy(payload)
        random.Random(trial).shuffle(shuffled["snapshots"])
        assert analyze(shuffled) == expected
    assert hashlib.sha256(json.dumps(expected).encode()).hexdigest()
