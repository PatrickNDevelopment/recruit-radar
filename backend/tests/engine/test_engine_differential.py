"""Regression tests for the readings fixed by the differential review.

The Python engine, the TypeScript engine and the oracle were written independently from the same
spec and disagreed on each of these points while every golden vector still passed. The decision and
the spec text it rests on are in ``docs/spec/ambiguities/differential.md`` (D-1 .. D-10); the
TypeScript twin of this file is ``tests/differential.test.ts``. D-2, D-3 and D-5 are also asserted in
``test_engine_analyze.py`` / ``test_engine_identity.py`` / ``test_engine_models.py``, and D-2, D-3 and
D-4 are pinned by golden vectors 45-47.
"""

from __future__ import annotations

from typing import Any

import pytest
from rr_engine_testkit import AS_OF, company, make_input, posting, snapshot

from recruit_radar.engine import EngineInputError, analyze
from recruit_radar.engine.normalize import trim

T1 = "2026-10-01T00:00:00Z"


def one_snapshot(postings: list[dict[str, Any]], **options: str) -> dict[str, Any]:
    """A snapshot ``s1`` at T1; ``options`` are the testkit's ``kind`` / ``ref`` / ``mode``."""
    return snapshot("s1", T1, postings, **options)


def rejected(payload: Any) -> bool:
    try:
        analyze(payload)
    except EngineInputError:
        return True
    return False


# ECMA-262 WhiteSpace + LineTerminator: exactly what String.prototype.trim removes.
ECMASCRIPT_TRIMMED = frozenset(
    [
        0x09,
        0x0A,
        0x0B,
        0x0C,
        0x0D,
        0x20,
        0xA0,
        0x1680,
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
        0xFEFF,
    ]
    + list(range(0x2000, 0x200B))
)


class TestD1Trim:
    def test_trim_is_exactly_the_ecmascript_set_over_the_whole_bmp(self) -> None:
        disagreements = [
            code_point
            for code_point in range(0x10000)
            if not 0xD800 <= code_point <= 0xDFFF
            and (trim(chr(code_point) + "x" + chr(code_point)) == "x")
            != (code_point in ECMASCRIPT_TRIMMED)
        ]
        assert disagreements == []

    def test_a_bom_is_trimmed_but_nel_and_the_c0_separators_are_not(self) -> None:
        assert trim("\ufeffAcme\ufeff") == "Acme"
        assert trim("\u0085Acme") == "\u0085Acme"
        assert trim("\u001cAcme\u001f") == "\u001cAcme\u001f"

    def test_analyze_trims_with_the_same_set(self) -> None:
        raw = posting("\ufeff Acme \u3000", "\u0085Engineer\u0085", location="\u00a0Berlin\u00a0")
        result = analyze(make_input([one_snapshot([raw])]))
        acme = company(result, "acme")
        assert acme["name"] == "Acme"
        assert result["roles"][0]["title"] == "\u0085Engineer\u0085"
        assert result["roles"][0]["location"] == "Berlin"


class TestD4NotSameNamesTheCanonicalPair:
    POSTINGS = [  # noqa: RUF012 - read-only fixture shared by the tests in this class
        posting("Alpha Group", "Engineer"),
        posting("Alpha Groupy", "Engineer"),
        posting("Alpha Groupz", "Engineer"),
    ]
    MERGE = {"a_key": "alpha group", "b_key": "alpha groupy", "decision": "merge"}  # noqa: RUF012

    def candidates(self, *decisions: dict[str, str]) -> list[tuple[str, str, str]]:
        snaps = [one_snapshot(self.POSTINGS, kind="csv", ref="x", mode="additive")]
        result = analyze(make_input(snaps, decisions=[self.MERGE, *decisions]))
        return [(c["a_key"], c["b_key"], c["reason"]) for c in result["merge_candidates"]]

    def test_the_candidate_is_reported_between_canonical_keys(self) -> None:
        assert self.candidates() == [("alpha group", "alpha groupz", "near_typo")]

    def test_a_decision_naming_a_member_does_not_hide_it(self) -> None:
        member = {"a_key": "alpha groupy", "b_key": "alpha groupz", "decision": "not_same"}
        assert self.candidates(member) == [("alpha group", "alpha groupz", "near_typo")]

    def test_a_decision_naming_the_canonical_pair_hides_it(self) -> None:
        pair = {"a_key": "alpha group", "b_key": "alpha groupz", "decision": "not_same"}
        assert self.candidates(pair) == []


