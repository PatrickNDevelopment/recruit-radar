#!/usr/bin/env python3
"""RecruitRadar reference oracle (stdlib only).

Written strictly from docs/spec/01-normalization-and-identity.md and
docs/spec/02-lifecycle-and-scoring.md, without looking at either engine.
It exists only to generate and cross-check the golden vectors in
contracts/vectors/.  It is deliberately simple: one pass per spec section,
no caching, no cleverness.

    python contracts/tools/oracle.py --self-check
    python contracts/tools/oracle.py --analyze path/to/analysis-vector.json

READINGS (below) lists the places where the spec text admits more than one
reading.  The default value of each is the most literal reading; the
alternatives exist ONLY so --self-check can prove that no committed vector
depends on an ambiguous sentence.  See docs/spec/ambiguities/vectors.md.
"""

from __future__ import annotations

import argparse
import calendar
import contextlib
import glob
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
VECTOR_DIR = os.path.normpath(os.path.join(HERE, "..", "vectors"))

# ---------------------------------------------------------------- constants
LEGAL_SUFFIXES = frozenset(
    (
        "inc",
        "incorporated",
        "llc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "company",
        "gmbh",
        "plc",
        "ag",
        "sa",
        "bv",
        "nv",
        "llp",
        "lp",
        "pte",
        "pty",
    )
)
SOURCE_WEIGHT = {
    "greenhouse": 1000,
    "lever": 1000,
    "ashby": 1000,
    "csv": 600,
    "manual": 400,
}
SOURCE_KINDS = ("greenhouse", "lever", "ashby", "csv", "manual")
VOLUME_TABLE = (0, 300, 480, 600, 690, 760, 820, 870, 910, 950, 1000)
COMPONENTS = (
    ("role_relevance", 30),
    ("volume", 20),
    ("change", 15),
    ("urgency", 10),
    ("source_confidence", 15),
    ("freshness", 10),
)
CHANGE_WINDOW_S = 30 * 86400
URGENCY_DAYS = 45
MIN_SPAN_DAYS = 14
TRACKED = ("title", "location", "work_mode", "department", "url", "posted_at")
REASONS = ("spacing_variant", "token_overlap", "near_typo")
WORK_MODES = ("remote", "hybrid", "onsite", "unknown")

# Ambiguous-spec switches.  Defaults = most literal reading.
READINGS = {
    # string used to join a source role key for "string compare of the joined key"
    "key_sep": "|",
    # title_key: order in which ( ) and [ ] segments are stripped inside one pass
    "bracket_mode": "paren_then_bracket",  # | bracket_then_paren | alternation
    # title_key: what a removed segment is replaced by ("remove" read literally = nothing)
    "bracket_replace": "delete",  # | space
    # does a not_same decision match raw keys or keys mapped to group canonical keys?
    "not_same": "literal",  # | mapped
    # merge decisions naming a key that no posting has
    "dangling": "literal",  # | present_canonical | ignore
    # "both have >=2 tokens": list length or distinct-token count
    "overlap_tokens": "list",  # | set
    # T: set of timestamps or one entry per snapshot
    "T": "set",  # | multiset
    # which members may supply the displayed title/location/work_mode/department
    "display_members": "all",  # | active_if_active
    # which postings feed aliases / display name
    "names": "all_postings",  # | latest_only
    # title carried by a `reappeared` event
    "reappeared_title": "new",  # | old
    # company.first_seen: min over all roles or over active roles
    "company_first_seen": "all_roles",  # | active_roles
    # role.relevant for a REMOVED canonical role: computed from its title, or null
    "relevant_removed": "computed",  # | null
}


@contextlib.contextmanager
def reading(**overrides):
    old = dict(READINGS)
    READINGS.update(overrides)
    try:
        yield
    finally:
        READINGS.clear()
        READINGS.update(old)


# ------------------------------------------------------------ normalization
def sha12(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def _tokens(normalized: str) -> list[str]:
    return [t for t in normalized.split(" ") if t]


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = "".join(c if unicodedata.category(c)[0] in "LNM" else " " for c in s)
    return " ".join(_tokens(s))


def company_key(name: str) -> str:
    original = _tokens(norm_text(name))
    toks = list(original)
    while toks and toks[-1] in LEGAL_SUFFIXES:
        toks.pop()
    if toks and toks[0] == "the":
        toks.pop(0)
    if not toks:
        toks = original
    return " ".join(toks)


_PAREN = re.compile(r"\([^()]*\)")
_BRACK = re.compile(r"\[[^\[\]]*\]")
_EITHER = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")


def title_key(title: str) -> str:
    t = title
    repl = " " if READINGS["bracket_replace"] == "space" else ""
    while True:
        mode = READINGS["bracket_mode"]
        if mode == "paren_then_bracket":
            n = _BRACK.sub(repl, _PAREN.sub(repl, t))
        elif mode == "bracket_then_paren":
            n = _PAREN.sub(repl, _BRACK.sub(repl, t))
        else:
            n = _EITHER.sub(repl, t)
        if n == t:
            break
        t = n
    return norm_text(t)


def location_key(loc) -> str:
    toks = set(_tokens(norm_text(loc or "")))
    return " ".join(sorted(toks))  # str ordering == code point ordering


def token_sequence_match(tkey: str, phrase: str) -> bool:
    pk = norm_text(phrase)
    if not pk:
        return False
    p = pk.split(" ")
    t = tkey.split(" ") if tkey else []
    return any(t[i : i + len(p)] == p for i in range(len(t) - len(p) + 1))


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# --------------------------------------------------------------------- time
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def epoch(ts: str) -> int:
    """'YYYY-MM-DDTHH:MM:SSZ' -> epoch seconds (UTC)."""
    y, mo, d = int(ts[0:4]), int(ts[5:7]), int(ts[8:10])
    hh, mi, ss = int(ts[11:13]), int(ts[14:16]), int(ts[17:19])
    return calendar.timegm((y, mo, d, hh, mi, ss, 0, 0, 0))


def epoch_date(d: str) -> int:
    """'YYYY-MM-DD' -> epoch of 00:00:00Z."""
    return epoch(d + "T00:00:00Z")


def days_between(a: int, b: int) -> int:
    return (b - a) // 86400  # floor division, as the spec's floor()


def rhu(num: int, den: int) -> int:
    return (2 * num + den) // (2 * den)


def key_str(key: tuple) -> str:
    return READINGS["key_sep"].join(key)


# ----------------------------------------------------------- identity pieces
def source_role_key(src: tuple, p: dict) -> tuple:
    if p["source_posting_id"] is not None:
        return (src[0], src[1], "id", p["source_posting_id"])
    return (
        src[0],
        src[1],
        "k",
        company_key(p["company_name"]),
        title_key(p["title"]),
        location_key(p["location"]),
    )


def build_canon(present: set, decisions: list) -> dict:
    """present company keys -> canonical key of their merge group (union-find)."""
    mode = READINGS["dangling"]
    parent = {k: k for k in present}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    for d in decisions:
        if d["decision"] != "merge":
            continue
        a, b = d["a_key"], d["b_key"]
        if mode == "ignore" and not (a in present and b in present):
            continue
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)  # root is always the smallest member
    members = {}
    for k in parent:
        members.setdefault(find(k), []).append(k)
    canon = {}
    for root, ms in members.items():
        c = root
        if mode == "present_canonical":
            pres = [m for m in ms if m in present]
            c = min(pres) if pres else root
        for m in ms:
            canon[m] = c
    return canon


