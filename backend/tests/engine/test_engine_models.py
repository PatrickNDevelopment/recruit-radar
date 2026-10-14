"""Boundary validation: RawPosting rules (spec 01 section 1) and the analyze input shape."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from rr_engine_testkit import AS_OF, make_input, posting, snapshot

from recruit_radar.engine import EngineInputError, analyze
from recruit_radar.engine.models import parse_input
from recruit_radar.engine.timeutil import (
    date_to_epoch,
    days_between,
    timestamp_to_epoch,
)


def one_posting_input(**overrides: Any) -> dict[str, Any]:
    raw = posting(**{k: v for k, v in overrides.items() if k in {"company", "title"}})
    raw.update({k: v for k, v in overrides.items() if k not in {"company", "title"}})
    return make_input([snapshot("s1", "2026-10-01T00:00:00Z", [raw])])


def rejects(payload: Any, fragment: str | None = None) -> None:
    with pytest.raises(EngineInputError) as caught:
        analyze(payload)
    assert isinstance(caught.value, ValueError)
    if fragment is not None:
        assert fragment in str(caught.value)


class TestTopLevelShape:
    def test_empty_input_is_valid(self) -> None:
        result = analyze({"as_of": AS_OF})
        assert result["companies"] == []
        assert result["roles"] == []
        assert result["events"] == []
        assert result["merge_candidates"] == []
        assert result["stats"] == {
            "snapshots": 0,
            "postings_observed": 0,
            "companies": 0,
            "active_roles": 0,
        }

    def test_non_object_input(self) -> None:
        rejects([1, 2, 3], "must be an object")
        rejects(None, "must be an object")
        rejects("{}", "must be an object")

    def test_as_of_is_required(self) -> None:
        rejects({"snapshots": []}, "as_of")

    def test_unknown_top_level_key_is_ignored(self) -> None:
        # D-5: spec 02 section 1 forbids nothing and the TypeScript engine ignores unknown
        # properties; `extra="forbid"` of spec 03 is about API request bodies, not analyze().
        payload = make_input([])
        payload["version"] = 1
        assert analyze(payload) == analyze(make_input([]))

    @pytest.mark.parametrize(
        "bad",
        [
            "2026-10-13",
            "2026-10-13 12:00:00Z",
            "2026-10-13T12:00:00",
            "2026-10-13T12:00:00+00:00",
            "2026-10-13T12:00:00.000Z",
            "2026-13-01T00:00:00Z",
            "2026-02-30T00:00:00Z",
            "2026-10-13T24:00:00Z",
            "2026-10-13T12:60:00Z",
            "2026-10-13T12:00:60Z",
            "2026-10-13t12:00:00z",
            " 2026-10-13T12:00:00Z",
            "2026-10-13T12:00:00Z\n",
            "",
            "0000-01-01T00:00:00Z",
        ],
    )
    def test_bad_as_of(self, bad: str) -> None:
        rejects(make_input([], as_of=bad), "as_of")

    def test_as_of_must_be_a_string(self) -> None:
        rejects({"as_of": 20261013})

    def test_leap_day_is_a_real_date(self) -> None:
        analyze(make_input([], as_of="2028-02-29T00:00:00Z"))
        rejects(make_input([], as_of="2026-02-29T00:00:00Z"))


class TestProfileAndDecisions:
    def test_profile_extras_ignored(self) -> None:
        payload = make_input([])
        payload["profile"]["match_all"] = True
        assert analyze(payload) == analyze(make_input([]))

    def test_keywords_must_be_strings(self) -> None:
        payload = make_input([])
        payload["profile"]["include_keywords"] = ["ok", 3]
        rejects(payload, "include_keywords")

    def test_decision_pair_must_be_ordered(self) -> None:
        decision = {"a_key": "b", "b_key": "a", "decision": "merge"}
        rejects(make_input([], decisions=[decision]), "a_key")
        same = {"a_key": "a", "b_key": "a", "decision": "merge"}
        rejects(make_input([], decisions=[same]), "a_key")

    def test_decision_kind(self) -> None:
        rejects(make_input([], decisions=[{"a_key": "a", "b_key": "b", "decision": "maybe"}]))

    def test_decision_extras_ignored(self) -> None:
        extra = {"a_key": "a", "b_key": "b", "decision": "merge", "id": 7}
        plain = {"a_key": "a", "b_key": "b", "decision": "merge"}
        assert analyze(make_input([], decisions=[extra])) == analyze(
            make_input([], decisions=[plain])
        )

    def test_decision_ordering_is_by_code_point(self) -> None:
        upper_first = {"a_key": "Z", "b_key": "a", "decision": "merge"}
        analyze(make_input([], decisions=[upper_first]))  # "Z" (0x5A) < "a" (0x61)
        rejects(make_input([], decisions=[{"a_key": "a", "b_key": "Z", "decision": "merge"}]))


class TestSnapshotValidation:
    def test_duplicate_snapshot_ids(self) -> None:
        snaps = [
            snapshot("s1", "2026-10-01T00:00:00Z", []),
            snapshot("s1", "2026-10-02T00:00:00Z", [], ref="other"),
        ]
        rejects(make_input(snaps), "duplicate snapshot_id")

    def test_empty_snapshot_id(self) -> None:
        rejects(make_input([snapshot("", "2026-10-01T00:00:00Z", [])]), "snapshot_id")

    def test_bad_enums(self) -> None:
        rejects(make_input([snapshot("s", "2026-10-01T00:00:00Z", [], kind="workday")]))
        rejects(make_input([snapshot("s", "2026-10-01T00:00:00Z", [], mode="partial")]))

    def test_source_ref_bounds(self) -> None:
        rejects(make_input([snapshot("s", "2026-10-01T00:00:00Z", [], ref="   ")]), "source_ref")
        rejects(
            make_input([snapshot("s", "2026-10-01T00:00:00Z", [], ref="x" * 201)]), "source_ref"
        )
        analyze(make_input([snapshot("s", "2026-10-01T00:00:00Z", [], ref="x" * 200)]))

    def test_bad_observed_at(self) -> None:
        rejects(make_input([snapshot("s", "2026-10-01", [])]), "observed_at")

    def test_snapshot_extras_ignored(self) -> None:
        snap = snapshot("s", "2026-10-01T00:00:00Z", [])
        plain = dict(snap)
        snap["note"] = "x"
        assert analyze(make_input([snap])) == analyze(make_input([plain]))

    def test_snapshot_without_postings_key(self) -> None:
        snap = snapshot("s", "2026-10-01T00:00:00Z", [])
        del snap["postings"]
        assert analyze(make_input([snap]))["stats"]["snapshots"] == 1

    def test_posting_source_fields_must_agree_with_snapshot(self) -> None:
        agree = posting()
        agree.update({"source_kind": "greenhouse", "source_ref": "acme"})
        analyze(make_input([snapshot("s", "2026-10-01T00:00:00Z", [agree])]))
        disagree = posting()
        disagree["source_kind"] = "lever"
        rejects(make_input([snapshot("s", "2026-10-01T00:00:00Z", [disagree])]), "source_kind")

    def test_input_is_not_mutated(self) -> None:
        payload = one_posting_input(location="  New York  ")
        before = copy.deepcopy(payload)
        analyze(payload)
        assert payload == before


class TestPostingValidation:
    def test_minimal_posting(self) -> None:
        parsed = parse_input(one_posting_input())
        raw = parsed.snapshots[0].postings[0]
        assert (raw.company_name, raw.title) == ("Acme", "Engineer")
        assert raw.work_mode == "unknown"
        assert raw.location is None
        assert raw.source_posting_id is None

    def test_strings_are_trimmed_and_blank_optionals_become_null(self) -> None:
        payload = one_posting_input(
            company="  Acme  Inc.  ",
            title=" Senior  Engineer ",
            location="   ",
            department="",
            url="",
            posted_at="",
            source_posting_id="  ",
            work_mode="",
        )
        raw = parse_input(payload).snapshots[0].postings[0]
        assert raw.company_name == "Acme  Inc."  # internal whitespace is preserved
        assert raw.title == "Senior  Engineer"
        assert raw.location is None
        assert raw.department is None
        assert raw.url is None
        assert raw.posted_at is None
        assert raw.source_posting_id is None
        assert raw.work_mode == "unknown"

    def test_derived_keys(self) -> None:
        raw = (
            parse_input(
                one_posting_input(
                    company="The Acme Corp.", title="Engineer (Remote)", location="NY, NY"
                )
            )
            .snapshots[0]
            .postings[0]
        )
        assert (raw.company_key, raw.title_key, raw.location_key) == ("acme", "engineer", "ny")

    @pytest.mark.parametrize(
        ("overrides", "fragment"),
        [
            ({"company": ""}, "company_name"),
            ({"company": "   "}, "company_name"),
            ({"company": "x" * 201}, "company_name"),
            ({"title": ""}, "title"),
            ({"title": "t" * 301}, "title"),
            ({"location": "l" * 301}, "location"),
            ({"department": "d" * 201}, "department"),
            ({"work_mode": "office"}, "work_mode"),
            ({"work_mode": "Remote"}, "work_mode"),
            ({"url": "ftp://example.com/job"}, "url"),
            ({"url": "javascript:alert(1)"}, "url"),
            ({"url": "example.com/job"}, "url"),
            ({"posted_at": "2026-02-30"}, "posted_at"),
            ({"posted_at": "2026-13-01"}, "posted_at"),
            ({"posted_at": "26-10-01"}, "posted_at"),
            ({"posted_at": "2026-10-01T00:00:00Z"}, "posted_at"),
            ({"posted_at": "2026/10/01"}, "posted_at"),
            ({"posted_at": "2026-1-1"}, "posted_at"),
            ({"source_posting_id": 123}, "source_posting_id"),
        ],
    )
    def test_invalid_posting_fields(self, overrides: dict[str, Any], fragment: str) -> None:
        rejects(one_posting_input(**overrides), fragment)

    def test_unknown_posting_key_is_ignored(self) -> None:
        # D-5 again, at the posting level (a description field, for instance, is not stored).
        with_extra = one_posting_input(nonsense="x")
        assert analyze(with_extra) == analyze(one_posting_input())

    @pytest.mark.parametrize(
        "overrides",
        [
            {"company": "x" * 200},
            {"title": "t" * 300},
            {"location": "l" * 300},
            {"department": "d" * 200},
            {"url": "https://example.com/jobs/1"},
            {"url": "HTTP://EXAMPLE.COM/jobs/1"},
            {"url": "  https://example.com/jobs/1  "},
            {"posted_at": "2024-02-29"},
            {"work_mode": "onsite"},
            {"source_posting_id": "abc-123"},
        ],
    )
    def test_boundary_values_accepted(self, overrides: dict[str, Any]) -> None:
        analyze(one_posting_input(**overrides))

    def test_length_limits_apply_after_trimming(self) -> None:
        analyze(one_posting_input(company="  " + "x" * 200 + "  "))
        rejects(one_posting_input(company="x" * 201 + "  "), "company_name")

    def test_url_scheme_check_is_ascii_only(self) -> None:
        # U+017F (long s) case-folds to "s" under Unicode ignore-case matching; it must not count.
        rejects(one_posting_input(url="http" + chr(0x17F) + "://example.com"), "url")

    def test_non_string_company_is_rejected_not_coerced(self) -> None:
        payload = make_input(
            [snapshot("s", "2026-10-01T00:00:00Z", [{"company_name": 5, "title": "t"}])]
        )
        rejects(payload, "company_name")


class TestTimeUtil:
    def test_timestamp_to_epoch(self) -> None:
        assert timestamp_to_epoch("1970-01-01T00:00:00Z") == 0
        assert timestamp_to_epoch("2026-10-13T12:00:00Z") == 1_791_892_800
        assert (
            timestamp_to_epoch("2000-03-01T00:00:00Z") - timestamp_to_epoch("2000-02-28T00:00:00Z")
            == 2 * 86_400
        )  # 2000 is a leap year

    def test_date_to_epoch_is_midnight_utc(self) -> None:
        assert date_to_epoch("2026-10-13") == timestamp_to_epoch("2026-10-13T00:00:00Z")

    def test_days_between_floors_and_may_be_negative(self) -> None:
        start = timestamp_to_epoch("2026-10-01T00:00:00Z")
        assert days_between(start, start + 86_399) == 0
        assert days_between(start, start + 86_400) == 1
        assert days_between(start, start - 1) == -1
        assert days_between(start, start - 86_400) == -1
        assert days_between(start, start - 86_401) == -2