class TestD6InstantsAreNotTrimmed:
    """``as_of`` and ``observed_at`` are not RawPosting strings: their format is exact."""

    @pytest.mark.parametrize(
        "bad",
        [
            " 2026-10-13T12:00:00Z",
            "2026-10-13T12:00:00Z ",
            "\t2026-10-13T12:00:00Z",
            "2026-10-13T12:00:00Z\n",
            "\ufeff2026-10-13T12:00:00Z",
        ],
    )
    def test_padded_as_of_is_rejected(self, bad: str) -> None:
        assert rejected(make_input([], as_of=bad))

    @pytest.mark.parametrize("bad", [" 2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z\t"])
    def test_padded_observed_at_is_rejected(self, bad: str) -> None:
        assert rejected(make_input([snapshot("s", bad, [])]))

    def test_the_exact_form_is_accepted(self) -> None:
        assert analyze(make_input([snapshot("s", T1, [])], as_of=AS_OF))["as_of"] == AS_OF


class TestD7OmittedCollectionsAreEmpty:
    def test_missing_snapshots_is_an_empty_analysis(self) -> None:
        result = analyze({"as_of": AS_OF})
        assert result["companies"] == [] and result["stats"]["snapshots"] == 0

    def test_missing_postings_is_an_empty_snapshot(self) -> None:
        snap = snapshot("s", T1, [])
        del snap["postings"]
        assert analyze(make_input([snap]))["stats"] == {
            "snapshots": 1,
            "postings_observed": 0,
            "companies": 0,
            "active_roles": 0,
        }

    def test_null_is_not_an_omission(self) -> None:
        assert rejected({"as_of": AS_OF, "snapshots": None})
        snap = snapshot("s", T1, [])
        snap["postings"] = None
        assert rejected(make_input([snap]))


class TestD8UrlConstrainsTheSchemeOnly:
    @pytest.mark.parametrize(
        "value",
        [
            "https://example.com/jobs/1",
            "http://example.com",
            "HTTPS://EXAMPLE.COM",
            "Http://x",
            "https:",
            "https://",
            "http:example.com",
            "https://exa mple.com/a b",
            "https://example.com/\u0001",
            "https://example.com/a\nb",
        ],
    )
    def test_accepted(self, value: str) -> None:
        result = analyze(make_input([one_snapshot([posting(url=value)])]))
        assert result["roles"][0]["observations"][0]["url"] == value

    @pytest.mark.parametrize(
        "value",
        [
            "ftp://example.com/x",
            "javascript:alert(1)",
            "data:text/html,hi",
            "mailto:a@b.c",
            "//example.com/x",
            "example.com/jobs",
            "/jobs/1",
            "ht\ttps://example.com",
            "\u0001https://example.com",
            "http\u017f://example.com",
            "https\uff1a//example.com",
        ],
    )
    def test_rejected(self, value: str) -> None:
        assert rejected(make_input([one_snapshot([posting(url=value)])]))


class TestD9KeywordLimits:
    def keywords(
        self, *, include: list[str] | None = None, exclude: list[str] | None = None
    ) -> Any:
        return make_input([], include=include or [], exclude=exclude or [])

    def test_fifty_keywords_of_sixty_code_points_are_accepted(self) -> None:
        analyze(self.keywords(include=["k" * 60] * 50, exclude=["\U0001f600" * 60] * 50))

    def test_fifty_one_keywords_are_rejected(self) -> None:
        assert rejected(self.keywords(include=[f"k{i}" for i in range(51)]))
        assert rejected(self.keywords(include=["a"], exclude=[f"k{i}" for i in range(51)]))

    def test_a_sixty_one_code_point_keyword_is_rejected(self) -> None:
        assert rejected(self.keywords(include=["k" * 61]))
        assert rejected(self.keywords(include=["\U0001f600" * 61]))  # code points, not UTF-16 units

    def test_the_limit_applies_after_trimming(self) -> None:
        analyze(self.keywords(include=["  " + "k" * 60 + "  "]))
        assert rejected(self.keywords(include=["  " + "k" * 61 + "  "]))

    def test_a_blank_keyword_is_allowed_and_never_matches(self) -> None:
        result = analyze(
            make_input([one_snapshot([posting(title="Engineer")])], include=["", "   "])
        )
        assert result["roles"][0]["relevant"] is False


class TestD10PostingSourceRef:
    def test_a_present_but_empty_posting_source_ref_is_invalid(self) -> None:
        for value in ("", "   ", "\t"):
            raw = posting()
            raw["source_ref"] = value
            assert rejected(make_input([one_snapshot([raw])])), repr(value)

    def test_null_and_absent_inherit_the_snapshots_source(self) -> None:
        with_null = posting()
        with_null["source_ref"] = None
        for raw in (with_null, posting()):
            analyze(make_input([one_snapshot([raw])]))

    def test_a_padded_copy_of_the_snapshot_source_ref_agrees(self) -> None:
        raw = posting()
        raw["source_ref"] = "  acme  "
        analyze(make_input([one_snapshot([raw], ref="acme")]))