def candidate_reason(a: str, b: str):
    if a.replace(" ", "") == b.replace(" ", ""):
        return "spacing_variant"
    ta, tb = _tokens(a), _tokens(b)
    if READINGS["overlap_tokens"] == "set":
        enough = len(set(ta)) >= 2 and len(set(tb)) >= 2
    else:
        enough = len(ta) >= 2 and len(tb) >= 2
    if enough:
        sa, sb = set(ta), set(tb)
        if len(sa & sb) * 100 >= 75 * len(sa | sb):
            return "token_overlap"
    if len(a) >= 6 and len(b) >= 6 and levenshtein(a, b) <= 1:
        return "near_typo"
    return None


# ------------------------------------------------------------------ analyze
def analyze(inp: dict) -> dict:
    as_of_s = inp["as_of"]
    as_of = epoch(as_of_s)
    include = inp["profile"]["include_keywords"]
    exclude = inp["profile"]["exclude_keywords"]
    configured = len(include) > 0

    def title_matches(tkey: str) -> bool:
        return any(token_sequence_match(tkey, k) for k in include) and not any(
            token_sequence_match(tkey, k) for k in exclude
        )

    # ---- replay (02 section 2) ----
    snaps = sorted(
        (s for s in inp["snapshots"] if epoch(s["observed_at"]) <= as_of),
        key=lambda s: (s["observed_at"], s["snapshot_id"]),
    )
    roles: dict = {}
    events: list = []
    seen_sources: set = set()
    postings_observed = 0
    for snap in snaps:
        src = (snap["source_kind"], snap["source_ref"])
        is_baseline = src not in seen_sources
        seen_sources.add(src)
        at = snap["observed_at"]
        last: dict = {}
        names: dict = {}
        for idx, p in enumerate(snap["postings"]):
            postings_observed += 1
            k = source_role_key(src, p)
            last[k] = (idx, p)  # later posting replaces earlier one
            names.setdefault(k, []).append((at, p["company_name"]))
        for k, (_, p) in sorted(last.items(), key=lambda kv: kv[1][0]):
            r = roles.get(k)
            if r is None:
                r = roles[k] = {
                    "key": k,
                    "kind": src[0],
                    "ref": src[1],
                    "posting_id": p["source_posting_id"],
                    "company_name": p["company_name"],
                    "names": [],
                    "status": "active",
                    "first_seen": at,
                    "last_seen": at,
                    "removed_at": None,
                    **{f: p[f] for f in TRACKED},
                }
                events.append(
                    {
                        "at": at,
                        "type": "baseline" if is_baseline else "added",
                        "key": k,
                        "title": p["title"],
                        "fields": None,
                    }
                )
            elif r["status"] == "active":
                diff = sorted(f for f in TRACKED if r[f] != p[f])
                if diff:
                    events.append(
                        {
                            "at": at,
                            "type": "changed",
                            "key": k,
                            "title": p["title"],
                            "fields": diff,
                        }
                    )
            else:
                old_title = r["title"]
                r["status"], r["removed_at"] = "active", None
                title = (
                    old_title if READINGS["reappeared_title"] == "old" else p["title"]
                )
                events.append(
                    {
                        "at": at,
                        "type": "reappeared",
                        "key": k,
                        "title": title,
                        "fields": None,
                    }
                )
            for f in TRACKED:
                r[f] = p[f]
            r["company_name"] = p["company_name"]
            r["last_seen"] = at
            r["names"].extend(names[k])
        if snap["mode"] == "full":
            gone = [
                k
                for k, r in roles.items()
                if (r["kind"], r["ref"]) == src
                and r["status"] == "active"
                and k not in last
            ]
            for k in sorted(gone, key=key_str):
                r = roles[k]
                r["status"], r["removed_at"] = "removed", at
                events.append(
                    {
                        "at": at,
                        "type": "removed",
                        "key": k,
                        "title": r["title"],
                        "fields": None,
                    }
                )

    # ---- company identity (01 section 3) ----
    present = {company_key(r["company_name"]) for r in roles.values()}
    canon = build_canon(present, inp["decisions"])
    for r in roles.values():
        r["ckey"] = canon[company_key(r["company_name"])]
    ckeys = sorted({r["ckey"] for r in roles.values()})

    def names_of(ck: str) -> list:
        out = []
        for r in roles.values():
            if r["ckey"] != ck:
                continue
            if READINGS["names"] == "latest_only":
                out.append((r["first_seen"], r["company_name"]))
            else:
                out.extend(r["names"])
        return out

    display = {
        ck: min(names_of(ck)) for ck in ckeys
    }  # earliest observed, then smallest raw name

    # merge candidates
    if READINGS["not_same"] == "mapped":
        not_same = {
            tuple(
                sorted(
                    (
                        canon.get(d["a_key"], d["a_key"]),
                        canon.get(d["b_key"], d["b_key"]),
                    )
                )
            )
            for d in inp["decisions"]
            if d["decision"] == "not_same"
        }
    else:
        not_same = {
            (d["a_key"], d["b_key"])
            for d in inp["decisions"]
            if d["decision"] == "not_same"
        }
    cands = []
    for i, a in enumerate(ckeys):
        for b in ckeys[i + 1 :]:
            if (a, b) in not_same:
                continue
            why = candidate_reason(a, b)
            if why:
                cands.append(
                    {
                        "candidate_id": sha12(a + "|" + b),
                        "a_key": a,
                        "b_key": b,
                        "a_name": display[a][1],
                        "b_name": display[b][1],
                        "reason": why,
                    }
                )
    cands.sort(key=lambda c: (REASONS.index(c["reason"]), c["a_key"], c["b_key"]))

    # ---- canonical roles (01 section 4, 02 section 3) ----
    groups: dict = {}
    for r in roles.values():
        g = (r["ckey"], title_key(r["title"]), location_key(r["location"]))
        groups.setdefault(g, {}).setdefault((r["kind"], r["ref"]), []).append(r)
    croles = []
    for (ck, tk, lk), by_src in groups.items():
        cid = "c_" + sha12(ck)
        for lst in by_src.values():
            lst.sort(key=lambda r: key_str(r["key"]))
        for i in range(max(len(lst) for lst in by_src.values())):
            members = [by_src[s][i] for s in sorted(by_src) if len(by_src[s]) > i]
            active = [m for m in members if m["status"] == "active"]
            pool = (
                active
                if (READINGS["display_members"] == "active_if_active" and active)
                else members
            )
            shown = min(pool, key=lambda m: (-epoch(m["last_seen"]), key_str(m["key"])))
            posted = [m["posted_at"] for m in members if m["posted_at"] is not None]
            first_seen = min(m["first_seen"] for m in members)
            posted_at = min(posted) if posted else None
            age_from = epoch_date(posted_at) if posted_at else epoch(first_seen)
            croles.append(
                {
                    "ckey": ck,
                    "company_id": cid,
                    "role_id": "r_" + sha12(cid + "|" + tk + "|" + lk + "|" + str(i)),
                    "title": shown["title"],
                    "location": shown["location"],
                    "work_mode": shown["work_mode"],
                    "department": shown["department"],
                    "posted_at": posted_at,
                    "status": "active" if active else "removed",
                    "first_seen": first_seen,
                    "last_seen": max(m["last_seen"] for m in (active or members)),
                    "removed_at": None
                    if active
                    else max(m["removed_at"] for m in members),
                    "relevant": (
                        None
                        if not configured
                        or (READINGS["relevant_removed"] == "null" and not active)
                        else title_matches(tk)
                    ),
                    "age_days": max(0, days_between(age_from, as_of)),
                    "_posted_epoch": epoch_date(posted_at) if posted_at else None,
                    "_members": members,
                    "_active": active,
                    "observations": [
                        {
                            "source_kind": m["kind"],
                            "source_ref": m["ref"],
                            "source_posting_id": m["posting_id"],
                            "url": m["url"],
                            "status": m["status"],
                            "first_seen": m["first_seen"],
                            "last_seen": m["last_seen"],
                        }
                        for m in sorted(
                            members,
                            key=lambda m: (m["kind"], m["ref"], m["posting_id"] or ""),
                        )
                    ],
                }
            )

    role_of_key = {}
    for cr in croles:
        for m in cr["_members"]:
            role_of_key[m["key"]] = cr

    # ---- scoring (02 section 4) ----
    full_by_source: dict = {}
    for s in snaps:
        if s["mode"] == "full":
            full_by_source.setdefault((s["source_kind"], s["source_ref"]), []).append(
                s["observed_at"]
            )

    companies = []
    for ck in ckeys:
        cid = "c_" + sha12(ck)
        c_roles = [cr for cr in croles if cr["ckey"] == ck]
        A = [cr for cr in c_roles if cr["status"] == "active"]
        R = [cr for cr in A if cr["relevant"] is True]
        scope = R if configured else A
        sources = {(r["kind"], r["ref"]) for r in roles.values() if r["ckey"] == ck}
        T = [t for s in sorted(sources) for t in full_by_source.get(s, [])]
        if READINGS["T"] == "set":
            T = sorted(set(T))
        span = days_between(epoch(min(T)), epoch(max(T))) if len(T) >= 2 else None

        def comp(key, value, code, inputs):
            return {
                "key": key,
                "weight": dict(COMPONENTS)[key],
                "value": value,
                "reason_code": code,
                "inputs": inputs,
            }

        none = "no_active_roles"
        if not A:
            comps = [
                comp("role_relevance", None, none, {"relevant": None, "active": 0}),
                comp("volume", None, none, {"scope_roles": 0}),
                comp(
                    "change",
                    None,
                    none,
                    {
                        "added": None,
                        "removed": None,
                        "net": None,
                        "span_days": span,
                        "window_days": 30,
                    },
                ),
                comp(
                    "urgency",
                    None,
                    none,
                    {"aged": None, "known": None, "threshold_days": 45},
                ),
                comp(
                    "source_confidence",
                    None,
                    none,
                    {"scope_roles": 0, "corroborated": None},
                ),
                comp("freshness", None, none, {"days_since_last_seen": None}),
            ]
            last_seen = None
        else:
            # role_relevance
            if configured:
                rr = comp(
                    "role_relevance",
                    rhu(1000 * len(R), len(A)),
                    None,
                    {"relevant": len(R), "active": len(A)},
                )
            else:
                rr = comp(
                    "role_relevance",
                    None,
                    "no_keywords",
                    {"relevant": None, "active": len(A)},
                )
            # volume
            vol = comp(
                "volume",
                VOLUME_TABLE[min(len(scope), 10)],
                None,
                {"scope_roles": len(scope)},
            )
            # change
            if len(T) < 2 or span < MIN_SPAN_DAYS:
                chg = comp(
                    "change",
                    None,
                    "insufficient_history",
                    {
                        "added": None,
                        "removed": None,
                        "net": None,
                        "span_days": span,
                        "window_days": 30,
                    },
                )
            else:
                added = removed = 0
                for e in events:
                    r = roles[e["key"]]
                    if r["ckey"] != ck or e["type"] not in (
                        "added",
                        "reappeared",
                        "removed",
                    ):
                        continue
                    t = epoch(e["at"])
                    if not (as_of - CHANGE_WINDOW_S < t <= as_of):
                        continue
                    if configured and not title_matches(title_key(e["title"])):
                        continue
                    if e["type"] == "removed":
                        removed += 1
                    else:
                        added += 1
                net = added - removed
                chg = comp(
                    "change",
                    min(1000, max(0, 500 + 100 * net)),
                    None,
                    {
                        "added": added,
                        "removed": removed,
                        "net": net,
                        "span_days": span,
                        "window_days": 30,
                    },
                )
            # urgency
            known = aged = 0
            for cr in scope:
                if cr["_posted_epoch"] is not None:
                    age = days_between(cr["_posted_epoch"], as_of)
                elif span is not None and span >= URGENCY_DAYS:
                    age = days_between(epoch(cr["first_seen"]), as_of)
                else:
                    continue
                known += 1
                aged += 1 if age >= URGENCY_DAYS else 0
            uin = {"aged": aged, "known": known, "threshold_days": 45}
            if not scope:
                urg = comp("urgency", None, "no_scope_roles", uin)
            elif known == 0:
                urg = comp("urgency", None, "no_dated_roles", uin)
            else:
                urg = comp("urgency", rhu(1000 * aged, known), None, uin)
            # source_confidence
            total = corroborated = 0
            for cr in scope:
                best = max(SOURCE_WEIGHT[m["kind"]] for m in cr["_active"])
                if len({(m["kind"], m["ref"]) for m in cr["_active"]}) >= 2:
                    best = min(1000, best + 100)
                    corroborated += 1
                total += best
            cin = {"scope_roles": len(scope), "corroborated": corroborated}
            if not scope:
                conf = comp("source_confidence", None, "no_scope_roles", cin)
            else:
                conf = comp("source_confidence", rhu(total, len(scope)), None, cin)
            # freshness
            last_seen = max(cr["last_seen"] for cr in A)
            d = max(0, days_between(epoch(last_seen), as_of))
            fv = 1000 if d <= 7 else 0 if d >= 60 else rhu(1000 * (60 - d), 53)
            fr = comp("freshness", fv, None, {"days_since_last_seen": d})
            comps = [rr, vol, chg, urg, conf, fr]

        W = sum(c["weight"] for c in comps if c["value"] is not None)
        score = (
            rhu(
                sum(c["weight"] * c["value"] for c in comps if c["value"] is not None),
                W,
            )
            if W
            else None
        )
        fs_roles = (
            [cr for cr in c_roles if cr["status"] == "active"]
            if (READINGS["company_first_seen"] == "active_roles" and A)
            else c_roles
        )
        companies.append(
            {
                "company_id": cid,
                "key": ck,
                "name": display[ck][1],
                "aliases": sorted({n for _, n in names_of(ck)}),
                "first_seen": min(cr["first_seen"] for cr in fs_roles),
                "last_seen": last_seen,
                "active_roles": len(A),
                "relevant_roles": len(R) if configured else None,
                "removed_roles": len(c_roles) - len(A),
                "score": score,
                "coverage": W,
                "rank": None,
                "components": comps,
            }
        )

    scored = sorted(
        (c for c in companies if c["score"] is not None),
        key=lambda c: (-c["score"], c["key"], c["company_id"]),
    )
    for n, c in enumerate(scored, 1):
        c["rank"] = n
    unscored = sorted(
        (c for c in companies if c["score"] is None),
        key=lambda c: (c["key"], c["company_id"]),
    )
    companies = scored + unscored
    order = {c["company_id"]: n for n, c in enumerate(companies)}

    out_roles = []
    for cr in sorted(
        croles,
        key=lambda c: (
            order[c["company_id"]],
            c["status"] != "active",
            c["first_seen"],
            c["role_id"],
        ),
    ):
        out_roles.append(
            {
                k: cr[k]
                for k in (
                    "role_id",
                    "company_id",
                    "title",
                    "location",
                    "work_mode",
                    "department",
                    "posted_at",
                    "status",
                    "first_seen",
                    "last_seen",
                    "removed_at",
                    "relevant",
                    "age_days",
                    "observations",
                )
            }
        )
    out_events = []
    for e in events:
        cr = role_of_key[e["key"]]
        out_events.append(
            {
                "at": e["at"],
                "type": e["type"],
                "company_id": cr["company_id"],
                "role_id": cr["role_id"],
                "source_kind": e["key"][0],
                "source_ref": e["key"][1],
                "title": e["title"],
                "fields": e["fields"],
            }
        )
    return {
        "as_of": as_of_s,
        "companies": companies,
        "roles": out_roles,
        "events": out_events,
        "merge_candidates": cands,
        "stats": {
            "snapshots": len(snaps),
            "postings_observed": postings_observed,
            "companies": len(companies),
            "active_roles": sum(1 for r in out_roles if r["status"] == "active"),
        },
    }


