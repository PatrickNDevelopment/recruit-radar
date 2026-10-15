#!/usr/bin/env python3
"""Builds contracts/vectors/*.json.

Inputs and every normalization expectation are written by hand in this file;
`expected` of each analysis vector is produced by oracle.analyze().  Normalization
expectations are asserted against the oracle at build time, so a disagreement
between my reading and the oracle stops the build.

    python contracts/tools/generate_vectors.py            # (re)write the files
    python contracts/tools/oracle.py --self-check         # verify the files

This source file is pure ASCII on purpose: every non-ASCII code point is a
\\u escape so that no editor, terminal or VCS can silently normalize it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import oracle

VECTOR_DIR = oracle.VECTOR_DIR
FE0F = "\ufe0f"
AS_OF = "2026-10-13T12:00:00Z"


# ======================================================== normalization cases
def norm_cases():
    """(fn, input, expected, note).  Expected values are hand-written."""
    C = []

    def add(fn, inp, expected, note):
        C.append((fn, inp, expected, note))

    # ---- norm_text
    nt = lambda i, e, n: add("norm_text", i, e, n)
    nt("Hello World", "hello world", "plain ASCII, lowercase")
    nt(
        "  Multiple   spaces\t\ttabs\r\nand\nnewlines  ",
        "multiple spaces tabs and newlines",
        "mixed whitespace collapses to single spaces, ends trimmed",
    )
    nt(
        "a\u00a0b\u2003c\u3000d",
        "a b c d",
        "NBSP, em space, ideographic space are separators",
    )
    nt(
        "\uff21\uff23\uff2d\uff25\u3000\uff11\uff12\uff13",
        "acme 123",
        "fullwidth Latin, space and digits fold under NFKC",
    )
    nt("Caf\u00e9", "caf\u00e9", "precomposed accent preserved (not stripped)")
    nt("Cafe\u0301", "caf\u00e9", "decomposed e + U+0301 composes under NFKC")
    nt("Stra\u00dfe", "stra\u00dfe", "sharp s is not casefolded to ss")
    nt("STRASSE", "strasse", "ASCII SS stays ss, so differs from the sharp-s spelling")
    nt("STRA\u1e9eE", "stra\u00dfe", "capital sharp s lowercases to sharp s")
    nt(
        "\u0130stanbul",
        "i\u0307stanbul",
        "Turkish dotted capital I -> i + U+0307 (kept: category Mn)",
    )
    nt("ISTANBUL", "istanbul", "plain I lowercases to i, not dotless i (locale-free)")
    nt("\u0131stanbul", "\u0131stanbul", "dotless i is already lowercase and stays")
    nt(
        "\u041c\u041e\u0421\u041a\u0412\u0410",
        "\u043c\u043e\u0441\u043a\u0432\u0430",
        "Cyrillic lowercases",
    )
    nt(
        "\u6771\u4eac\u3001\u6e0b\u8c37\u3002",
        "\u6771\u4eac \u6e0b\u8c37",
        "CJK letters kept, ideographic punctuation separates",
    )
    nt("Rocket \U0001f680 Labs", "rocket labs", "emoji (So) is a separator")
    nt(
        "\u2764\ufe0f",
        FE0F,
        "heart + VS16: the heart is a separator but U+FE0F is category Mn and survives",
    )
    nt(
        "\U0001f468\u200d\U0001f469\u200d\U0001f467",
        "",
        "ZWJ family emoji: all So/Cf -> empty",
    )
    nt(
        "1\ufe0f\u20e3",
        "1\ufe0f\u20e3",
        "keycap sequence: digit + Mn + Me all survive as one token",
    )
    nt(
        "\u0301abc",
        "\u0301abc",
        "lone leading combining mark is category M and survives",
    )
    nt(
        "(Remote) [US]",
        "remote us",
        "brackets are separators in norm_text (only title_key removes them)",
    )
    nt("AT&T", "at t", "ampersand splits")
    nt(
        "O'Brien & Sons, Ltd.",
        "o brien sons ltd",
        "apostrophe, ampersand, comma, period",
    )
    nt("C++ / C# / .NET", "c c net", "symbols dropped, single letters kept")
    nt("", "", "empty input")
    nt("!!!---???", "", "punctuation only -> empty")
    nt("   \t\n ", "", "whitespace only -> empty")
    nt("3M", "3m", "digits are kept")
    nt("7-Eleven", "7 eleven", "hyphen splits")
    nt("H\u2082O", "h2o", "subscript two folds to 2 under NFKC")
    nt("\u2167", "viii", "roman numeral eight (Nl) NFKC-expands to letters")
    nt(
        "\u0663\u0664",
        "\u0663\u0664",
        "Arabic-Indic digits are category Nd and survive unchanged",
    )
    nt("\ufb01nance", "finance", "fi ligature expands under NFKC")
    nt("Acme\u2122", "acmetm", "trade mark sign NFKC-expands to the letters TM")
    nt(
        "\u039f\u0394\u03a5\u03a3\u03a3\u0395\u03a5\u03a3",
        "\u03bf\u03b4\u03c5\u03c3\u03c3\u03b5\u03c5\u03c2",
        "final sigma: only the last capital sigma lowercases to U+03C2 (default, non-locale lowercasing)",
    )
    nt("\u03a3", "\u03c3", "lone capital sigma lowercases to medial sigma")
    nt(
        "O\u02bcBrien",
        "o\u02bcbrien",
        "U+02BC modifier letter apostrophe is category Lm: a LETTER, not a separator",
    )
    nt("co\u00adoperate", "co operate", "soft hyphen (Cf) is a separator")
    nt(
        "a\u200bb\u200cc\u200dd\ufeffe",
        "a b c d e",
        "ZWSP, ZWNJ, ZWJ, BOM are all separators",
    )
    nt("\u212a", "k", "Kelvin sign NFKC-folds to K")
    nt("\u212b", "\u00e5", "Angstrom sign NFKC-folds to A-ring, lowercased")
    nt("\u00bd time", "1 2 time", "vulgar half expands to 1, fraction slash (Sm), 2")
    nt("\u24b6cme", "acme", "circled A folds to A")
    nt(
        "\u3231\u30a2\u30af\u30e1",
        "\u682a \u30a2\u30af\u30e1",
        "parenthesized ideograph stock expands to (kabu): parens separate",
    )
    nt(
        "\uff08Remote\uff09",
        "remote",
        "fullwidth parentheses become ASCII parentheses then separators",
    )
    nt(
        "\uff71\uff78\uff92",
        "\u30a2\u30af\u30e1",
        "halfwidth katakana widen under NFKC",
    )
    nt("\u01c5", "d\u017e", "titlecase DZ-caron digraph expands to d + z-caron")
    nt(
        "\U0001d400\U0001d41c\U0001d426\U0001d41e",
        "acme",
        "mathematical bold letters (astral) fold to ASCII",
    )
    nt(
        "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35",
        "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35",
        "Thai letters + vowel marks (Mn) all kept",
    )
    nt(
        "\u05e9\u05c1\u05dc\u05d5\u05b9\u05dd",
        "\u05e9\u05c1\u05dc\u05d5\u05b9\u05dd",
        "Hebrew with points: Mn marks kept",
    )
    nt(
        "\u00c5ngstr\u00f6m",
        "\u00e5ngstr\u00f6m",
        "Latin-1 uppercase accents lowercase",
    )
    nt("\u0e3f100", "100", "currency symbol (Sc) is a separator, digits stay")
    nt(
        "a_b-c.d/e\\f",
        "a b c d e f",
        "underscore (Pc), hyphen (Pd), period, slashes all separate",
    )
    nt(
        "Tab\tseparated\u000bvertical\u000cform",
        "tab separated vertical form",
        "VT and FF are whitespace",
    )
    nt("\u00aa", "a", "feminine ordinal indicator NFKC-folds to a")
    nt(
        "x\u0338y",
        "x\u0338y",
        "combining long solidus overlay (Mn) stays inside the token",
    )
    nt("\u1100\u1161", "\uac00", "Hangul jamo pair composes to a syllable under NFKC")
    nt("\u00df", "\u00df", "lone sharp s")
    nt("\u00a9 2026", "2026", "copyright sign (So) separates, digits stay")

    # ---- company_key
    ck = lambda i, e, n: add("company_key", i, e, n)
    ck("Acme, Inc.", "acme", "spec example")
    ck(
        "The Acme Corporation",
        "acme",
        "spec example: leading 'the' and trailing suffix",
    )
    ck("Inc", "inc", "spec example: suffix-only name keeps its tokens")
    ck("AT&T", "at t", "spec example")
    ck("Acme Co Ltd", "acme", "two stacked suffixes")
    ck("ACME INC. LLC", "acme", "uppercase, punctuation, stacked suffixes")
    ck(
        "The Inc",
        "the inc",
        "dropping suffix then 'the' would leave nothing -> original tokens",
    )
    ck("The", "the", "'the' alone is kept")
    ck("The The", "the", "only a single leading 'the' is dropped")
    ck(
        "The Company",
        "the company",
        "suffix + 'the' would empty the key -> original tokens",
    )
    ck("Co Inc", "co inc", "all tokens are suffixes -> original tokens")
    ck("Inc Inc", "inc inc", "all tokens are suffixes -> original tokens")
    ck("Pte Ltd", "pte ltd", "all suffixes -> original tokens")
    ck("The Co Ltd", "the co ltd", "drop ltd, co, the would empty -> original tokens")
    ck("Inc. Acme", "inc acme", "a leading suffix word is not dropped")
    ck(
        "Acme Inc Holdings",
        "acme inc holdings",
        "a mid-name suffix word is not dropped",
    )
    ck("Acme Holding AG", "acme holding", "AG is a suffix, 'holding' is not")
    ck(
        "Acme S.A.",
        "acme s a",
        "S.A. normalizes to tokens 's','a' - not the suffix 'sa'",
    )
    ck("Acme SA", "acme", "SA without dots is the suffix")
    ck(
        "Acme GmbH & Co. KG",
        "acme gmbh co kg",
        "trailing 'kg' is not a suffix, so nothing is dropped",
    )
    ck("Acme L.L.C.", "acme l l c", "dotted LLC is three tokens, not the suffix")
    ck("Acme Pty. Ltd.", "acme", "Pty + Ltd")
    ck(
        "Acme Limited Liability Company",
        "acme limited liability",
        "only the trailing 'company' goes; 'limited' is no longer trailing",
    )
    ck("Acme Incorporated", "acme", "'incorporated' is a suffix")
    ck(
        "\uff21\uff43\uff4d\uff45\u3000\uff29\uff4e\uff43\uff0e",
        "acme",
        "fullwidth 'Acme Inc.' normalizes first",
    )
    ck("!!!", "", "no tokens at all -> empty key")
    ck("", "", "empty name")
    ck(
        "The Acme The",
        "acme the",
        "trailing 'the' is not a suffix; only the leading 'the' goes",
    )
    ck("Acme The", "acme the", "'the' is only dropped when leading")
    ck("the the inc", "the", "inc dropped, then one leading 'the'")
    ck("Acme Corp Inc Co", "acme", "four suffix words, longest chain")
    ck("Stra\u00dfe GmbH", "stra\u00dfe", "sharp s kept, GmbH dropped")
    ck(
        "\u682a\u5f0f\u4f1a\u793e\u30a2\u30af\u30e1",
        "\u682a\u5f0f\u4f1a\u793e\u30a2\u30af\u30e1",
        "CJK corporate prefix is not in the Latin suffix set",
    )
    ck("Acme Co.", "acme", "period after suffix")
    ck("Co", "co", "single suffix token kept")
    ck(
        "The O'Brien Company",
        "o brien",
        "'company' dropped, 'the' dropped, apostrophe split",
    )

    # ---- title_key
    tk = lambda i, e, n: add("title_key", i, e, n)
    tk("Senior Engineer (Remote) [US]", "senior engineer", "spec example")
    tk(
        "Engineer (Remote (US))",
        "engineer",
        "nested parentheses removed innermost first, repeatedly",
    )
    tk(
        "Engineer (Remote",
        "engineer remote",
        "unbalanced open parenthesis: nothing removed, punctuation separates",
    )
    tk("Engineer Remote)", "engineer remote", "unbalanced close parenthesis")
    tk(
        "Engineer ((Remote)",
        "engineer",
        "inner pair removed, stray '(' becomes a separator",
    )
    tk("Engineer [Remote (US)]", "engineer", "parentheses inside brackets")
    tk(
        "Engineer [Remote (US]",
        "engineer",
        "bracket pair containing a stray '(' is still removed",
    )
    tk("Engineer [[Remote]]", "engineer", "nested brackets")
    tk(
        "Data(Science)Engineer",
        "dataengineer",
        "removal deletes the segment (no space inserted): neighbours fuse",
    )
    tk(
        "Lead [Platform] (Core) Engineer",
        "lead engineer",
        "several segments, mixed kinds",
    )
    tk("()", "", "empty parentheses")
    tk("[ ]", "", "blank brackets")
    tk("((()))", "", "deeply nested empty parentheses")
    tk(
        "Manager (Engineer track)",
        "manager",
        "keyword inside brackets is invisible to matching",
    )
    tk(
        "Engineer\uff08Remote\uff09",
        "engineer remote",
        "fullwidth brackets are NOT removed (removal precedes NFKC); NFKC then separates",
    )
    tk(
        "Engineer (Remote\nUS) II",
        "engineer ii",
        "a bracketed segment may span a newline",
    )
    tk("Engineer (A) (B) [C] [D]", "engineer", "multiple adjacent segments")
    tk(
        "Staff Engineer - (Platform)",
        "staff engineer",
        "trailing parenthetical after a dash",
    )
    tk("(Remote) Engineer", "engineer", "leading parenthetical")
    tk(
        "Sr. Software Engineer, Backend (Remote, US)",
        "sr software engineer backend",
        "commas and periods",
    )
    tk("C++ Developer (Games)", "c developer", "symbols plus bracket removal")
    tk(
        "\u30a8\u30f3\u30b8\u30cb\u30a2\uff08\u30ea\u30e2\u30fc\u30c8\uff09",
        "\u30a8\u30f3\u30b8\u30cb\u30a2 \u30ea\u30e2\u30fc\u30c8",
        "CJK title with fullwidth parentheses survives",
    )
    tk("Engineer )(", "engineer", "reversed parentheses are not a segment")
    tk("", "", "empty title")

    # ---- location_key
    lk = lambda i, e, n: add("location_key", i, e, n)
    lk("New York, NY", "new ny york", "spec example")
    lk("NY - New York", "new ny york", "spec example: token order does not matter")
    lk(None, "", "null location is treated as empty")
    lk("", "", "empty location")
    lk("Remote", "remote", "single token")
    lk("NY NY New York", "new ny york", "duplicate tokens collapse")
    lk(
        "Z\u00fcrich, Switzerland",
        "switzerland z\u00fcrich",
        "'s' sorts before 'z-umlaut' by code point",
    )
    lk(
        "\u00e9cole zebra",
        "zebra \u00e9cole",
        "code point order puts e-acute (U+E9) AFTER z; locale collation would not",
    )
    lk("10 Downing St", "10 downing st", "digits sort before letters")
    lk(
        "\U00020000 \u2764\ufe0f",
        FE0F + " \U00020000",
        "U+FE0F (BMP) sorts BEFORE U+20000 (astral) by code point; UTF-16 unit order says the opposite",
    )
    lk(
        "Berlin, Germany; Munich, Germany",
        "berlin germany munich",
        "semicolon separates, duplicates collapse",
    )
    lk(
        "San Francisco Bay Area (Hybrid)",
        "area bay francisco hybrid san",
        "brackets are NOT removed in location_key",
    )
    lk("\uff2e\uff39", "ny", "fullwidth letters fold")
    lk("Remote - US / Canada", "canada remote us", "slash and dash separate")
    lk(
        "\u6771\u4eac \u65e5\u672c",
        "\u65e5\u672c \u6771\u4eac",
        "CJK tokens sort by code point (U+65E5 < U+6771)",
    )
    lk("a b A B", "a b", "case-folded duplicates collapse")
    lk(
        "\u00c5rhus, \u00d8stergade",
        "\u00e5rhus \u00f8stergade",
        "a-ring (U+E5) before o-slash (U+F8)",
    )
    lk("Remote (US)", "remote us", "parenthetical stays as tokens")

    # ---- token_sequence_match (title is already a title_key)
    ts = lambda t, p, e, n: add("token_sequence_match", {"title": t, "phrase": p}, e, n)
    ts("senior data engineer", "data engineer", True, "contiguous multi-token phrase")
    ts("data software engineer", "data engineer", False, "same tokens, not contiguous")
    ts(
        "engineering manager",
        "engineer",
        False,
        "token must match whole token, not a prefix",
    )
    ts("engineer", "engineer", True, "exact")
    ts("senior engineer", "Engineer", True, "phrase is normalized (case)")
    ts("senior engineer", "", False, "empty phrase never matches")
    ts("senior engineer", "!!!", False, "phrase that normalizes to empty never matches")
    ts("engineer", "senior engineer", False, "phrase longer than title")
    ts("c developer", "C++", True, "'C++' normalizes to token 'c'")
    ts("objective c developer", "C#", True, "'c' matches inside an unrelated title")
    ts("a b a b", "b a", True, "match found at an inner offset")
    ts("a b a b", "a a", False, "tokens exist but are not adjacent")
    ts("machine learning researcher", "machine learning", True, "two-token phrase")
    ts("learning machine operator", "machine learning", False, "order matters")
    ts("internal tools engineer", "intern", False, "'intern' must not match 'internal'")
    ts("engineer intern", "intern", True, "'intern' matches as a whole token")
    ts(
        "caf\u00e9 manager",
        "CAFE\u0301",
        True,
        "phrase NFKC-composes before comparison",
    )
    ts("stra\u00dfe lead", "STRASSE", False, "sharp s is not ss")
    ts("", "engineer", False, "empty title key")
    ts("", "", False, "both empty")
    ts(
        "lead engineer ii",
        "lead  ENGINEER",
        True,
        "internal whitespace and case in the phrase",
    )
    ts("front end engineer", "front-end", True, "hyphenated phrase becomes two tokens")
    ts(
        "frontend engineer",
        "front-end",
        False,
        "fused word does not match split phrase",
    )
    ts("sr software engineer", "Sr. Software", True, "punctuation in phrase")
    ts(
        "\u682a\u5f0f\u4f1a\u793e",
        "\u682a\u5f0f",
        False,
        "CJK token is whole-token matched",
    )
    ts(
        "engineer",
        "engineer engineer",
        False,
        "repeated phrase tokens need repeated title tokens",
    )

    # ---- sha12 (expected computed with hashlib directly)
    for s, n in (
        ("", "SHA-256 of the empty string starts e3b0c44298fc"),
        ("abc", "SHA-256 of 'abc' starts ba7816bf8f01"),
        ("acme", "company key as hashed for company_id"),
        ("Acme", "case-sensitive: differs from 'acme'"),
        ("acme|acme robotics", "candidate_id preimage uses '|'"),
        ("\u00e9", "precomposed e-acute: UTF-8 bytes C3 A9, no normalization"),
        (
            "e\u0301",
            "decomposed e-acute differs from the precomposed hash (sha12 does NOT normalize)",
        ),
        ("\U0001f680", "astral code point hashes its 4 UTF-8 bytes"),
        ("c_" + "acme", "prefix is not part of the digest"),
        ("a" * 1000, "long input"),
        ("\u682a\u5f0f\u4f1a\u793e", "CJK, 12 UTF-8 bytes"),
    ):
        add("sha12", s, hashlib.sha256(s.encode("utf-8")).hexdigest()[:12], n)
    return C


def build_normalization():
    cases = []
    counters = {}
    for fn, inp, expected, note in norm_cases():
        got = oracle.run_norm_case({"fn": fn, "input": inp})
        if got != expected:
            raise SystemExit(
                f"hand-written expectation disagrees with oracle: {fn}({inp!r}) "
                f"hand={expected!r} oracle={got!r}"
            )
        counters[fn] = counters.get(fn, 0) + 1
        cases.append(
            {
                "id": f"{fn}-{counters[fn]:03d}",
                "fn": fn,
                "input": inp,
                "expected": expected,
                "note": note,
            }
        )
    return {
        "format_version": 1,
        "kind": "normalization",
        "description": "Golden cases for the 01-normalization-and-identity functions. See README.md.",
        "cases": cases,
    }


# ============================================================ analysis vectors
VECTORS: list = []


def _p(
    kind,
    ref,
    pid,
    company,
    title,
    location=None,
    work_mode="unknown",
    department=None,
    url=None,
    posted_at=None,
):
    return {
        "source_kind": kind,
        "source_ref": ref,
        "source_posting_id": pid,
        "company_name": company,
        "title": title,
        "location": location,
        "work_mode": work_mode,
        "department": department,
        "url": url,
        "posted_at": posted_at,
    }


def src(kind, ref):
    """posting factory bound to one source."""

    def make(pid, company, title, location=None, **kw):
        return _p(kind, ref, pid, company, title, location, **kw)

    return make


def snap(sid, kind, ref, at, mode, postings):
    return {
        "snapshot_id": sid,
        "source_kind": kind,
        "source_ref": ref,
        "observed_at": at,
        "mode": mode,
        "postings": list(postings),
    }


def add(
    name, description, snapshots, include=(), exclude=(), decisions=(), as_of=AS_OF
):
    VECTORS.append(
        {
            "name": name,
            "description": description,
            "input": {
                "as_of": as_of,
                "profile": {
                    "include_keywords": list(include),
                    "exclude_keywords": list(exclude),
                },
                "decisions": [dict(d) for d in decisions],
                "snapshots": list(snapshots),
            },
        }
    )


def days(a, b):
    return oracle.days_between(oracle.epoch(a), oracle.epoch(b))


def url(host, *parts):
    return "https://" + host + ".example.test/" + "/".join(parts)


def define_vectors():
    VECTORS.clear()

    # 01 ------------------------------------------------------------------
    t = "2026-10-12T09:00:00Z"
    gh, cA, man, cB = (
        src("greenhouse", "acme"),
        src("csv", "list-a"),
        src("manual", "manual"),
        src("csv", "list-b"),
    )
    add(
        "name-variants-collapse",
        "Acme / ACME Inc. / acme, inc / The Acme Corporation spelled differently in four sources (all observed at the "
        "same instant) collapse to ONE company keyed 'acme'. The display name is the lexicographically smallest raw "
        "name by code point (uppercase 'ACME Inc.' < 'Acme' < 'The ...' < 'acme, inc'). The three 'Backend Engineer' "
        "observations (locations 'Austin, TX' / 'TX - Austin' / 'Austin TX') are one canonical role.",
        [
            snap(
                "s-gh",
                "greenhouse",
                "acme",
                t,
                "full",
                [
                    gh(
                        "1001",
                        "Acme",
                        "Backend Engineer",
                        "Austin, TX",
                        work_mode="hybrid",
                        department="Engineering",
                        url=url("boards", "acme", "1001"),
                    ),
                    gh(
                        "1002",
                        "Acme",
                        "Product Designer",
                        "Remote",
                        work_mode="remote",
                        department="Design",
                        url=url("boards", "acme", "1002"),
                    ),
                ],
            ),
            snap(
                "s-csv-a",
                "csv",
                "list-a",
                t,
                "additive",
                [cA(None, "ACME Inc.", "Backend Engineer", "TX - Austin")],
            ),
            snap(
                "s-man",
                "manual",
                "manual",
                t,
                "additive",
                [man(None, "acme, inc", "Backend Engineer", "Austin TX")],
            ),
            snap(
                "s-csv-b",
                "csv",
                "list-b",
                t,
                "additive",
                [cB(None, "The Acme Corporation", "Data Analyst", "Remote")],
            ),
        ],
    )

    # 02 ------------------------------------------------------------------
    old, z, k1, k2 = (
        src("csv", "older"),
        src("greenhouse", "zenith"),
        src("csv", "kappa-1"),
        src("csv", "kappa-2"),
    )
    add(
        "earliest-posting-names-company",
        "Display name is the raw name of the EARLIEST observed posting, not the smallest: 'Zenith Labs Inc' (csv, "
        "2026-09-01) beats the lexicographically smaller 'Zenith Labs' seen later. Separately 'KAPPA WORKS' and "
        "'Kappa Works' are observed at the same instant, so the tie goes to the smallest raw name by code point "
        "('KAPPA WORKS': 'A' < 'a').",
        [
            snap(
                "s1",
                "csv",
                "older",
                "2026-09-01T00:00:00Z",
                "additive",
                [old(None, "Zenith Labs Inc", "Optics Engineer", "Remote")],
            ),
            snap(
                "s2",
                "greenhouse",
                "zenith",
                "2026-09-20T00:00:00Z",
                "full",
                [
                    z("7", "Zenith Labs", "Optics Engineer", "Remote"),
                    z("8", "Zenith Labs", "Lab Manager", "Boston"),
                ],
            ),
            snap(
                "s3",
                "csv",
                "kappa-1",
                "2026-09-05T00:00:00Z",
                "additive",
                [k1(None, "Kappa Works", "Estimator", "Tulsa")],
            ),
            snap(
                "s4",
                "csv",
                "kappa-2",
                "2026-09-05T00:00:00Z",
                "additive",
                [k2(None, "KAPPA WORKS", "Foreman", "Tulsa")],
            ),
        ],
    )

    # 03 ------------------------------------------------------------------
    t = "2026-10-10T00:00:00Z"
    add(
        "merge-candidates-three-reasons",
        "One candidate of each kind, never auto-merged: 'DoorDash' vs 'Door Dash' (spacing_variant), "
        "'Blue Ocean Shipping Co' vs '... Group' (token_overlap at exactly 75%: 3 of 4 tokens) and 'Acme Robotics' "
        "vs 'Acme Robotic' (near_typo). Output order is by reason, then keys.",
        [
            snap(
                "s1",
                "greenhouse",
                "doordash",
                t,
                "full",
                [
                    src("greenhouse", "doordash")(
                        "1", "DoorDash", "Courier Operations Lead", "Remote"
                    )
                ],
            ),
            snap(
                "s2",
                "csv",
                "dd-list",
                t,
                "additive",
                [src("csv", "dd-list")(None, "Door Dash", "Data Scientist", "Remote")],
            ),
            snap(
                "s3",
                "lever",
                "blue-ocean",
                t,
                "full",
                [
                    src("lever", "blue-ocean")(
                        "L1", "Blue Ocean Shipping Co", "Port Planner", "Rotterdam"
                    )
                ],
            ),
            snap(
                "s4",
                "ashby",
                "blue-ocean-group",
                t,
                "full",
                [
                    src("ashby", "blue-ocean-group")(
                        "A1", "Blue Ocean Shipping Group", "Fleet Analyst", "Hamburg"
                    )
                ],
            ),
            snap(
                "s5",
                "greenhouse",
                "acme-robotics",
                t,
                "full",
                [
                    src("greenhouse", "acme-robotics")(
                        "1", "Acme Robotics", "Firmware Engineer", "Remote"
                    )
                ],
            ),
            snap(
                "s6",
                "csv",
                "acme-list",
                t,
                "additive",
                [
                    src("csv", "acme-list")(
                        None, "Acme Robotic", "Mechanical Engineer", "Remote"
                    )
                ],
            ),
        ],
    )

    # 04 ------------------------------------------------------------------
    def one(ref, name, title="Planner"):
        return snap(
            "s-" + ref,
            "csv",
            ref,
            t,
            "additive",
            [src("csv", ref)(None, name, title, "Remote")],
        )

    add(
        "candidate-reason-precedence",
        "When several candidate tests hold the FIRST in the order spacing_variant, token_overlap, near_typo is "
        "reported. Pair 1 is spacing_variant although it is also near_typo (distance 1) and 75% token overlap "
        "(9 of 12). Pair 2 is token_overlap (6 of 8 = 75%) although also near_typo. Pair 3 is token_overlap at "
        "7 of 9 (77.8%). Pair 4 ('Victor Whiskey' vs '... Yankee', 2 of 3 = 66.7%) is not a candidate.",
        [
            one("p1", "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota X Y"),
            one("p2", "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota XY"),
            one("q1", "Ab Cd Ef Gh Ij Kl Mn"),
            one("q2", "Ab Cd Ef Gh Ij Kl Mo"),
            one("d1", "Delta Echo Foxtrot Golf Hotel India Juliet Kilo"),
            one("d2", "Delta Echo Foxtrot Golf Hotel India Juliet Lima"),
            one("v1", "Victor Whiskey"),
            one("v2", "Victor Whiskey Yankee"),
        ],
    )

    # 05 ------------------------------------------------------------------
    K1 = "".join(chr(0x20000 + i) for i in range(6))
    K2 = K1[:5] + "\U00021006"
    K3 = "".join(chr(0x20010 + i) for i in range(5))
    K4 = K3[:4] + "\U00020015"
    add(
        "near-typo-boundaries",
        "near_typo needs BOTH keys >= 6 code points and Levenshtein <= 1. 'Nordic'/'Nordik' and 'Quantum'/'Quantom' "
        "qualify; 'Google'/'Gogle' (6 vs 5 code points), 'Hooli'/'Hoolie' (5 vs 6) do not; 'Initech'/'Intiech' is a "
        "transposition = distance 2 (Levenshtein, not Damerau). Astral CJK keys: six code points (12 UTF-16 units) "
        "differing in ONE code point qualify even though both surrogates differ; five code points (10 units) "
        "differing in one low surrogate do NOT qualify (length is counted in code points).",
        [
            one("n1", "Nordic"),
            one("n2", "Nordik"),
            one("g1", "Google"),
            one("g2", "Gogle"),
            one("u1", "Quantum"),
            one("u2", "Quantom"),
            one("i1", "Initech"),
            one("i2", "Intiech"),
            one("h1", "Hooli"),
            one("h2", "Hoolie"),
            one("k1", K1),
            one("k2", K2),
            one("k3", K3),
            one("k4", K4),
        ],
    )

    # 06 ------------------------------------------------------------------
    t = "2026-10-12T12:00:00Z"
    add(
        "candidate-code-point-order",
        "Two companies whose keys differ only in the last token: U+FE0F (variation selector, BMP) vs U+20000 "
        "(CJK ext. B, astral). By code point 'rocket <FE0F>' < 'rocket <20000>' so it is a_key; sorting by UTF-16 "
        "code units would reverse a_key/b_key, the candidate_id and the rank order (both companies score the same, "
        "so rank is decided by key).",
        [
            snap(
                "s1",
                "greenhouse",
                "rocket-a",
                t,
                "full",
                [
                    src("greenhouse", "rocket-a")(
                        "1", "Rocket \u2764\ufe0f", "Systems Engineer", "Remote"
                    )
                ],
            ),
            snap(
                "s2",
                "greenhouse",
                "rocket-b",
                t,
                "full",
                [
                    src("greenhouse", "rocket-b")(
                        "1", "Rocket \U00020000", "Systems Engineer", "Remote"
                    )
                ],
            ),
        ],
    )

    # 07 ------------------------------------------------------------------
    t = "2026-10-10T00:00:00Z"
    add(
        "not-same-hides-candidate",
        "A not_same decision on ('door dash','doordash') removes exactly that spacing_variant candidate; the "
        "unrelated near_typo candidate ('acme robotic','acme robotics') is still reported. A not_same decision "
        "between two non-candidates is harmless. The two companies are still two companies.",
        [
            one("a", "DoorDash"),
            one("b", "Door Dash"),
            one("c", "Acme Robotics"),
            one("d", "Acme Robotic"),
        ],
        decisions=[
            {"a_key": "door dash", "b_key": "doordash", "decision": "not_same"},
            {"a_key": "acme robotics", "b_key": "doordash", "decision": "not_same"},
        ],
    )

    # 08 ------------------------------------------------------------------
    dd, ddc = src("greenhouse", "doordash"), src("csv", "dd-sheet")
    add(
        "merge-decision-applies-to-history",
        "A user merge of 'door dash' and 'doordash' is applied retroactively: events from before the decision "
        "carry the merged company id, the canonical key is the smaller key ('door dash'), the display name is "
        "still the earliest posting's ('DoorDash'), and 'Courier Operations Lead' from both spellings dedups into "
        "one role with two observations. The csv import lists 'Data Scientist' under BOTH spellings: they have "
        "different source role keys (company_key is part of a null-id key), so after the merge they are two "
        "roles of one source and stay two canonical roles (a merge never collapses a source with itself). "
        "No candidate remains.",
        [
            snap(
                "s1",
                "greenhouse",
                "doordash",
                "2026-09-01T00:00:00Z",
                "full",
                [dd("10", "DoorDash", "Courier Operations Lead", "Remote")],
            ),
            snap(
                "s2",
                "csv",
                "dd-sheet",
                "2026-09-10T00:00:00Z",
                "additive",
                [
                    ddc(None, "Door Dash", "Courier Operations Lead", "Remote"),
                    ddc(None, "Door Dash", "Data Scientist", "San Francisco, CA"),
                    ddc(None, "DoorDash", "Data Scientist", "San Francisco, CA"),
                ],
            ),
            snap(
                "s3",
                "greenhouse",
                "doordash",
                "2026-09-20T00:00:00Z",
                "full",
                [
                    dd("10", "DoorDash", "Courier Operations Lead", "Remote"),
                    dd("11", "DoorDash", "Merchant Success Manager", "New York, NY"),
                ],
            ),
        ],
        decisions=[{"a_key": "door dash", "b_key": "doordash", "decision": "merge"}],
    )

    # 09 ------------------------------------------------------------------
    add(
        "merge-transitive-canonical-only-candidates",
        "merge('nova lab','nova labs') + merge('nova labs','novalabs') form one group (transitive) whose canonical "
        "key is the smallest member 'nova lab'. Candidates are computed between GROUP canonical keys only: the "
        "unmerged 'novalabz' is distance 1 from the non-canonical member 'novalabs' but distance 2 from the "
        "canonical 'nova lab', so no candidate is emitted.",
        [
            snap(
                "s1",
                "greenhouse",
                "nova",
                "2026-10-01T00:00:00Z",
                "full",
                [
                    src("greenhouse", "nova")(
                        "1", "Nova Labs", "Optics Engineer", "Remote"
                    )
                ],
            ),
            snap(
                "s2",
                "csv",
                "nova-sheet",
                "2026-10-02T00:00:00Z",
                "additive",
                [
                    src("csv", "nova-sheet")(
                        None, "NovaLabs", "Optics Engineer", "Remote"
                    )
                ],
            ),
            snap(
                "s3",
                "manual",
                "manual",
                "2026-10-03T00:00:00Z",
                "additive",
                [src("manual", "manual")(None, "Nova Lab", "Lab Technician", "Remote")],
            ),
            snap(
                "s4",
                "lever",
                "novalabz",
                "2026-10-04T00:00:00Z",
                "full",
                [src("lever", "novalabz")("z1", "NovaLabz", "Glass Blower", "Remote")],
            ),
        ],
        decisions=[
            {"a_key": "nova lab", "b_key": "nova labs", "decision": "merge"},
            {"a_key": "nova labs", "b_key": "novalabs", "decision": "merge"},
        ],
    )

    # 10 ------------------------------------------------------------------
    h = src("greenhouse", "support-house")
    add(
        "headcounts-two-roles-same-source",
        "Two postings with identical title and location but different posting ids inside ONE source stay two "
        "roles (two headcount); a third in another city is a third role. Their role_ids differ by the group "
        "index.",
        [
            snap(
                "s1",
                "greenhouse",
                "support-house",
                "2026-10-09T12:00:00Z",
                "full",
                [
                    h("201", "Support House Ltd", "Support Engineer", "Berlin"),
                    h("202", "Support House Ltd", "Support Engineer", "Berlin"),
                    h("203", "Support House Ltd", "Support Engineer", "Munich"),
                ],
            )
        ],
        include=["engineer"],
    )

    # 11 ------------------------------------------------------------------
    c = src("csv", "jobs-export")
    add(
        "csv-null-id-rows-collapse",
        "CSV rows without posting ids are identified by (company_key, title_key, location_key): 'New York, NY' and "
        "'NY - New York' rows are the SAME source role (last row wins). The same rows WITH ids ('A-1','A-2') stay "
        "two roles. A later import re-lists the collapsed role with another raw location spelling and a new "
        "department, which is a `changed` event for fields ['department','location'] because tracked fields "
        "compare raw values.",
        [
            snap(
                "i1",
                "csv",
                "jobs-export",
                "2026-10-08T00:00:00Z",
                "additive",
                [
                    c(
                        None,
                        "Acme",
                        "Support Engineer",
                        "New York, NY",
                        department="Support",
                        url=url("jobs", "1"),
                    ),
                    c(
                        None,
                        "Acme",
                        "Support Engineer",
                        "NY - New York",
                        department="Customer Success",
                        url=url("jobs", "2"),
                    ),
                    c(None, "Acme", "Support Engineer", "Remote"),
                    c("A-1", "Acme", "Account Executive", "Remote"),
                    c("A-2", "Acme", "Account Executive", "Remote"),
                ],
            ),
            snap(
                "i2",
                "csv",
                "jobs-export",
                "2026-10-10T00:00:00Z",
                "additive",
                [
                    c(
                        None,
                        "Acme",
                        "Support Engineer",
                        "NY, New York",
                        department="Support Ops",
                        url=url("jobs", "2"),
                    )
                ],
            ),
        ],
    )

    # 12 ------------------------------------------------------------------
    t1, t2, t3 = "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z", "2026-10-03T00:00:00Z"
    g, cs, m = src("greenhouse", "acme"), src("csv", "sheet"), src("manual", "manual")
    add(
        "cross-source-corroboration",
        "One real opening seen by several sources is ONE canonical role. 'Staff Engineer' (greenhouse 1000 + csv "
        "600) is corroborated but capped at 1000; 'Sales Lead' (csv 600 + manual 400) is corroborated to 700 "
        "(best 600 + 100); 'QA Engineer' (greenhouse only) 1000; 'Ops Coordinator' (manual only) 400.",
        [
            snap(
                "s1",
                "greenhouse",
                "acme",
                t1,
                "full",
                [
                    g(
                        "11",
                        "Acme",
                        "Staff Engineer",
                        "Remote",
                        url=url("boards", "11"),
                    ),
                    g("12", "Acme", "QA Engineer", "Remote", url=url("boards", "12")),
                ],
            ),
            snap(
                "s2",
                "csv",
                "sheet",
                t2,
                "additive",
                [
                    cs(None, "Acme", "Staff Engineer", "Remote"),
                    cs(None, "Acme", "Sales Lead", "Boston"),
                ],
            ),
            snap(
                "s3",
                "manual",
                "manual",
                t3,
                "additive",
                [
                    m(None, "Acme", "Sales Lead", "Boston"),
                    m(None, "Acme", "Ops Coordinator", "Boston"),
                ],
            ),
        ],
    )

    # 13 ------------------------------------------------------------------
    g, cs = src("greenhouse", "acme"), src("csv", "sheet")
    add(
        "corroboration-needs-two-active-observations",
        "A role listed by greenhouse and csv is corroborated only while BOTH observations are active. After a "
        "later full greenhouse snapshot drops 'Data Engineer', the canonical role stays active through its csv "
        "observation but has one active observation: confidence 600 and not corroborated. 'Platform Engineer' "
        "keeps both. The dropped role still produces a `removed` event inside the 30-day window.",
        [
            snap(
                "s1",
                "greenhouse",
                "acme",
                "2026-09-20T00:00:00Z",
                "full",
                [
                    g("5", "Acme", "Data Engineer", "Remote"),
                    g("6", "Acme", "Platform Engineer", "Remote"),
                ],
            ),
            snap(
                "s2",
                "csv",
                "sheet",
                "2026-09-21T00:00:00Z",
                "additive",
                [
                    cs(None, "Acme", "Data Engineer", "Remote"),
                    cs(None, "Acme", "Platform Engineer", "Remote"),
                ],
            ),
            snap(
                "s3",
                "greenhouse",
                "acme",
                "2026-10-05T00:00:00Z",
                "full",
                [g("6", "Acme", "Platform Engineer", "Remote")],
            ),
        ],
        include=["engineer"],
    )

    # 14 ------------------------------------------------------------------
    g = src("greenhouse", "acme")
    add(
        "rename-and-field-changes",
        "Same posting id, different values: a rename is a `changed` event (not remove+add) and its `fields` is "
        "the sorted list of tracked fields that differ. Role 1 changes ONLY its title => ['title']; role 2 "
        "department+url; role 3 gains a posted_at; role 4 changes title+location+work_mode (sorted: "
        "location, title, work_mode). The canonical role_id follows the NEW title_key, and events carry "
        "that final id.",
        [
            snap(
                "s1",
                "greenhouse",
                "acme",
                "2026-09-01T00:00:00Z",
                "full",
                [
                    g(
                        "1",
                        "Acme",
                        "Backend Engineer",
                        "Remote",
                        department="Engineering",
                        url=url("boards", "1"),
                    ),
                    g(
                        "2",
                        "Acme",
                        "Product Designer",
                        "London",
                        work_mode="onsite",
                        department="Design",
                        url=url("boards", "2"),
                        posted_at="2026-08-20",
                    ),
                    g(
                        "3",
                        "Acme",
                        "Data Analyst",
                        "Paris",
                        work_mode="hybrid",
                        department="Data",
                        url=url("boards", "3"),
                    ),
                    g(
                        "4",
                        "Acme",
                        "Office Manager",
                        "Leeds",
                        department="Operations",
                        url=url("boards", "4"),
                    ),
                ],
            ),
            snap(
                "s2",
                "greenhouse",
                "acme",
                "2026-09-20T00:00:00Z",
                "full",
                [
                    g(
                        "1",
                        "Acme",
                        "Senior Backend Engineer",
                        "Remote",
                        department="Engineering",
                        url=url("boards", "1"),
                    ),
                    g(
                        "2",
                        "Acme",
                        "Product Designer",
                        "London",
                        work_mode="onsite",
                        department="Product Design",
                        url=url("boards", "2", "v2"),
                        posted_at="2026-08-20",
                    ),
                    g(
                        "3",
                        "Acme",
                        "Data Analyst",
                        "Paris",
                        work_mode="hybrid",
                        department="Data",
                        url=url("boards", "3"),
                        posted_at="2026-08-25",
                    ),
                    g(
                        "4",
                        "Acme",
                        "Facilities Manager",
                        "Leeds - Hybrid",
                        work_mode="hybrid",
                        department="Operations",
                        url=url("boards", "4"),
                    ),
                ],
            ),
        ],
    )

    # 15 ------------------------------------------------------------------
    g = src("greenhouse", "acme")
    be, fe = (
        ("1", "Acme", "Backend Engineer", "Remote"),
        ("2", "Acme", "Frontend Engineer", "Remote"),
    )
    add(
        "removal-then-reappearance",
        "Full snapshots: role 2 is removed, comes back (`reappeared`, first_seen preserved, removed_at cleared) "
        "and is removed again. It ends removed with last_seen at its last listing, not at removal time. "
        "Only the reappearance and the second removal fall inside the 30-day change window: net 0.",
        [
            snap(
                "s1",
                "greenhouse",
                "acme",
                "2026-09-01T00:00:00Z",
                "full",
                [g(*be), g(*fe)],
            ),
            snap("s2", "greenhouse", "acme", "2026-09-10T00:00:00Z", "full", [g(*be)]),
            snap(
                "s3",
                "greenhouse",
                "acme",
                "2026-09-20T00:00:00Z",
                "full",
                [g(*be), g(*fe)],
            ),
            snap("s4", "greenhouse", "acme", "2026-10-01T00:00:00Z", "full", [g(*be)]),
        ],
    )

    # 16 ------------------------------------------------------------------
    cl, g = src("csv", "list"), src("greenhouse", "acme")
    a_row = (None, "Acme", "Forklift Operator", "Boston, MA")
    add(
        "additive-snapshot-never-removes",
        "An additive (import) snapshot that omits roles removes nothing: B and C stay active with their old "
        "last_seen while A is refreshed (raw location/url changed => `changed` ['location','url']). In the same "
        "company a FULL greenhouse snapshot that omits its role does remove it.",
        [
            snap(
                "s0",
                "greenhouse",
                "acme",
                "2026-08-15T00:00:00Z",
                "full",
                [g("D1", "Acme", "Warehouse Lead", "Boston")],
            ),
            snap(
                "s1",
                "csv",
                "list",
                "2026-09-01T00:00:00Z",
                "additive",
                [
                    cl(*a_row, department="Warehouse", url=url("sheet", "a")),
                    cl(None, "Acme", "Packer", "Boston, MA"),
                    cl(None, "Acme", "Shift Supervisor", "Cambridge, MA"),
                ],
            ),
            snap(
                "s2",
                "csv",
                "list",
                "2026-09-15T00:00:00Z",
                "additive",
                [
                    cl(
                        None,
                        "Acme",
                        "Forklift Operator",
                        "MA - Boston",
                        department="Warehouse",
                        url=url("sheet", "a2"),
                    )
                ],
            ),
            snap("s3", "greenhouse", "acme", "2026-09-30T00:00:00Z", "full", []),
        ],
    )

    # 17 ------------------------------------------------------------------
    g, lv = src("greenhouse", "acme"), src("lever", "acme")
    add(
        "baseline-vs-added",
        "The first snapshot of EACH source is its baseline: lever's first snapshot (2026-09-20) produces "
        "`baseline` events even though greenhouse history already exists, and baselines never count in the "
        "change score. Only greenhouse's later 'Data Analyst' is `added`, so change = 600. The lever "
        "'Backend Engineer' corroborates the greenhouse role.",
        [
            snap(
                "s1",
                "greenhouse",
                "acme",
                "2026-09-01T00:00:00Z",
                "full",
                [
                    g("1", "Acme", "Backend Engineer", "Remote"),
                    g("2", "Acme", "Product Designer", "Remote"),
                ],
            ),
            snap(
                "s2",
                "greenhouse",
                "acme",
                "2026-09-15T00:00:00Z",
                "full",
                [
                    g("1", "Acme", "Backend Engineer", "Remote"),
                    g("2", "Acme", "Product Designer", "Remote"),
                    g("3", "Acme", "Data Analyst", "Remote"),
                ],
            ),
            snap(
                "s3",
                "lever",
                "acme",
                "2026-09-20T00:00:00Z",
                "full",
                [
                    lv("L1", "Acme", "Backend Engineer", "Remote"),
                    lv("L2", "Acme", "Sales Lead", "Boston"),
                ],
            ),
        ],
    )

    # 18 ------------------------------------------------------------------
    x, y = src("greenhouse", "xray"), src("greenhouse", "yankee")
    for a_, b_, want in (
        ("2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z", 14),
        ("2026-09-01T00:00:00Z", "2026-09-14T23:59:59Z", 13),
    ):
        assert days(a_, b_) == want
    add(
        "change-span-14-vs-13",
        "History needs a span of at least 14 whole days between the first and last full snapshot of the "
        "company's sources. 'Xray Xylem': 2026-09-01T00:00:00Z -> 2026-09-15T00:00:00Z = 14 days: change is "
        "computed (+1 => 600). 'Yankee Yards': 2026-09-01T00:00:00Z -> 2026-09-14T23:59:59Z = 13 days 23:59:59 "
        "= 13: insufficient_history with span_days 13.",
        [
            snap(
                "x1",
                "greenhouse",
                "xray",
                "2026-09-01T00:00:00Z",
                "full",
                [x("1", "Xray Xylem", "Engineer", "Remote")],
            ),
            snap(
                "x2",
                "greenhouse",
                "xray",
                "2026-09-15T00:00:00Z",
                "full",
                [
                    x("1", "Xray Xylem", "Engineer", "Remote"),
                    x("2", "Xray Xylem", "Designer", "Remote"),
                ],
            ),
            snap(
                "y1",
                "greenhouse",
                "yankee",
                "2026-09-01T00:00:00Z",
                "full",
                [y("1", "Yankee Yards", "Engineer", "Remote")],
            ),
            snap(
                "y2",
                "greenhouse",
                "yankee",
                "2026-09-14T23:59:59Z",
                "full",
                [
                    y("1", "Yankee Yards", "Engineer", "Remote"),
                    y("2", "Yankee Yards", "Designer", "Remote"),
                ],
            ),
        ],
    )

    # 19 ------------------------------------------------------------------
    mr = src("greenhouse", "marsh")
    ids = {
        1: "Engineer One",
        2: "Engineer Two",
        3: "Engineer Three",
        4: "Engineer Four",
        5: "Engineer Five",
    }

    def mk(*nums):
        return [mr(str(n), "Marsh", ids[n], "Remote") for n in nums]

    add(
        "change-window-30d-edges",
        "as_of is 2026-10-13T12:00:00Z so the window is (2026-09-13T12:00:00Z, as_of]. The 'added' event at "
        "exactly 2026-09-13T12:00:00Z is OUT (strict >), the one one second later is IN, and the `removed` "
        "event at exactly as_of is IN: added 1, removed 1, net 0 => 500. A snapshot observed AT as_of is "
        "processed (only observed_at > as_of is ignored). Span is 54 days (>= 45) so first_seen ages feed "
        "urgency: two roles first seen 2026-08-20 are 54 days old (aged), the two new ones are not.",
        [
            snap(
                "s1", "greenhouse", "marsh", "2026-08-20T00:00:00Z", "full", mk(1, 2, 3)
            ),
            snap(
                "s2",
                "greenhouse",
                "marsh",
                "2026-09-13T12:00:00Z",
                "full",
                mk(1, 2, 3, 4),
            ),
            snap(
                "s3",
                "greenhouse",
                "marsh",
                "2026-09-13T12:00:01Z",
                "full",
                mk(1, 2, 3, 4, 5),
            ),
            snap(
                "s4",
                "greenhouse",
                "marsh",
                "2026-10-13T12:00:00Z",
                "full",
                mk(1, 2, 4, 5),
            ),
        ],
    )

    # 20 ------------------------------------------------------------------
    g = src("greenhouse", "acme")
    r = lambda i, title: g(str(i), "Acme", title, "Remote")
    add(
        "change-title-scope-filter",
        "With keywords configured only events whose title (AT EVENT TIME) matches an include keyword and no "
        "exclude keyword count. 'Backend Engineer' added (+1) and 'Engineer Two' removed (-1) count; "
        "'Marketing Lead' added, 'Engineer Intern' added/removed (exclude wins) and role 1 removed under its NEW "
        "title 'Designer' do not. 'Staff Engineer' is added in scope (+1) and renamed afterwards to 'Staff "
        "Designer': the event keeps the title it had at event time, so it still counts. Net +1 => 600. "
        "Unfiltered it would be added 4 / removed 4.",
        [
            snap(
                "s1",
                "greenhouse",
                "acme",
                "2026-08-01T00:00:00Z",
                "full",
                [
                    r(1, "Engineer"),
                    r(2, "Designer"),
                    r(3, "Engineer Intern"),
                    r(4, "Engineer Two"),
                ],
            ),
            snap(
                "s2",
                "greenhouse",
                "acme",
                "2026-09-20T00:00:00Z",
                "full",
                [
                    r(1, "Designer"),
                    r(2, "Designer"),
                    r(3, "Engineer Intern"),
                    r(4, "Engineer Two"),
                    r(5, "Backend Engineer"),
                    r(6, "Marketing Lead"),
                    r(7, "Engineer Intern"),
                    r(8, "Staff Engineer"),
                ],
            ),
            snap(
                "s3",
                "greenhouse",
                "acme",
                "2026-10-01T00:00:00Z",
                "full",
                [
                    r(5, "Backend Engineer"),
                    r(6, "Marketing Lead"),
                    r(7, "Engineer Intern"),
                    r(8, "Staff Designer"),
                ],
            ),
        ],
        include=["engineer"],
        exclude=["intern"],
    )

    # 21 ------------------------------------------------------------------
    tn = src("greenhouse", "tern")
    for p_, want in (("2026-08-29", 45), ("2026-08-30", 44)):
        assert days(p_ + "T00:00:00Z", "2026-10-13T00:00:00Z") == want
    add(
        "urgency-44-vs-45",
        "as_of is exactly midnight so ages are exact: posted_at 2026-08-30 is 44 days (NOT aged), 2026-08-29 is "
        "45 days (aged, threshold is >=). aged 1 of known 2 => 500.",
        [
            snap(
                "s1",
                "greenhouse",
                "tern",
                "2026-10-12T00:00:00Z",
                "full",
                [
                    tn(
                        "1",
                        "Tern Analytics",
                        "Platform Engineer",
                        "Remote",
                        posted_at="2026-08-29",
                    ),
                    tn(
                        "2",
                        "Tern Analytics",
                        "Data Engineer",
                        "Remote",
                        posted_at="2026-08-30",
                    ),
                ],
            )
        ],
        include=["engineer"],
        as_of="2026-10-13T00:00:00Z",
    )

    # 22 ------------------------------------------------------------------
    pi, qu, ra = (
        src("greenhouse", "pine"),
        src("greenhouse", "quartz"),
        src("greenhouse", "raven"),
    )
    assert days("2026-08-01T00:00:00Z", "2026-09-15T00:00:00Z") == 45
    assert days("2026-08-01T00:00:00Z", "2026-09-14T23:59:59Z") == 44
    add(
        "urgency-posted-at-vs-first-seen-span-rule",
        "A role with no posted_at is aged by first_seen ONLY when the company's full-snapshot span is >= 45 "
        "days. 'Pine Harbor' spans exactly 45 days: its undated role (first seen 73 days ago) counts as aged, a "
        "role with a recent posted_at (a re-listed posting) wins over its old first_seen (12 days), a new role "
        "is 28 days. 'Quartz "
        "Mill' spans 44d 23:59:59 = 44: its undated role is unknown (excluded from `known`), its dated one is "
        "aged. 'Raven Press' has a single snapshot: no span, no dated roles => no_dated_roles.",
        [
            snap(
                "p1",
                "greenhouse",
                "pine",
                "2026-08-01T00:00:00Z",
                "full",
                [
                    pi("1", "Pine Harbor", "Engineer A", "Remote"),
                    pi(
                        "2",
                        "Pine Harbor",
                        "Engineer B",
                        "Remote",
                        posted_at="2026-10-01",
                    ),
                ],
            ),
            snap(
                "p2",
                "greenhouse",
                "pine",
                "2026-09-15T00:00:00Z",
                "full",
                [
                    pi("1", "Pine Harbor", "Engineer A", "Remote"),
                    pi(
                        "2",
                        "Pine Harbor",
                        "Engineer B",
                        "Remote",
                        posted_at="2026-10-01",
                    ),
                    pi("3", "Pine Harbor", "Engineer C", "Remote"),
                ],
            ),
            snap(
                "q1",
                "greenhouse",
                "quartz",
                "2026-08-01T00:00:00Z",
                "full",
                [
                    qu(
                        "1",
                        "Quartz Mill",
                        "Engineer A",
                        "Remote",
                        posted_at="2026-08-01",
                    ),
                    qu("2", "Quartz Mill", "Engineer B", "Remote"),
                ],
            ),
            snap(
                "q2",
                "greenhouse",
                "quartz",
                "2026-09-14T23:59:59Z",
                "full",
                [
                    qu(
                        "1",
                        "Quartz Mill",
                        "Engineer A",
                        "Remote",
                        posted_at="2026-08-01",
                    ),
                    qu("2", "Quartz Mill", "Engineer B", "Remote"),
                ],
            ),
            snap(
                "r1",
                "greenhouse",
                "raven",
                "2026-10-01T00:00:00Z",
                "full",
                [ra("1", "Raven Press", "Engineer A", "Remote")],
            ),
        ],
    )

    # 23 ------------------------------------------------------------------
    fresh = [
        ("Amberly", "2026-10-13T12:00:00Z", 0),
        ("Birchwood", "2026-10-06T12:00:00Z", 7),
        ("Cedarville", "2026-10-05T12:00:01Z", 7),
        ("Dahlia Works", "2026-10-05T12:00:00Z", 8),
        ("Elmstead", "2026-08-15T12:00:00Z", 59),
        ("Fjordhaven", "2026-08-14T12:00:01Z", 59),
        ("Granite Quay", "2026-08-14T12:00:00Z", 60),
        ("Hollowell", "2026-08-13T12:00:00Z", 61),
        ("Ivywood", "2025-09-08T12:00:00Z", 400),
    ]
    snaps = []
    for name, at, want in fresh:
        assert days(at, AS_OF) == want, (name, at)
        ref = "fresh-" + name.split()[0].lower()
        snaps.append(
            snap(
                "f-" + ref,
                "greenhouse",
                ref,
                at,
                "full",
                [src("greenhouse", ref)("1", name, "Operations Analyst", "Remote")],
            )
        )
    add(
        "freshness-boundaries",
        "Nine single-role companies whose only snapshot is 0, 7, 7d23:59:59, 8, 59, 59d23:59:59, 60, 61 and "
        "400 days before as_of. Freshness is 1000 for d<=7 (7d23:59:59 floors to 7), rhu(1000*(60-d),53) in "
        "between (d=8 -> 981, d=59 -> 19) and 0 at d>=60: the formula itself is continuous at 7 and 60, so "
        "d=61 and d=400 are there to catch an implementation that applies it (negative!) or forgets the clamp. "
        "The first three tie on score, as do the last three; ties are ordered by key.",
        snaps,
    )

    # 24 ------------------------------------------------------------------
    cs, mn = src("csv", "leads"), src("manual", "manual")
    add(
        "no-keywords-partial-coverage",
        "No keywords: role_relevance is null (no_keywords), scope = all active roles. CSV/manual data has no "
        "full snapshot so change is insufficient_history. Urgency uses only the dated roles (aged 1 of known 2 "
        "=> 500; the undated manual role is unknown). Coverage is 55.",
        [
            snap(
                "s1",
                "csv",
                "leads",
                "2026-10-03T00:00:00Z",
                "additive",
                [
                    cs(
                        None,
                        "Hollis & Pike",
                        "Welder",
                        "Dallas",
                        posted_at="2026-08-20",
                    ),
                    cs(
                        None,
                        "Hollis & Pike",
                        "Fitter",
                        "Dallas",
                        posted_at="2026-10-01",
                    ),
                ],
            ),
            snap(
                "s2",
                "manual",
                "manual",
                "2026-10-04T00:00:00Z",
                "additive",
                [mn(None, "Hollis & Pike", "Estimator", "Dallas")],
            ),
        ],
    )

    # 25 ------------------------------------------------------------------
    ke = src("greenhouse", "kestrel")
    titles = [
        "Senior Engineer",
        "Engineering Manager",
        "Engineer Intern",
        "Internal Tools Engineer",
        "Manager (Engineer track)",
        "Machine Learning Researcher",
        "Learning Machine Operator",
        "Machine Vision & Learning Lead",
    ]
    add(
        "keyword-token-sequence-and-exclude",
        "Keywords match whole-token contiguous sequences of the title_key: 'engineer' matches 'Senior Engineer' "
        "and 'Internal Tools Engineer' but not 'Engineering Manager' or 'Manager (Engineer track)' (bracketed "
        "text is removed first); exclude 'intern' removes 'Engineer Intern' yet does NOT match 'Internal'; the "
        "two-token keyword 'machine learning' matches only the adjacent, ordered title. 3 of 8 relevant.",
        [
            snap(
                "s1",
                "greenhouse",
                "kestrel",
                "2026-10-11T12:00:00Z",
                "full",
                [
                    ke(str(i + 1), "Kestrel Inc", t_, "Remote")
                    for i, t_ in enumerate(titles)
                ],
            )
        ],
        include=["engineer", "machine learning"],
        exclude=["intern"],
    )

    # 26 ------------------------------------------------------------------
    pl = src("greenhouse", "plum")
    add(
        "no-scope-roles",
        "Keywords are configured but no active role matches: scope is empty, so role_relevance=0 and volume=0 "
        "are real zeros (counted in coverage) while urgency and source_confidence are null with "
        "no_scope_roles and their other inputs are the empty-set counts. Change is still computed (span 15): "
        "baselines only => 500.",
        [
            snap(
                "s1",
                "greenhouse",
                "plum",
                "2026-09-20T00:00:00Z",
                "full",
                [
                    pl("1", "Plum Row", "Marketing Manager", "Remote"),
                    pl("2", "Plum Row", "Sales Lead", "Boston"),
                ],
            ),
            snap(
                "s2",
                "greenhouse",
                "plum",
                "2026-10-05T00:00:00Z",
                "full",
                [
                    pl("1", "Plum Row", "Marketing Manager", "Remote"),
                    pl("2", "Plum Row", "Sales Lead", "Boston"),
                ],
            ),
        ],
        include=["engineer"],
    )

    # 27 ------------------------------------------------------------------
    g, lv = src("greenhouse", "acme"), src("lever", "zeta")
    add(
        "snapshots-after-as-of-ignored",
        "Snapshots with observed_at > as_of vanish completely: the 2026-10-13T12:00:01Z full snapshot that "
        "would remove 'Designer' is ignored (one second late), a snapshot observed exactly AT as_of is "
        "processed, and a company that appears only in a future snapshot does not exist. stats count only "
        "processed snapshots and postings.",
        [
            snap(
                "s-late",
                "greenhouse",
                "acme",
                "2026-10-13T12:00:01Z",
                "full",
                [g("1", "Acme", "Engineer", "Remote")],
            ),
            snap(
                "s-past",
                "greenhouse",
                "acme",
                "2026-09-01T00:00:00Z",
                "full",
                [g("1", "Acme", "Engineer", "Remote")],
            ),
            snap(
                "s-now",
                "greenhouse",
                "acme",
                "2026-10-13T12:00:00Z",
                "full",
                [
                    g("1", "Acme", "Engineer", "Remote"),
                    g("2", "Acme", "Designer", "Remote"),
                ],
            ),
            snap(
                "s-future",
                "lever",
                "zeta",
                "2026-11-01T00:00:00Z",
                "full",
                [lv("z", "Zeta Works", "Welder", "Remote")],
            ),
        ],
    )

    # 28 ------------------------------------------------------------------
    g = src("greenhouse", "acme")
    add(
        "duplicate-keys-last-wins",
        "Inside one snapshot a repeated source role key is replaced by its LAST occurrence and produces no "
        "event of its own (role 'a' ends with title 'Engineer v2', department 'New'); events are emitted in "
        "order of each key's last occurrence (b, a, n1). postings_observed still counts all 5 listed postings.",
        [
            snap(
                "s1",
                "greenhouse",
                "acme",
                "2026-10-10T00:00:00Z",
                "full",
                [
                    g(
                        "a",
                        "Acme",
                        "Engineer v1",
                        "Remote",
                        department="Old",
                        url=url("boards", "a1"),
                    ),
                    g("b", "Acme", "Designer", "Remote"),
                    g(
                        "a",
                        "Acme",
                        "Engineer v2",
                        "Remote",
                        department="New",
                        url=url("boards", "a2"),
                    ),
                    _p("greenhouse", "acme", "n1", "Acme", "Office Manager", "Remote"),
                    _p(
                        "greenhouse",
                        "acme",
                        "n1",
                        "Acme",
                        "Office Manager",
                        "Remote",
                        department="Facilities",
                    ),
                ],
            )
        ],
    )

    # 29 ------------------------------------------------------------------
    gk, lo = src("greenhouse", "ghost"), src("greenhouse", "liveoak")
    add(
        "all-roles-removed",
        "A company whose every role has been removed has no active roles: all six components are null with "
        "no_active_roles, score null, coverage 0, rank null, last_seen null, and it sorts AFTER ranked "
        "companies. change.inputs.span_days is still computed (19) because the source has two full snapshots. "
        "The roles are listed in the order 2, 1; the empty full snapshot removes them in ascending source "
        "role key order (1, 2), not in listing order.",
        [
            snap(
                "g1",
                "greenhouse",
                "ghost",
                "2026-09-01T00:00:00Z",
                "full",
                [
                    gk("2", "Ghost Kitchen Co", "Dishwasher", "Remote"),
                    gk("1", "Ghost Kitchen Co", "Chef", "Remote"),
                ],
            ),
            snap("g2", "greenhouse", "ghost", "2026-09-20T00:00:00Z", "full", []),
            snap(
                "l1",
                "greenhouse",
                "liveoak",
                "2026-10-10T00:00:00Z",
                "full",
                [lo("1", "Live Oak", "Arborist", "Remote")],
            ),
        ],
    )

    # 30 ------------------------------------------------------------------
    t = "2026-10-12T12:00:00Z"
    names = [
        "Zebra Works",
        "alpha works",
        "\u00c9mile Works",
        "\u03a9mega Works",
        "7 Seas",
    ]
    snaps = []
    for n_ in names:
        ref = "tie-" + str(names.index(n_))
        snaps.append(
            snap(
                "t-" + ref,
                "greenhouse",
                ref,
                t,
                "full",
                [src("greenhouse", ref)("1", n_, "Operations Analyst", "Remote")],
            )
        )
    add(
        "score-ties-order-by-key",
        "Five identical companies score 689 each; rank is decided by KEY ascending BY CODE POINT (not by display "
        "name: 'Zebra Works' sorts before 'alpha works' as a name but not as a key): '7 seas' < "
        "'alpha works' < 'zebra works' < '<e-acute>mile works' (U+E9) < '<omega>mega works' (U+3C9). A "
        "locale-aware or case-insensitive sort would put the accented name between alpha and zebra.",
        snaps,
    )

    # 31 ------------------------------------------------------------------
    add(
        "empty-snapshots",
        "No snapshots at all: every collection is empty and every stat is 0.",
        [],
        include=["engineer"],
        exclude=["intern"],
    )

    # 32 ------------------------------------------------------------------
    t = "2026-10-12T00:00:00Z"
    FW = "\uff32\uff4f\uff43\uff4b\uff45\uff54\u3000\uff2c\uff41\uff42\uff53"  # fullwidth "Rocket Labs"
    EMO = "\U0001f680 Rocket Labs \U0001f680"

    def solo(ref, name, kind="greenhouse", mode="full", at=t):
        return snap(
            "u-" + ref,
            kind,
            ref,
            at,
            mode,
            [
                src(kind, ref)(
                    "1" if kind != "csv" else None, name, "Operations Analyst", "Remote"
                )
            ],
        )

    add(
        "unicode-company-names",
        "Names that differ in script, width, composition and case. Fullwidth 'Rocket Labs', '<rocket> Rocket "
        "Labs <rocket>' and plain 'Rocket Labs' are one company; its name is the earliest posting, and the tie "
        "between the fullwidth and emoji spellings goes to the smaller CODE POINT (U+FF32 < U+1F680; UTF-16 "
        "order would pick the emoji). Aliases sort by code point. 'Stra\u00dfe GmbH' (sharp s) and 'STRASSE GmbH' "
        "are different companies; Turkish dotted capital I and ASCII I are different; decomposed accents "
        "compose; CJK/Cyrillic keys are kept; fullwidth 'Acme Inc.' joins 'Acme'.",
        [
            solo("rl-1", FW, "csv", "additive"),
            solo("rl-2", EMO, "csv", "additive"),
            solo("rl-3", "Rocket Labs", "greenhouse", "full", "2026-10-12T06:00:00Z"),
            solo("strasse-1", "Stra\u00dfe GmbH"),
            solo("strasse-2", "STRASSE GmbH"),
            solo("istanbul", "\u0130stanbul Yaz\u0131l\u0131m A.\u015e."),
            solo("istanbul-ascii", "Istanbul Yazilim A.S."),
            solo(
                "jp-1", "\u682a\u5f0f\u4f1a\u793e\u30a2\u30af\u30e1", "csv", "additive"
            ),
            solo(
                "jp-2",
                "\u30a2\u30af\u30e1\u3000\u682a\u5f0f\u4f1a\u793e",
                "csv",
                "additive",
            ),
            solo("ru", "\u0420\u043e\u043c\u0430\u0448\u043a\u0430 \u041e\u041e\u041e"),
            solo("zoe", "Zoe\u0301's Cafe\u0301 & Co."),
            solo("acme-fw", "\uff21\uff43\uff4d\uff45\u3000\uff29\uff4e\uff43\uff0e"),
            solo("acme", "Acme", "csv", "additive"),
        ],
    )

    # 33 ------------------------------------------------------------------
    og, ol, oa = (
        src("greenhouse", "orbit"),
        src("lever", "orbit"),
        src("ashby", "orbit"),
    )
    oc, om = src("csv", "orbit-leads"), src("manual", "manual")
    N = "Orbit Systems"
    add(
        "many-sources-one-company",
        "All five source kinds feed one company. 'Systems Engineer' has 5 observations (still one role, "
        "corroborated, 1000); 'Account Executive' joins lever + csv despite 'Chicago, IL' / 'IL - Chicago'; "
        "'Site Reliability Engineer' is ashby-only; 'Office Manager' manual-only. History spans three full "
        "snapshots (20 days).",
        [
            snap(
                "s1",
                "greenhouse",
                "orbit",
                "2026-09-10T00:00:00Z",
                "full",
                [og("g1", N, "Systems Engineer", "Remote")],
            ),
            snap(
                "s2",
                "lever",
                "orbit",
                "2026-09-12T00:00:00Z",
                "full",
                [
                    ol("l1", N, "Systems Engineer", "Remote"),
                    ol("l2", N, "Account Executive", "Chicago, IL"),
                ],
            ),
            snap(
                "s3",
                "ashby",
                "orbit",
                "2026-09-30T00:00:00Z",
                "full",
                [
                    oa("a1", N, "Systems Engineer", "Remote"),
                    oa("a2", N, "Site Reliability Engineer", "Remote"),
                ],
            ),
            snap(
                "s4",
                "csv",
                "orbit-leads",
                "2026-10-01T00:00:00Z",
                "additive",
                [
                    oc(None, N, "Systems Engineer", "Remote"),
                    oc(None, N, "Account Executive", "IL - Chicago"),
                ],
            ),
            snap(
                "s5",
                "manual",
                "manual",
                "2026-10-02T00:00:00Z",
                "additive",
                [
                    om(None, N, "Systems Engineer", "Remote"),
                    om(None, N, "Office Manager", "Chicago IL"),
                ],
            ),
        ],
        include=["engineer", "executive"],
    )

    # 34 ------------------------------------------------------------------
    mo = src("greenhouse", "mosaic")
    M = "Mosaic Group"
    add(
        "mixed-work-modes-and-role-order",
        "Work modes remote/hybrid/onsite/unknown are carried through to roles. Roles are ordered active first, "
        "then first_seen, then role_id (ties on first_seen are broken by role_id); the removed role comes last.",
        [
            snap(
                "s1",
                "greenhouse",
                "mosaic",
                "2026-09-01T00:00:00Z",
                "full",
                [
                    mo("1", M, "Remote Engineer", "Remote", work_mode="remote"),
                    mo("2", M, "Hybrid Designer", "Leeds", work_mode="hybrid"),
                    mo("3", M, "Onsite Technician", "Leeds", work_mode="onsite"),
                    mo("4", M, "Unknown Planner", "Leeds"),
                ],
            ),
            snap(
                "s2",
                "greenhouse",
                "mosaic",
                "2026-09-20T00:00:00Z",
                "full",
                [
                    mo("1", M, "Remote Engineer", "Remote", work_mode="remote"),
                    mo("2", M, "Hybrid Designer", "Leeds", work_mode="hybrid"),
                    mo("4", M, "Unknown Planner", "Leeds"),
                    mo("5", M, "Remote Writer", "Remote", work_mode="remote"),
                    mo("6", M, "Hybrid Editor", "Leeds", work_mode="hybrid"),
                ],
            ),
        ],
    )

    # 35 ------------------------------------------------------------------
    ge, le, ae, ce = (
        src("greenhouse", "geo"),
        src("lever", "geo"),
        src("ashby", "geo"),
        src("csv", "geo"),
    )
    G = "Geo Services"
    add(
        "location-token-order-dedup",
        "location_key sorts unique tokens, so 'New York, NY', 'NY - New York' and 'NY, New York' from three "
        "ATS sources are one canonical role (displayed from the member seen last), and so are 'Z\u00fcrich, "
        "Switzerland' / 'Switzerland - Z\u00fcrich'. 'New York NY (Hybrid)' adds the token 'hybrid' and is a "
        "different role; so is 'Remote (US)' vs 'Remote'.",
        [
            snap(
                "s1",
                "greenhouse",
                "geo",
                "2026-10-01T00:00:00Z",
                "full",
                [
                    ge("1", G, "Support Engineer", "New York, NY"),
                    ge("2", G, "Account Manager", "Z\u00fcrich, Switzerland"),
                    ge("3", G, "Recruiter", "Remote"),
                ],
            ),
            snap(
                "s2",
                "lever",
                "geo",
                "2026-10-02T00:00:00Z",
                "full",
                [
                    le("L1", G, "Support Engineer", "NY - New York"),
                    le("L2", G, "Account Manager", "Switzerland - Z\u00fcrich"),
                    le("L3", G, "Recruiter", "Remote (US)"),
                ],
            ),
            snap(
                "s3",
                "ashby",
                "geo",
                "2026-10-03T00:00:00Z",
                "full",
                [ae("A1", G, "Support Engineer", "NY, New York")],
            ),
            snap(
                "s4",
                "csv",
                "geo",
                "2026-10-04T00:00:00Z",
                "additive",
                [ce(None, G, "Support Engineer", "New York NY (Hybrid)")],
            ),
        ],
    )

    # 36 ------------------------------------------------------------------
    fu, fc = src("greenhouse", "future"), src("csv", "future-list")
    add(
        "future-posted-at-age-clamp",
        "posted_at later than as_of gives a negative raw age that clamps to 0 (age_days 0, known, not aged); "
        "posted_at on the as_of day is also 0. When two sources disagree, the canonical posted_at is the "
        "earliest non-null ('2026-10-01' beats the future '2026-11-01') => age 12.",
        [
            snap(
                "s1",
                "greenhouse",
                "future",
                "2026-10-12T00:00:00Z",
                "full",
                [
                    fu(
                        "1",
                        "Future Foods",
                        "Engineer",
                        "Remote",
                        posted_at="2026-11-01",
                    ),
                    fu(
                        "2", "Future Foods", "Analyst", "Remote", posted_at="2026-10-13"
                    ),
                    fu(
                        "3",
                        "Future Foods",
                        "Engineer II",
                        "Remote",
                        posted_at="2026-11-01",
                    ),
                ],
            ),
            snap(
                "s2",
                "csv",
                "future-list",
                "2026-10-12T06:00:00Z",
                "additive",
                [
                    fc(
                        None,
                        "Future Foods",
                        "Engineer",
                        "Remote",
                        posted_at="2026-10-01",
                    )
                ],
            ),
        ],
        include=["engineer", "analyst"],
    )

    # 37 ------------------------------------------------------------------
    bg, bc, bm = src("greenhouse", "bw"), src("csv", "bw-list"), src("manual", "manual")
    bl, ba = src("lever", "bw"), src("ashby", "bw")
    B = "Bracket Works"
    add(
        "title-key-brackets-dedup",
        "title_key strips ( ) and [ ] segments (nested, repeatedly) before normalizing, so 'Software Engineer "
        "(Remote)', '[US]' and the bare title are one role; 'Data Engineer (Remote (US))' joins 'Data "
        "Engineer'. An UNBALANCED '(Remote' is not removed ('platform engineer remote' is a different role) "
        "and FULLWIDTH brackets are not removed either ('designer remote'). The displayed title is the member "
        "seen last.",
        [
            snap(
                "s1",
                "greenhouse",
                "bw",
                "2026-10-01T00:00:00Z",
                "full",
                [
                    bg("1", B, "Software Engineer (Remote)", "Remote"),
                    bg("3", B, "Platform Engineer (Remote", "Remote"),
                    bg("4", B, "Designer\uff08Remote\uff09", "Remote"),
                ],
            ),
            snap(
                "s2",
                "csv",
                "bw-list",
                "2026-10-02T00:00:00Z",
                "additive",
                [
                    bc(None, B, "Software Engineer [US]", "Remote"),
                    bc(None, B, "Platform Engineer", "Remote"),
                    bc(None, B, "Designer", "Remote"),
                ],
            ),
            snap(
                "s3",
                "manual",
                "manual",
                "2026-10-03T00:00:00Z",
                "additive",
                [bm(None, B, "Software Engineer", "Remote")],
            ),
            snap(
                "s4",
                "lever",
                "bw",
                "2026-10-04T00:00:00Z",
                "full",
                [bl("L2", B, "Data Engineer (Remote (US))", "Berlin")],
            ),
            snap(
                "s5",
                "ashby",
                "bw",
                "2026-10-05T00:00:00Z",
                "full",
                [ba("A2", B, "Data Engineer", "Berlin")],
            ),
        ],
    )

    # 38 ------------------------------------------------------------------
    t = "2026-10-01T00:00:00Z"
    add(
        "snapshot-order-id-tiebreak",
        "Snapshots are processed by (observed_at, snapshot_id) with string order: 's10' < 's2' < 'snap-a' < "
        "'snap-b' even though they are listed differently and 's10' is numerically larger than 's2'. "
        "'snap-a' (processed first) is the csv baseline so 'Fitter' in 'snap-b' is `added`; the reverse order "
        "would make both rows baselines.",
        [
            snap(
                "s2",
                "greenhouse",
                "beta",
                t,
                "full",
                [src("greenhouse", "beta")("1", "Beta Works", "Welder", "Remote")],
            ),
            snap(
                "s10",
                "greenhouse",
                "alpha",
                t,
                "full",
                [src("greenhouse", "alpha")("1", "Alpha Works", "Painter", "Remote")],
            ),
            snap(
                "snap-b",
                "csv",
                "list",
                t,
                "additive",
                [
                    src("csv", "list")(None, "Gamma Works", "Rigger", "Remote"),
                    src("csv", "list")(None, "Gamma Works", "Fitter", "Remote"),
                ],
            ),
            snap(
                "snap-a",
                "csv",
                "list",
                t,
                "additive",
                [src("csv", "list")(None, "Gamma Works", "Rigger", "Remote")],
            ),
        ],
    )

    # 39 ------------------------------------------------------------------
    bk, bkc = src("greenhouse", "blank"), src("csv", "blank-list")
    add(
        "empty-keys",
        "Names/titles/locations made only of punctuation normalize to the empty string and are still valid "
        "keys: company key '' (company_id c_e3b0c44298fc = sha12('')), title_key '' and location_key '' (also "
        "what a null location gives), so '!!!' and '***' are one company and the two postings are one role. "
        "No keyword can match an empty title, so the role is not relevant.",
        [
            snap(
                "s1",
                "greenhouse",
                "blank",
                "2026-10-05T00:00:00Z",
                "full",
                [bk("1", "!!!", "(Remote)", "???")],
            ),
            snap(
                "s2",
                "csv",
                "blank-list",
                "2026-10-06T00:00:00Z",
                "additive",
                [bkc(None, "***", "[Hybrid]", None)],
            ),
        ],
        include=["engineer"],
    )

    # 40 ------------------------------------------------------------------
    sh = src("greenhouse", "software-house")
    add(
        "minimal-single-role",
        "The smallest scored company: one active relevant role from one greenhouse snapshot 3 days old. "
        "Change and urgency are null (insufficient_history, no_dated_roles) and coverage is 75.",
        [
            snap(
                "s1",
                "greenhouse",
                "software-house",
                "2026-10-10T12:00:00Z",
                "full",
                [
                    sh(
                        "1",
                        "Software House Ltd",
                        "Software Engineer",
                        "Remote",
                        url=url("boards", "software-house", "1"),
                    )
                ],
            )
        ],
        include=["engineer"],
    )

    # 41 ------------------------------------------------------------------
    gg = src("greenhouse", "twins")
    add(
        "history-span-uses-all-source-snapshots",
        "T is every full snapshot of every source that supplied a role to the company - including snapshots "
        "that did not list it. 'Beta Co' first appears in the second greenhouse snapshot, but the source's "
        "first snapshot (2026-08-01) counts too: span 31 days, so change is computed (its only event is "
        "outside the window => 500) instead of insufficient_history.",
        [
            snap(
                "s1",
                "greenhouse",
                "twins",
                "2026-08-01T00:00:00Z",
                "full",
                [gg("1", "Alpha Co", "Engineer", "Remote")],
            ),
            snap(
                "s2",
                "greenhouse",
                "twins",
                "2026-09-01T00:00:00Z",
                "full",
                [
                    gg("1", "Alpha Co", "Engineer", "Remote"),
                    gg("2", "Beta Co", "Engineer", "Remote"),
                ],
            ),
        ],
    )

    # 42 ------------------------------------------------------------------
    sg, sl, sc = (
        src("greenhouse", "support"),
        src("lever", "support"),
        src("csv", "support-sheet"),
    )
    H = "Support Hub"
    add(
        "headcounts-match-across-sources",
        "Cross-source matching is one-to-one by sorted source role key, not by listing or first-seen order: "
        "greenhouse has ids 201/202 and lever L-a/L-b for the same title+location (two headcount) and csv has "
        "one row. Greenhouse '202' and lever 'L-b' were seen FIRST, but canonical role 0 is built from the "
        "smallest key of every source ('201' + 'L-a' + the csv row) and canonical role 1 from the second "
        "('202' + 'L-b').",
        [
            snap(
                "g1",
                "greenhouse",
                "support",
                "2026-09-01T00:00:00Z",
                "full",
                [sg("202", H, "Support Engineer", "Berlin")],
            ),
            snap(
                "l1",
                "lever",
                "support",
                "2026-09-03T00:00:00Z",
                "full",
                [sl("L-b", H, "Support Engineer", "Berlin")],
            ),
            snap(
                "c1",
                "csv",
                "support-sheet",
                "2026-09-05T00:00:00Z",
                "additive",
                [sc(None, H, "Support Engineer", "Berlin")],
            ),
            snap(
                "g2",
                "greenhouse",
                "support",
                "2026-09-10T00:00:00Z",
                "full",
                [
                    sg("202", H, "Support Engineer", "Berlin"),
                    sg("201", H, "Support Engineer", "Berlin"),
                ],
            ),
            snap(
                "l2",
                "lever",
                "support",
                "2026-09-12T00:00:00Z",
                "full",
                [
                    sl("L-b", H, "Support Engineer", "Berlin"),
                    sl("L-a", H, "Support Engineer", "Berlin"),
                ],
            ),
        ],
    )

    # 43 ------------------------------------------------------------------
    lg, lc = src("greenhouse", "lumen"), src("csv", "lumen-sheet")
    add(
        "additive-imports-are-not-history",
        "T counts only FULL snapshots. 'Lumen' has one greenhouse full snapshot (2026-08-01) and a csv import "
        "65 days later: there is a single full snapshot, so `change` is insufficient_history with span_days "
        "null and the 45-day span rule cannot age the undated roles (no_dated_roles), even though 65 days "
        "separate the first and last snapshot of any kind.",
        [
            snap(
                "g1",
                "greenhouse",
                "lumen",
                "2026-08-01T00:00:00Z",
                "full",
                [lg("1", "Lumen", "Optics Engineer", "Remote")],
            ),
            snap(
                "c1",
                "csv",
                "lumen-sheet",
                "2026-10-05T00:00:00Z",
                "additive",
                [
                    lc(None, "Lumen", "Optics Engineer", "Remote"),
                    lc(None, "Lumen", "Sales Lead", "Boston"),
                ],
            ),
        ],
    )

    # 44 ------------------------------------------------------------------
    pg, pc, pl = (
        src("greenhouse", "prism"),
        src("csv", "prism-sheet"),
        src("lever", "prism"),
    )
    P = "Prism Labs"
    add(
        "canonical-last-seen-ignores-removed-members",
        "A canonical role's last_seen is the max over its ACTIVE members only. 'Optics Engineer' was last "
        "listed by greenhouse on 2026-09-10 but that member has been removed; the csv member (active, last "
        "listed 2026-09-05) keeps the role alive, so last_seen is 2026-09-05 and freshness uses 38 days, "
        "not 33. 'Legacy Analyst' has no active member: last_seen is then the max over ALL members "
        "(2026-09-20) and removed_at is the LATEST member removal (2026-10-08, not 2026-10-05). Display "
        "fields are identical across members so the displayed values do not depend on which member "
        "is chosen.",
        [
            snap(
                "g1",
                "greenhouse",
                "prism",
                "2026-09-01T00:00:00Z",
                "full",
                [
                    pg("1", P, "Optics Engineer", "Remote"),
                    pg("9", P, "Legacy Analyst", "Remote"),
                ],
            ),
            snap(
                "c1",
                "csv",
                "prism-sheet",
                "2026-09-05T00:00:00Z",
                "additive",
                [pc(None, P, "Optics Engineer", "Remote")],
            ),
            snap(
                "g2",
                "greenhouse",
                "prism",
                "2026-09-10T00:00:00Z",
                "full",
                [
                    pg("1", P, "Optics Engineer", "Remote"),
                    pg("9", P, "Legacy Analyst", "Remote"),
                ],
            ),
            snap(
                "l1",
                "lever",
                "prism",
                "2026-09-20T00:00:00Z",
                "full",
                [pl("L9", P, "Legacy Analyst", "Remote")],
            ),
            snap("g3", "greenhouse", "prism", "2026-10-05T00:00:00Z", "full", []),
            snap("l2", "lever", "prism", "2026-10-08T00:00:00Z", "full", []),
        ],
    )

    # ---------------------------------------------------------------------
    # 45-47 pin readings that the first 44 vectors deliberately left open and that the
    # differential review (docs/spec/ambiguities/differential.md D-2, D-3, D-4) then DECIDED.
    # Before they existed the two engines and the oracle each took a different reading and every
    # vector still passed; these three make the decision part of the contract.
    # ---------------------------------------------------------------------

    # 45 ------------------------------------------------------------------
    tg, tl, pg, pl = (
        src("greenhouse", "tidewater"),
        src("lever", "tidewater"),
        src("greenhouse", "pier-nine"),
        src("lever", "pier-nine"),
    )
    add(
        "span-counts-instants-not-snapshots",
        "02 s4 writes |T|, min T and max T, so T is a SET of instants. 'Tidewater Freight' has a greenhouse "
        "board and a lever board, each with ONE full snapshot, both observed at 2026-10-01T00:00:00Z: T has "
        "one element, so span_days is null (a multiset reading would give 0). 'Pier Nine' has the same two "
        "boards observed 30 days apart, again one full snapshot each: T has two instants (one per source), "
        "span_days is 30 and 'change' is computed; the lever baseline is not an 'added' event, so net is 0 "
        "and the value is 500.",
        [
            snap(
                "tw-g",
                "greenhouse",
                "tidewater",
                "2026-10-01T00:00:00Z",
                "full",
                [tg("501", "Tidewater Freight", "Dock Planner", "Rotterdam")],
            ),
            snap(
                "tw-l",
                "lever",
                "tidewater",
                "2026-10-01T00:00:00Z",
                "full",
                [tl("L-501", "Tidewater Freight", "Dock Planner", "Rotterdam")],
            ),
            snap(
                "pn-g",
                "greenhouse",
                "pier-nine",
                "2026-09-01T00:00:00Z",
                "full",
                [pg("601", "Pier Nine", "Berth Planner", "Bergen")],
            ),
            snap(
                "pn-l",
                "lever",
                "pier-nine",
                "2026-10-01T00:00:00Z",
                "full",
                [pl("L-601", "Pier Nine", "Berth Planner", "Bergen")],
            ),
        ],
    )

    # 46 ------------------------------------------------------------------
    ha, hb = src("csv", "hollow-a"), src("csv", "hollow-b")
    add(
        "merge-through-absent-key-names-the-group",
        "01 s3: the canonical key of a merged group is its lexicographically smallest MEMBER key, and every "
        "key a merge decision names is a member - including a key no posting has any more (a stale "
        "decision, e.g. after a source was deleted). 'ardent hollow' has no posting: merging it with "
        "'birch hollow' and 'cedar hollow' makes it the group's key (and company_id), although it is not "
        "among the present keys. 'zenith row' is absent too, but larger than both present keys, so the "
        "group of 'dune row' and 'elm row' that it joins keeps 'dune row'; the merge is transitive "
        "through an absent key either way. Two roles dedupe across the merged companies (same title and "
        "location, two sources).",
        [
            snap(
                "hollow-a-1",
                "csv",
                "hollow-a",
                "2026-10-05T00:00:00Z",
                "additive",
                [
                    ha(None, "Birch Hollow", "Kiln Operator", "Delft"),
                    ha(None, "Dune Row", "Glaze Chemist", "Utrecht"),
                ],
            ),
            snap(
                "hollow-b-1",
                "csv",
                "hollow-b",
                "2026-10-06T00:00:00Z",
                "additive",
                [
                    hb(None, "Cedar Hollow", "Kiln Operator", "Delft"),
                    hb(None, "Elm Row", "Glaze Chemist", "Utrecht"),
                ],
            ),
        ],
        decisions=[
            {"a_key": "ardent hollow", "b_key": "birch hollow", "decision": "merge"},
            {"a_key": "ardent hollow", "b_key": "cedar hollow", "decision": "merge"},
            {"a_key": "dune row", "b_key": "zenith row", "decision": "merge"},
            {"a_key": "elm row", "b_key": "zenith row", "decision": "merge"},
        ],
    )

    # 47 ------------------------------------------------------------------
    la, lb = src("csv", "list-a"), src("csv", "list-b")
    add(
        "not-same-names-the-canonical-pair",
        "01 s3.4 emits a candidate for a pair of GROUP CANONICAL keys 'not marked not_same'; a decision "
        "marks exactly the (a_key, b_key) pair it names. 'alpha groupy' is merged into 'alpha group', so "
        "the pair of groups is ('alpha group', 'alpha groupz') (near_typo). The user's not_same names "
        "'alpha groupy' / 'alpha groupz' - a MEMBER of the merged group, not the canonical pair - so it "
        "does not hide that candidate (mapping decision keys to canonical keys first would hide it). The "
        "not_same for 'delta works' / 'delta workz' names the pair itself and does hide it.",
        [
            snap(
                "list-a-1",
                "csv",
                "list-a",
                "2026-10-12T00:00:00Z",
                "additive",
                [
                    la(None, "Alpha Group", "Engineer", "Lisbon"),
                    la(None, "Alpha Groupz", "Engineer", "Lisbon"),
                    la(None, "Delta Works", "Engineer", "Lisbon"),
                    la(None, "Delta Workz", "Engineer", "Lisbon"),
                ],
            ),
            snap(
                "list-b-1",
                "csv",
                "list-b",
                "2026-10-12T00:00:00Z",
                "additive",
                [lb(None, "Alpha Groupy", "Engineer", "Lisbon")],
            ),
        ],
        decisions=[
            {"a_key": "alpha group", "b_key": "alpha groupy", "decision": "merge"},
            {"a_key": "alpha groupy", "b_key": "alpha groupz", "decision": "not_same"},
            {"a_key": "delta works", "b_key": "delta workz", "decision": "not_same"},
        ],
    )


def build_analysis():
    define_vectors()
    out = []
    for v in VECTORS:
        problems = oracle.validate_input(v["input"])
        if problems:
            raise SystemExit(f"{v['name']}: invalid input: {problems}")
        out.append(
            {
                "name": v["name"],
                "description": v["description"],
                "input": v["input"],
                "expected": oracle.analyze(v["input"]),
            }
        )
    return out


def build_all():
    return build_normalization(), build_analysis()


# ===================================================================== output
def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main():
    norm, analysis = build_all()
    os.makedirs(VECTOR_DIR, exist_ok=True)
    for old in os.listdir(VECTOR_DIR):
        if old.startswith("analysis-") and old.endswith(".json"):
            os.remove(os.path.join(VECTOR_DIR, old))
    head = {k: v for k, v in norm.items() if k != "cases"}
    lines = ["{"]
    for k, v in head.items():
        lines.append(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=True)},")
    lines.append('  "cases": [')
    body = [f"    {json.dumps(c, ensure_ascii=True)}" for c in norm["cases"]]
    lines.append(",\n".join(body))
    lines += ["  ]", "}", ""]
    _write(os.path.join(VECTOR_DIR, "normalization.json"), "\n".join(lines))
    for n, v in enumerate(analysis, 1):
        _write(
            os.path.join(VECTOR_DIR, f"analysis-{n:02d}-{v['name']}.json"),
            json.dumps(v, indent=2, ensure_ascii=True) + "\n",
        )
    print(
        f"wrote normalization.json ({len(norm['cases'])} cases) and {len(analysis)} analysis vectors"
    )
    _prettify()


def _prettify():
    """`npm run format:check` covers contracts/vectors, so format what was just written."""
    npx = shutil.which("npx")
    if npx is None:
        print(
            "npx not found: run `npx prettier --write contracts/vectors` before committing"
        )
        return
    repo = os.path.normpath(os.path.join(HERE, "..", ".."))
    done = subprocess.run(
        [npx, "prettier", "--write", "contracts/vectors"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        print("prettier failed; run `npx prettier --write contracts/vectors` manually")
        print(done.stdout[-400:] + done.stderr[-400:])
    else:
        print("formatted contracts/vectors with prettier")


if __name__ == "__main__":
    main()