# --------------------------------------------------------------- validation
def validate_input(inp: dict) -> list:
    """Return a list of problems with an analysis input (empty list = conforms to 01/02)."""
    bad: list = []

    def need(cond, msg):
        if not cond:
            bad.append(msg)

    need(set(inp) == {"as_of", "profile", "decisions", "snapshots"}, "top-level keys")
    need(
        isinstance(inp.get("as_of"), str) and _TS.fullmatch(inp["as_of"]) is not None,
        "as_of format",
    )
    prof = inp.get("profile", {})
    need(set(prof) == {"include_keywords", "exclude_keywords"}, "profile keys")
    for name in ("include_keywords", "exclude_keywords"):
        kws = prof.get(name, [])
        need(isinstance(kws, list) and len(kws) <= 50, f"{name} count")
        for k in kws:
            need(isinstance(k, str) and 1 <= len(k) <= 60, f"{name} item length {k!r}")
            need(
                norm_text(k) != "",
                f"{name} item normalizes to empty {k!r} (excluded by design, see ambiguities)",
            )
    need(
        not (not prof.get("include_keywords") and prof.get("exclude_keywords")),
        "exclude_keywords without include_keywords (ambiguous, excluded by design)",
    )
    for d in inp.get("decisions", []):
        need(set(d) == {"a_key", "b_key", "decision"}, "decision keys")
        need(d["a_key"] < d["b_key"], f"decision keys not ordered {d}")
        need(d["decision"] in ("merge", "not_same"), "decision value")
    ids = set()
    for s in inp.get("snapshots", []):
        need(
            set(s)
            == {
                "snapshot_id",
                "source_kind",
                "source_ref",
                "observed_at",
                "mode",
                "postings",
            },
            "snapshot keys",
        )
        need(s["snapshot_id"] not in ids, f"duplicate snapshot_id {s['snapshot_id']}")
        ids.add(s["snapshot_id"])
        need(s["source_kind"] in SOURCE_KINDS, "source_kind")
        need(
            isinstance(s["source_ref"], str)
            and 1 <= len(s["source_ref"]) <= 200
            and s["source_ref"] == s["source_ref"].strip(),
            "source_ref",
        )
        need(s["mode"] in ("full", "additive"), "mode")
        if _TS.fullmatch(s["observed_at"]) is None:
            bad.append("observed_at format")
        else:
            datetime.strptime(s["observed_at"], "%Y-%m-%dT%H:%M:%SZ")
        for p in s["postings"]:
            need(
                set(p)
                == {
                    "source_kind",
                    "source_ref",
                    "source_posting_id",
                    "company_name",
                    "title",
                    "location",
                    "work_mode",
                    "department",
                    "url",
                    "posted_at",
                },
                "posting keys",
            )
            need(
                p["source_kind"] == s["source_kind"]
                and p["source_ref"] == s["source_ref"],
                "posting source differs from snapshot source (ambiguous, excluded by design)",
            )
            pid = p["source_posting_id"]
            need(
                pid is None
                or (isinstance(pid, str) and pid == pid.strip() and pid != ""),
                "posting id",
            )
            need(
                s["source_kind"] in ("csv", "manual") or pid is not None,
                "ATS posting needs an id",
            )
            for f, lo, hi in (("company_name", 1, 200), ("title", 1, 300)):
                need(
                    isinstance(p[f], str)
                    and lo <= len(p[f]) <= hi
                    and p[f] == p[f].strip(),
                    f"{f} {p[f]!r}",
                )
            for f, hi in (("location", 300), ("department", 200)):
                v = p[f]
                need(
                    v is None
                    or (isinstance(v, str) and 1 <= len(v) <= hi and v == v.strip()),
                    f"{f} {v!r}",
                )
            need(p["work_mode"] in WORK_MODES, "work_mode")
            need(
                p["url"] is None or re.match(r"https?://\S+$", p["url"]) is not None,
                "url",
            )
            if p["posted_at"] is not None:
                need(_DATE.fullmatch(p["posted_at"]) is not None, "posted_at format")
                try:
                    datetime.strptime(p["posted_at"], "%Y-%m-%d")
                except ValueError:
                    bad.append(f"posted_at not a real date {p['posted_at']}")
    return bad


def check_ids(a: dict) -> list:
    """Internal consistency of an Analysis: ids derive from keys, references resolve."""
    bad = []
    cids = {c["company_id"] for c in a["companies"]}
    if len(cids) != len(a["companies"]):
        bad.append("duplicate company_id")
    for c in a["companies"]:
        if c["company_id"] != "c_" + sha12(c["key"]):
            bad.append(f"company_id/key mismatch {c['key']!r}")
        if [x["key"] for x in c["components"]] != [k for k, _ in COMPONENTS]:
            bad.append("component order")
    rids = {r["role_id"] for r in a["roles"]}
    if len(rids) != len(a["roles"]):
        bad.append("duplicate role_id")
    key_of = {c["company_id"]: c["key"] for c in a["companies"]}
    for r in a["roles"]:
        if r["company_id"] not in cids:
            bad.append("role with unknown company_id")
            continue
        tk, lk = title_key(r["title"]), location_key(r["location"])
        if not any(
            r["role_id"]
            == "r_" + sha12(r["company_id"] + "|" + tk + "|" + lk + "|" + str(i))
            for i in range(len(a["roles"]) + 1)
        ):
            bad.append(
                f"role_id does not derive from (company, title_key, location_key, i): {r['title']!r}"
            )
        if key_of[r["company_id"]] is None:
            bad.append("company key missing")
    for e in a["events"]:
        if e["company_id"] not in cids or e["role_id"] not in rids:
            bad.append("event references unknown company/role")
    for m in a["merge_candidates"]:
        if m["candidate_id"] != sha12(m["a_key"] + "|" + m["b_key"]):
            bad.append("candidate_id mismatch")
        if not m["a_key"] < m["b_key"]:
            bad.append("candidate keys unordered")
    return bad


# ---------------------------------------------------------------- self-check
NORM_FUNCS = {
    "norm_text": norm_text,
    "company_key": company_key,
    "title_key": title_key,
    "location_key": location_key,
    "sha12": sha12,
}


def run_norm_case(case: dict):
    fn = case["fn"]
    if fn == "token_sequence_match":
        return token_sequence_match(case["input"]["title"], case["input"]["phrase"])
    return NORM_FUNCS[fn](case["input"])


# Values derived by hand (HAND_CHECKS.md) BEFORE the oracle was run on these vectors.
# vector name -> company key -> (score, coverage, rank, [component values in fixed order])
HAND_DERIVED = {
    "minimal-single-role": {
        "software house": (813, 75, 1, [1000, 300, None, None, 1000, 1000])
    },
    "name-variants-collapse": {
        "acme": (778, 45, 1, [None, 600, None, None, 867, 1000])
    },
    "freshness-boundaries": {
        "amberly": (689, 45, 1, [None, 300, None, None, 1000, 1000]),
        "birchwood": (689, 45, 2, [None, 300, None, None, 1000, 1000]),
        "cedarville": (689, 45, 3, [None, 300, None, None, 1000, 1000]),
        "dahlia works": (685, 45, 4, [None, 300, None, None, 1000, 981]),
        "elmstead": (471, 45, 5, [None, 300, None, None, 1000, 19]),
        "fjordhaven": (471, 45, 6, [None, 300, None, None, 1000, 19]),
        "granite quay": (467, 45, 7, [None, 300, None, None, 1000, 0]),
        "hollowell": (467, 45, 8, [None, 300, None, None, 1000, 0]),
        "ivywood": (467, 45, 9, [None, 300, None, None, 1000, 0]),
    },
    "change-span-14-vs-13": {
        "yankee yards": (681, 45, 1, [None, 480, None, None, 1000, 604]),
        "xray xylem": (661, 60, 2, [None, 480, 600, None, 1000, 604]),
    },
    "urgency-44-vs-45": {
        "tern analytics": (819, 85, 1, [1000, 480, None, 500, 1000, 1000])
    },
    "cross-source-corroboration": {
        "acme": (775, 45, 1, [None, 690, None, None, 775, 943])
    },
    "keyword-token-sequence-and-exclude": {
        "kestrel": (643, 75, 1, [375, 600, None, None, 1000, 1000])
    },
    "change-window-30d-edges": {
        "marsh": (733, 70, 1, [None, 690, 500, 500, 1000, 1000])
    },
    "all-roles-removed": {
        "live oak": (689, 45, 1, [None, 300, None, None, 1000, 1000]),
        "ghost kitchen": (None, 0, None, [None, None, None, None, None, None]),
    },
    "score-ties-order-by-key": {
        "7 seas": (689, 45, 1, [None, 300, None, None, 1000, 1000]),
        "alpha works": (689, 45, 2, [None, 300, None, None, 1000, 1000]),
        "zebra works": (689, 45, 3, [None, 300, None, None, 1000, 1000]),
        "\u00e9mile works": (689, 45, 4, [None, 300, None, None, 1000, 1000]),
        "\u03c9mega works": (689, 45, 5, [None, 300, None, None, 1000, 1000]),
    },
    "no-scope-roles": {"plum row": (231, 75, 1, [0, 0, 500, None, None, 981])},
    "urgency-posted-at-vs-first-seen-span-rule": {
        "quartz mill": (688, 70, 1, [None, 480, 500, 1000, 1000, 604]),
        "raven press": (668, 45, 2, [None, 300, None, None, 1000, 906]),
        "pine harbor": (648, 70, 3, [None, 600, 600, 333, 1000, 604]),
    },
    "headcounts-two-roles-same-source": {
        "support house": (893, 75, 1, [1000, 600, None, None, 1000, 1000])
    },
    "change-title-scope-filter": {"acme": (466, 100, 1, [250, 300, 600, 0, 1000, 906])},
    "headcounts-match-across-sources": {
        "support hub": (668, 45, 1, [None, 480, None, None, 1000, 547])
    },
    "additive-imports-are-not-history": {
        "lumen": (698, 45, 1, [None, 480, None, None, 800, 981])
    },
    "canonical-last-seen-ignores-removed-members": {
        "prism labs": (369, 60, 1, [None, 300, 200, None, 600, 415])
    },
    "duplicate-keys-last-wins": {
        "acme": (822, 45, 1, [None, 600, None, None, 1000, 1000])
    },
    # HC-21 .. HC-23: derived by hand (HAND_CHECKS.md) before the oracle was run on them.
    "span-counts-instants-not-snapshots": {
        "tidewater freight": (668, 45, 1, [None, 300, None, None, 1000, 906]),
        "pier nine": (626, 60, 2, [None, 300, 500, None, 1000, 906]),
    },
    "merge-through-absent-key-names-the-group": {
        "ardent hollow": (589, 45, 1, [None, 300, None, None, 700, 1000]),
        "dune row": (589, 45, 2, [None, 300, None, None, 700, 1000]),
    },
    "not-same-names-the-canonical-pair": {
        "alpha group": (589, 45, 1, [None, 300, None, None, 700, 1000]),
        "alpha groupz": (556, 45, 2, [None, 300, None, None, 600, 1000]),
        "delta works": (556, 45, 3, [None, 300, None, None, 600, 1000]),
        "delta workz": (556, 45, 4, [None, 300, None, None, 600, 1000]),
    },
}


# Structural values derived by hand (HAND_CHECKS.md).  Candidate ids were computed with a bare
# hashlib one-liner (sha256 of 'a|b', first 12 hex chars), not with this module.
_K1 = "".join(chr(0x20000 + i) for i in range(6))
HAND_CANDIDATES = {
    "merge-candidates-three-reasons": [
        ("spacing_variant", "door dash", "doordash", "ab57d53a978a"),
        (
            "token_overlap",
            "blue ocean shipping",
            "blue ocean shipping group",
            "5dda8a28b3a6",
        ),
        ("near_typo", "acme robotic", "acme robotics", "e9c738f08ae2"),
    ],
    "candidate-reason-precedence": [
        (
            "spacing_variant",
            "alpha beta gamma delta epsilon zeta eta theta iota x y",
            "alpha beta gamma delta epsilon zeta eta theta iota xy",
            None,
        ),
        ("token_overlap", "ab cd ef gh ij kl mn", "ab cd ef gh ij kl mo", None),
        (
            "token_overlap",
            "delta echo foxtrot golf hotel india juliet kilo",
            "delta echo foxtrot golf hotel india juliet lima",
            None,
        ),
    ],
    "near-typo-boundaries": [
        ("near_typo", "nordic", "nordik", None),
        ("near_typo", "quantom", "quantum", None),
        ("near_typo", _K1, _K1[:5] + "\U00021006", None),
    ],
    "candidate-code-point-order": [
        ("near_typo", "rocket \ufe0f", "rocket \U00020000", None)
    ],
    "not-same-hides-candidate": [("near_typo", "acme robotic", "acme robotics", None)],
    "merge-decision-applies-to-history": [],
    "merge-transitive-canonical-only-candidates": [],
    "name-variants-collapse": [],
    "span-counts-instants-not-snapshots": [],
    "merge-through-absent-key-names-the-group": [],
    # the id is sha256('alpha group|alpha groupz')[:12] from a bare hashlib one-liner
    "not-same-names-the-canonical-pair": [
        ("near_typo", "alpha group", "alpha groupz", "3895f6ac16ad")
    ],
}
# vector -> events in output order: (at, type, source_kind, source_ref, title, fields)
HAND_EVENTS = {
    "snapshot-order-id-tiebreak": [
        ("2026-10-01T00:00:00Z", "baseline", "greenhouse", "alpha", "Painter", None),
        ("2026-10-01T00:00:00Z", "baseline", "greenhouse", "beta", "Welder", None),
        ("2026-10-01T00:00:00Z", "baseline", "csv", "list", "Rigger", None),
        ("2026-10-01T00:00:00Z", "added", "csv", "list", "Fitter", None),
    ],
    "duplicate-keys-last-wins": [
        ("2026-10-10T00:00:00Z", "baseline", "greenhouse", "acme", "Designer", None),
        ("2026-10-10T00:00:00Z", "baseline", "greenhouse", "acme", "Engineer v2", None),
        (
            "2026-10-10T00:00:00Z",
            "baseline",
            "greenhouse",
            "acme",
            "Office Manager",
            None,
        ),
    ],
    "removal-then-reappearance": [
        (
            "2026-09-01T00:00:00Z",
            "baseline",
            "greenhouse",
            "acme",
            "Backend Engineer",
            None,
        ),
        (
            "2026-09-01T00:00:00Z",
            "baseline",
            "greenhouse",
            "acme",
            "Frontend Engineer",
            None,
        ),
        (
            "2026-09-10T00:00:00Z",
            "removed",
            "greenhouse",
            "acme",
            "Frontend Engineer",
            None,
        ),
        (
            "2026-09-20T00:00:00Z",
            "reappeared",
            "greenhouse",
            "acme",
            "Frontend Engineer",
            None,
        ),
        (
            "2026-10-01T00:00:00Z",
            "removed",
            "greenhouse",
            "acme",
            "Frontend Engineer",
            None,
        ),
    ],
    "rename-and-field-changes": [
        (
            "2026-09-01T00:00:00Z",
            "baseline",
            "greenhouse",
            "acme",
            "Backend Engineer",
            None,
        ),
        (
            "2026-09-01T00:00:00Z",
            "baseline",
            "greenhouse",
            "acme",
            "Product Designer",
            None,
        ),
        (
            "2026-09-01T00:00:00Z",
            "baseline",
            "greenhouse",
            "acme",
            "Data Analyst",
            None,
        ),
        (
            "2026-09-01T00:00:00Z",
            "baseline",
            "greenhouse",
            "acme",
            "Office Manager",
            None,
        ),
        (
            "2026-09-20T00:00:00Z",
            "changed",
            "greenhouse",
            "acme",
            "Senior Backend Engineer",
            ["title"],
        ),
        (
            "2026-09-20T00:00:00Z",
            "changed",
            "greenhouse",
            "acme",
            "Product Designer",
            ["department", "url"],
        ),
        (
            "2026-09-20T00:00:00Z",
            "changed",
            "greenhouse",
            "acme",
            "Data Analyst",
            ["posted_at"],
        ),
        (
            "2026-09-20T00:00:00Z",
            "changed",
            "greenhouse",
            "acme",
            "Facilities Manager",
            ["location", "title", "work_mode"],
        ),
    ],
    "all-roles-removed": [
        ("2026-09-01T00:00:00Z", "baseline", "greenhouse", "ghost", "Dishwasher", None),
        ("2026-09-01T00:00:00Z", "baseline", "greenhouse", "ghost", "Chef", None),
        ("2026-09-20T00:00:00Z", "removed", "greenhouse", "ghost", "Chef", None),
        ("2026-09-20T00:00:00Z", "removed", "greenhouse", "ghost", "Dishwasher", None),
        ("2026-10-10T00:00:00Z", "baseline", "greenhouse", "liveoak", "Arborist", None),
    ],
    "change-title-scope-filter": [
        ("2026-08-01T00:00:00Z", "baseline", "greenhouse", "acme", "Engineer", None),
        ("2026-08-01T00:00:00Z", "baseline", "greenhouse", "acme", "Designer", None),
        (
            "2026-08-01T00:00:00Z",
            "baseline",
            "greenhouse",
            "acme",
            "Engineer Intern",
            None,
        ),
        (
            "2026-08-01T00:00:00Z",
            "baseline",
            "greenhouse",
            "acme",
            "Engineer Two",
            None,
        ),
        (
            "2026-09-20T00:00:00Z",
            "changed",
            "greenhouse",
            "acme",
            "Designer",
            ["title"],
        ),
        (
            "2026-09-20T00:00:00Z",
            "added",
            "greenhouse",
            "acme",
            "Backend Engineer",
            None,
        ),
        ("2026-09-20T00:00:00Z", "added", "greenhouse", "acme", "Marketing Lead", None),
        (
            "2026-09-20T00:00:00Z",
            "added",
            "greenhouse",
            "acme",
            "Engineer Intern",
            None,
        ),
        ("2026-09-20T00:00:00Z", "added", "greenhouse", "acme", "Staff Engineer", None),
        (
            "2026-10-01T00:00:00Z",
            "changed",
            "greenhouse",
            "acme",
            "Staff Designer",
            ["title"],
        ),
        ("2026-10-01T00:00:00Z", "removed", "greenhouse", "acme", "Designer", None),
        ("2026-10-01T00:00:00Z", "removed", "greenhouse", "acme", "Designer", None),
        (
            "2026-10-01T00:00:00Z",
            "removed",
            "greenhouse",
            "acme",
            "Engineer Intern",
            None,
        ),
        ("2026-10-01T00:00:00Z", "removed", "greenhouse", "acme", "Engineer Two", None),
    ],
    "csv-null-id-rows-collapse": [
        (
            "2026-10-08T00:00:00Z",
            "baseline",
            "csv",
            "jobs-export",
            "Support Engineer",
            None,
        ),
        (
            "2026-10-08T00:00:00Z",
            "baseline",
            "csv",
            "jobs-export",
            "Support Engineer",
            None,
        ),
        (
            "2026-10-08T00:00:00Z",
            "baseline",
            "csv",
            "jobs-export",
            "Account Executive",
            None,
        ),
        (
            "2026-10-08T00:00:00Z",
            "baseline",
            "csv",
            "jobs-export",
            "Account Executive",
            None,
        ),
        (
            "2026-10-10T00:00:00Z",
            "changed",
            "csv",
            "jobs-export",
            "Support Engineer",
            ["department", "location"],
        ),
    ],
}


# vector -> canonical roles as sets of observations (source_kind, source_ref, source_posting_id),
# listed by the hand-derived pairing rule: i-th smallest key of every source forms canonical role i.
# vector -> {title: (status, first_seen, last_seen, removed_at)} derived by hand
HAND_ROLE_TIMES = {
    "canonical-last-seen-ignores-removed-members": {
        "Optics Engineer": (
            "active",
            "2026-09-01T00:00:00Z",
            "2026-09-05T00:00:00Z",
            None,
        ),
        "Legacy Analyst": (
            "removed",
            "2026-09-01T00:00:00Z",
            "2026-09-20T00:00:00Z",
            "2026-10-08T00:00:00Z",
        ),
    },
}
HAND_OBSERVATIONS = {
    "headcounts-match-across-sources": [
        {
            ("greenhouse", "support", "201"),
            ("lever", "support", "L-a"),
            ("csv", "support-sheet", None),
        },
        {("greenhouse", "support", "202"), ("lever", "support", "L-b")},
    ],
    # four source roles, two canonical roles: each pairs the hollow-a row with the hollow-b row
    "merge-through-absent-key-names-the-group": [
        {("csv", "hollow-a", None), ("csv", "hollow-b", None)},
        {("csv", "hollow-a", None), ("csv", "hollow-b", None)},
    ],
}


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def self_check() -> int:
    fails: list = []
    notes: list = []

    def fail(msg):
        fails.append(msg)

    # --- normalization vectors
    npath = os.path.join(VECTOR_DIR, "normalization.json")
    norm = _load(npath)
    cases = norm["cases"]
    per_fn: dict = {}
    for c in cases:
        per_fn[c["fn"]] = per_fn.get(c["fn"], 0) + 1
        got = run_norm_case(c)
        if got != c["expected"]:
            fail(f"normalization {c['id']}: expected {c['expected']!r} got {got!r}")
        if (
            c["fn"] == "token_sequence_match"
            and title_key(c["input"]["title"]) != c["input"]["title"]
        ):
            fail(f"normalization {c['id']}: title must already be a title_key")
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        fail("duplicate normalization case ids")
    if len(cases) < 80:
        fail(f"only {len(cases)} normalization cases (need >= 80)")
    for fn in (
        "norm_text",
        "company_key",
        "title_key",
        "location_key",
        "token_sequence_match",
        "sha12",
    ):
        if per_fn.get(fn, 0) == 0:
            fail(f"no normalization cases for {fn}")
    notes.append(f"normalization: {len(cases)} cases {dict(sorted(per_fn.items()))}")

    # --- analysis vectors
    files = sorted(glob.glob(os.path.join(VECTOR_DIR, "analysis-*.json")))
    if len(files) < 24:
        fail(f"only {len(files)} analysis vectors (need >= 24)")
    vectors = {}
    must_be_insensitive = [
        ("key_sep", ["\x00", "\x1f", "/", ":"]),
        ("bracket_mode", ["bracket_then_paren", "alternation"]),
        ("bracket_replace", ["space"]),
        ("overlap_tokens", ["set"]),
        ("display_members", ["active_if_active"]),
        ("names", ["latest_only"]),
        ("reappeared_title", ["old"]),
    ]
    # Readings the differential review DECIDED (docs/spec/ambiguities/differential.md D-2, D-3,
    # D-4) and then pinned with dedicated vectors: the alternative must change exactly those
    # vectors - proving they are sensitive - and no other one.
    pinned = {
        ("T", "multiset"): ["span-counts-instants-not-snapshots"],
        ("dangling", "present_canonical"): ["merge-through-absent-key-names-the-group"],
        ("dangling", "ignore"): ["merge-through-absent-key-names-the-group"],
        ("not_same", "mapped"): ["not-same-names-the-canonical-pair"],
    }
    pinned_readings: dict = {}
    for name, val in pinned:
        pinned_readings.setdefault(name, []).append(val)
    informational = [
        ("company_first_seen", ["active_roles"]),
        ("relevant_removed", ["null"]),
    ]
    sensitive: dict = {}
    for path in files:
        v = _load(path)
        base = os.path.basename(path)
        if set(v) != {"name", "description", "input", "expected"}:
            fail(f"{base}: keys {sorted(v)}")
            continue
        if not base.endswith(v["name"] + ".json"):
            fail(f"{base}: name {v['name']!r} does not match file name")
        if v["name"] in vectors:
            fail(f"duplicate vector name {v['name']}")
        vectors[v["name"]] = v
        for problem in validate_input(v["input"]):
            fail(f"{base}: input: {problem}")
        got = analyze(v["input"])
        if got != v["expected"]:
            fail(f"{base}: oracle output differs from file")
            continue  # variants are only meaningful relative to a matching base output
        for problem in check_ids(v["expected"]):
            fail(f"{base}: ids: {problem}")
        for name, values in (
            must_be_insensitive + informational + list(pinned_readings.items())
        ):
            for val in values:
                with reading(**{name: val}):
                    if analyze(v["input"]) != v["expected"]:
                        sensitive.setdefault((name, val), []).append(v["name"])
    for (name, val), vecs in sorted(sensitive.items()):
        if (name, val) in pinned:
            continue  # checked against the exact expected set below
        if name in dict(must_be_insensitive):
            fail(f"vectors depend on ambiguous reading {name}={val!r}: {vecs}")
        else:
            notes.append(
                f"informational: reading {name}={val!r} changes {len(vecs)} vector(s): {vecs}"
            )
    for (name, val), want in sorted(pinned.items()):
        got = sorted(sensitive.get((name, val), []))
        if got != sorted(want):
            fail(
                f"decided reading {name}={val!r}: expected it to change {want}, got {got}"
            )
    notes.append(
        f"analysis: {len(vectors)} vectors, insensitive to {len(must_be_insensitive)} ambiguous "
        f"readings, {len(pinned)} decided readings pinned by dedicated vectors"
    )

    # --- hand-derived values
    for vname, per_company in HAND_DERIVED.items():
        v = vectors.get(vname)
        if v is None:
            fail(f"hand-derived vector {vname} missing")
            continue
        by_key = {c["key"]: c for c in v["expected"]["companies"]}
        for ck, (score, cov, rank, vals) in per_company.items():
            c = by_key.get(ck)
            if c is None:
                fail(f"{vname}: company {ck!r} missing")
                continue
            got = (
                c["score"],
                c["coverage"],
                c["rank"],
                [x["value"] for x in c["components"]],
            )
            if got != (score, cov, rank, vals):
                fail(f"{vname}/{ck}: hand {(score, cov, rank, vals)} != oracle {got}")
    notes.append(
        f"hand-derived: {sum(len(x) for x in HAND_DERIVED.values())} companies in "
        f"{len(HAND_DERIVED)} vectors"
    )

    # --- structural hand-derived values
    for vname, want in HAND_CANDIDATES.items():
        v = vectors.get(vname)
        if v is None:
            fail(f"hand-derived vector {vname} missing")
            continue
        got = [
            (m["reason"], m["a_key"], m["b_key"], m["candidate_id"])
            for m in v["expected"]["merge_candidates"]
        ]
        same = len(got) == len(want) and all(
            g[:3] == w[:3] and (w[3] is None or g[3] == w[3]) for g, w in zip(got, want)
        )
        if not same:
            fail(f"{vname}: hand candidates {want} != oracle {got}")
    for vname, want in HAND_EVENTS.items():
        v = vectors.get(vname)
        if v is None:
            fail(f"hand-derived vector {vname} missing")
            continue
        got = [
            (
                e["at"],
                e["type"],
                e["source_kind"],
                e["source_ref"],
                e["title"],
                e["fields"],
            )
            for e in v["expected"]["events"]
        ]
        if got != want:
            fail(f"{vname}: hand events differ from oracle events")
    notes.append(
        f"hand-derived structure: candidates in {len(HAND_CANDIDATES)} vectors, "
        f"event order in {len(HAND_EVENTS)} vectors"
    )

    for vname, want in HAND_OBSERVATIONS.items():
        v = vectors.get(vname)
        if v is None:
            fail(f"hand-derived vector {vname} missing")
            continue
        got = [
            {
                (o["source_kind"], o["source_ref"], o["source_posting_id"])
                for o in r["observations"]
            }
            for r in v["expected"]["roles"]
        ]
        if sorted(map(sorted, got), key=str) != sorted(map(sorted, want), key=str):
            fail(f"{vname}: hand observation pairing differs from oracle")

    for vname, want in HAND_ROLE_TIMES.items():
        v = vectors.get(vname)
        if v is None:
            fail(f"hand-derived vector {vname} missing")
            continue
        got = {
            r["title"]: (r["status"], r["first_seen"], r["last_seen"], r["removed_at"])
            for r in v["expected"]["roles"]
        }
        if got != want:
            fail(f"{vname}: hand role times {want} != oracle {got}")

    # --- generator in sync with files
    try:
        sys.path.insert(0, HERE)
        import generate_vectors

        built_norm, built_analysis = generate_vectors.build_all()
        if built_norm != norm:
            fail("normalization.json is out of date with generate_vectors.py")
        built_names = {v["name"]: v for v in built_analysis}
        if set(built_names) != set(vectors):
            fail(
                f"generator/file vector sets differ: {sorted(set(built_names) ^ set(vectors))}"
            )
        for n, bv in built_names.items():
            if n in vectors and bv != vectors[n]:
                fail(f"analysis vector {n} out of date with generate_vectors.py")
        notes.append("generator: files match a fresh build")
    except ImportError:
        notes.append("generator: generate_vectors.py not importable (skipped)")

    # --- README references
    readme = os.path.join(VECTOR_DIR, "README.md")
    if os.path.exists(readme):
        with open(readme, encoding="utf-8") as fh:
            text = fh.read()
        for ref in sorted(set(re.findall(r"`vec:([a-z0-9-]+)`", text))):
            if ref not in vectors:
                fail(f"README references unknown vector {ref}")
    for n in notes:
        print(n)
    if fails:
        print(f"SELF-CHECK FAILED ({len(fails)} problem(s)):")
        for f in fails:
            print("  -", f)
        return 1
    print("SELF-CHECK OK")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(
            AttributeError, ValueError
        ):  # not a TextIOWrapper: leave as is
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="re-generate every vector and compare with the files",
    )
    ap.add_argument(
        "--analyze",
        metavar="FILE",
        help="print analyze() of a vector file or a bare input JSON",
    )
    args = ap.parse_args(argv)
    if args.self_check:
        return self_check()
    if args.analyze:
        data = _load(args.analyze)
        inp = data.get("input", data)
        print(json.dumps(analyze(inp), indent=2, ensure_ascii=False))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
