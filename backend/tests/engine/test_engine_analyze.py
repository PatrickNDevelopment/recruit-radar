"""End-to-end behaviour of analyze(): shape, ordering, boundaries (spec 02)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from rr_engine_testkit import (
    AS_OF,
    company,
    component,
    events,
    make_input,
    posting,
    roles_of,
    snapshot,
)

from recruit_radar.engine import analyze
from recruit_radar.engine.identity import company_id_for

COMPANY_KEYS = {
    "company_id",
    "key",
    "name",
    "aliases",
    "first_seen",
    "last_seen",
    "active_roles",
    "relevant_roles",
    "removed_roles",
    "score",
    "coverage",
    "rank",
    "components",
}
ROLE_KEYS = {
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
}
OBSERVATION_KEYS = {
    "source_kind",
    "source_ref",
    "source_posting_id",
    "url",
    "status",
    "first_seen",
    "last_seen",
}
EVENT_KEYS = {
    "at",
    "type",
    "company_id",
    "role_id",
    "source_kind",
    "source_ref",
    "title",
    "fields",
}
COMPONENT_KEYS = {"key", "weight", "value", "reason_code", "inputs"}
COMPONENT_ORDER = [
    "role_relevance",
    "volume",
    "change",
    "urgency",
    "source_confidence",
    "freshness",
]
INPUT_KEYS = {
    "role_relevance": {"relevant", "active"},
    "volume": {"scope_roles"},
    "change": {"added", "removed", "net", "span_days", "window_days"},
    "urgency": {"aged", "known", "threshold_days"},
    "source_confidence": {"scope_roles", "corroborated"},
    "freshness": {"days_since_last_seen"},
}


def two_snapshot_company(
    first: str,
    second: str,
    *,
    extra_second: list[dict[str, Any]] | None = None,
    as_of: str = AS_OF,
    **kwargs: Any,
) -> dict[str, Any]:
    """Greenhouse board observed twice: role id 1 present both times, extras at ``second``."""
    snaps = [
        snapshot("s1", first, [posting(pid="1", title="Engineer")]),
        snapshot("s2", second, [posting(pid="1", title="Engineer"), *(extra_second or [])]),
    ]
    return analyze(make_input(snaps, as_of=as_of, **kwargs))


class TestOutputShape:
    @pytest.fixture
    def analysis(self) -> dict[str, Any]:
        snaps = [
            snapshot(
                "s1",
                "2026-09-01T08:00:00Z",
                [
                    posting(
                        "Acme Inc.",
                        "Senior Engineer (Remote)",
                        pid="1",
                        location="NYC",
                        work_mode="remote",
                        department="Eng",
                        url="https://x.test/1",
                        posted_at="2026-08-01",
                    ),
                    posting("Acme Inc.", "Sales Intern", pid="2"),
                ],
            ),
            snapshot(
                "s2",
                "2026-10-10T08:00:00Z",
                [
                    posting("ACME", "Senior Engineer", pid="1", location="NYC"),
                    posting("Acme", "Staff Engineer", pid="3"),
                ],
            ),
        ]
        return analyze(make_input(snaps, include=["engineer"], exclude=["intern"]))

    def test_top_level(self, analysis: dict[str, Any]) -> None:
        assert set(analysis) == {
            "as_of",
            "companies",
            "roles",
            "events",
            "merge_candidates",
            "stats",
        }
        assert analysis["as_of"] == AS_OF
        assert set(analysis["stats"]) == {
            "snapshots",
            "postings_observed",
            "companies",
            "active_roles",
        }

    def test_object_key_sets(self, analysis: dict[str, Any]) -> None:
        for comp in analysis["companies"]:
            assert set(comp) == COMPANY_KEYS
            assert [c["key"] for c in comp["components"]] == COMPONENT_ORDER
            for c in comp["components"]:
                assert set(c) == COMPONENT_KEYS
                assert set(c["inputs"]) == INPUT_KEYS[c["key"]]
        for role in analysis["roles"]:
            assert set(role) == ROLE_KEYS
            for obs in role["observations"]:
                assert set(obs) == OBSERVATION_KEYS
        for event in analysis["events"]:
            assert set(event) == EVENT_KEYS

    def test_values(self, analysis: dict[str, Any]) -> None:
        (acme,) = analysis["companies"]
        assert acme["key"] == "acme"
        assert acme["company_id"] == company_id_for("acme")
        assert acme["name"] == "Acme Inc."
        assert acme["aliases"] == ["ACME", "Acme", "Acme Inc."]
        assert acme["first_seen"] == "2026-09-01T08:00:00Z"
        assert acme["last_seen"] == "2026-10-10T08:00:00Z"
        assert (acme["active_roles"], acme["relevant_roles"], acme["removed_roles"]) == (2, 2, 1)
        assert acme["rank"] == 1
        assert acme["coverage"] == 90  # urgency is missing, never scored as zero
        weights = {c["key"]: c["weight"] for c in acme["components"]}
        assert weights == {
            "role_relevance": 30,
            "volume": 20,
            "change": 15,
            "urgency": 10,
            "source_confidence": 15,
            "freshness": 10,
        }
        # role_relevance 1000, volume 480, change 600 (Staff Engineer added; the removed intern
        # is out of scope by title), urgency missing (the later posting dropped posted_at and the
        # 39-day span is too short to age roles by first_seen), confidence 1000, freshness 1000
        assert [c["value"] for c in acme["components"]] == [1000, 480, 600, None, 1000, 1000]
        assert component(acme, "urgency")["reason_code"] == "no_dated_roles"
        # (30*1000 + 20*480 + 15*600 + 15*1000 + 10*1000) / 90 = 73600 / 90 = 817.8
        assert acme["score"] == 818
        assert analysis["stats"] == {
            "snapshots": 2,
            "postings_observed": 4,
            "companies": 1,
            "active_roles": 2,
        }

    def test_role_and_event_values(self, analysis: dict[str, Any]) -> None:
        by_title = {r["title"]: r for r in analysis["roles"]}
        senior = by_title["Senior Engineer"]
        assert senior["status"] == "active"
        assert senior["work_mode"] == "unknown"  # latest observation had no work_mode
        assert senior["relevant"] is True
        assert senior["posted_at"] is None  # the later posting no longer carries a date
        assert senior["age_days"] == 42  # so the age falls back to first_seen (Sep 1 08:00)
        assert senior["observations"] == [
            {
                "source_kind": "greenhouse",
                "source_ref": "acme",
                "source_posting_id": "1",
                "url": None,
                "status": "active",
                "first_seen": "2026-09-01T08:00:00Z",
                "last_seen": "2026-10-10T08:00:00Z",
            }
        ]
        intern = by_title["Sales Intern"]
        assert intern["status"] == "removed"
        assert intern["removed_at"] == "2026-10-10T08:00:00Z"
        assert intern["relevant"] is False
        assert [(e["type"], e["title"], e["fields"]) for e in analysis["events"]] == [
            ("baseline", "Senior Engineer (Remote)", None),
            ("baseline", "Sales Intern", None),
            (
                "changed",
                "Senior Engineer",
                ["department", "posted_at", "title", "url", "work_mode"],
            ),
            ("added", "Staff Engineer", None),
            ("removed", "Sales Intern", None),
        ]

    def test_output_is_plain_json(self, analysis: dict[str, Any]) -> None:
        assert json.loads(json.dumps(analysis)) == analysis

        def check(value: Any) -> None:
            assert type(value) in {dict, list, str, int, bool, type(None)}, type(value)
            if isinstance(value, dict):
                for key, item in value.items():
                    assert isinstance(key, str)
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)

        check(analysis)


class TestPurity:
    def test_deterministic_and_non_mutating(self) -> None:
        snaps = [
            snapshot("s1", "2026-09-01T08:00:00Z", [posting(pid="1", location="NYC")]),
            snapshot(
                "s2", "2026-10-01T08:00:00Z", [posting(pid="1", location="NYC"), posting(pid="2")]
            ),
        ]
        payload = make_input(snaps, include=["engineer"])
        before = copy.deepcopy(payload)
        first = analyze(payload)
        second = analyze(payload)
        assert first == second
        assert payload == before

    def test_input_order_of_snapshots_and_decisions_is_irrelevant(self) -> None:
        snaps = [
            snapshot("b", "2026-09-10T00:00:00Z", [posting("Acme Labs", pid="2")]),
            snapshot("a", "2026-09-10T00:00:00Z", [posting("Acme", pid="1")]),
            snapshot("c", "2026-09-01T00:00:00Z", [posting("Acme Labs", pid="9")], kind="lever"),
        ]
        decisions = [
            {"a_key": "acme", "b_key": "acme labs", "decision": "merge"},
            {"a_key": "x", "b_key": "y", "decision": "not_same"},
        ]
        forward = analyze(make_input(snaps, decisions=decisions))
        backward = analyze(make_input(snaps[::-1], decisions=decisions[::-1]))
        assert forward == backward


class TestOrdering:
    @pytest.fixture
    def analysis(self) -> dict[str, Any]:
        s1 = snapshot(
            "s1",
            "2026-10-01T00:00:00Z",
            [
                posting("Alpha", "Engineer", pid="1"),
                posting("Beta", "Engineer", pid="2"),
                posting("Zeta", "Engineer", pid="3"),
                posting("Zeta", "Designer", pid="4"),
                posting("Zeta", "Analyst", pid="5"),
                posting("Omega", "Engineer", pid="6"),
                posting("AAA Gone", "Engineer", pid="7"),
            ],
        )
        s2 = snapshot(
            "s2",
            "2026-10-02T00:00:00Z",
            [
                posting("Alpha", "Engineer", pid="1"),
                posting("Beta", "Engineer", pid="2"),
                posting("Zeta", "Engineer", pid="3"),
                posting("Zeta", "Designer", pid="4"),
                posting("Zeta", "Analyst", pid="5"),
            ],
        )
        return analyze(make_input([s1, s2], as_of="2026-10-03T00:00:00Z"))

    def test_ranked_then_unscored_by_key(self, analysis: dict[str, Any]) -> None:
        order = [(c["key"], c["rank"], c["score"]) for c in analysis["companies"]]
        # no keywords, no dated roles, span 1 day: volume + confidence + freshness only (W=45);
        # one role -> (20*300 + 15*1000 + 10*1000) / 45 = 689; three roles -> 37000 / 45 = 822
        assert order == [
            ("zeta", 1, 822),
            ("alpha", 2, 689),  # tie on score broken by key ascending
            ("beta", 3, 689),
            ("aaa gone", None, None),
            ("omega", None, None),
        ]

    def test_unscored_company_is_fully_null(self, analysis: dict[str, Any]) -> None:
        omega = company(analysis, "omega")
        assert omega["coverage"] == 0
        assert omega["last_seen"] is None
        assert omega["first_seen"] == "2026-10-01T00:00:00Z"
        assert (omega["active_roles"], omega["removed_roles"]) == (0, 1)
        assert omega["relevant_roles"] is None
        assert all(
            c["value"] is None and c["reason_code"] == "no_active_roles"
            for c in omega["components"]
        )
        assert component(omega, "change")["inputs"] == {
            "added": None,
            "removed": None,
            "net": None,
            "span_days": 1,
            "window_days": 30,
        }

    def test_roles_follow_company_order_then_status_then_first_seen(
        self, analysis: dict[str, Any]
    ) -> None:
        sequence = [(r["company_id"], r["status"]) for r in analysis["roles"]]
        company_order = [c["company_id"] for c in analysis["companies"]]
        indexes = [company_order.index(cid) for cid, _ in sequence]
        assert indexes == sorted(indexes)
        for cid in company_order:
            statuses = [s for c, s in sequence if c == cid]
            assert statuses == sorted(statuses, key=lambda s: 0 if s == "active" else 1)

    def test_roles_of_one_company_sort_by_first_seen_then_role_id(self) -> None:
        snaps = [
            snapshot(
                "s1",
                "2026-10-01T00:00:00Z",
                [posting(pid="1", title="B"), posting(pid="2", title="A")],
            ),
            snapshot(
                "s2",
                "2026-10-02T00:00:00Z",
                [
                    posting(pid="1", title="B"),
                    posting(pid="2", title="A"),
                    posting(pid="3", title="C"),
                ],
            ),
        ]
        result = analyze(make_input(snaps))
        rows = [(r["first_seen"], r["role_id"]) for r in result["roles"]]
        assert rows == sorted(rows)
        assert result["roles"][-1]["title"] == "C"


class TestChangeWindowEdges:
    @staticmethod
    def change_for_added_at(observed_at: str) -> dict[str, Any]:
        snaps = [
            snapshot("s0", "2026-08-01T00:00:00Z", [posting(pid="1", title="Engineer")]),
            snapshot(
                "s1",
                observed_at,
                [posting(pid="1", title="Engineer"), posting(pid="2", title="Designer")],
            ),
            snapshot(
                "s2",
                "2026-10-13T00:00:00Z",
                [posting(pid="1", title="Engineer"), posting(pid="2", title="Designer")],
            ),
        ]
        result = analyze(make_input(snaps))
        assert result["events"][1]["type"] == "added", (
            "the second event must be the Designer addition"
        )
        change: dict[str, Any] = component(company(result, "acme"), "change")
        return change

    def test_exactly_thirty_days_old_is_outside_the_window(self) -> None:
        change = self.change_for_added_at("2026-09-13T12:00:00Z")
        assert change["inputs"]["added"] == 0
        assert change["value"] == 500

    def test_one_second_younger_is_inside_the_window(self) -> None:
        change = self.change_for_added_at("2026-09-13T12:00:01Z")
        assert change["inputs"]["added"] == 1
        assert change["value"] == 600

    def test_one_second_older_is_outside_the_window(self) -> None:
        change = self.change_for_added_at("2026-09-13T11:59:59Z")
        assert change["inputs"]["added"] == 0

    def test_event_at_as_of_counts(self) -> None:
        snaps = [
            snapshot("s0", "2026-08-01T00:00:00Z", [posting(pid="1")]),
            snapshot("s1", AS_OF, [posting(pid="1"), posting(pid="2", title="Designer")]),
        ]
        result = analyze(make_input(snaps))
        assert component(company(result, "acme"), "change")["inputs"]["added"] == 1


class TestSpanBoundaries:
    def test_span_of_exactly_fourteen_days_is_enough(self) -> None:
        result = two_snapshot_company(
            "2026-09-20T00:00:00Z",
            "2026-10-04T00:00:00Z",
            extra_second=[posting(pid="2", title="Designer")],
        )
        change = component(company(result, "acme"), "change")
        assert change["reason_code"] is None
        assert change["inputs"] == {
            "added": 1,
            "removed": 0,
            "net": 1,
            "span_days": 14,
            "window_days": 30,
        }
        assert change["value"] == 600

    def test_thirteen_days_twentythree_hours_is_not(self) -> None:
        result = two_snapshot_company(
            "2026-09-20T00:00:00Z",
            "2026-10-03T23:59:59Z",
            extra_second=[posting(pid="2", title="Designer")],
        )
        change = component(company(result, "acme"), "change")
        assert change["value"] is None
        assert change["reason_code"] == "insufficient_history"
        assert change["inputs"] == {
            "added": None,
            "removed": None,
            "net": None,
            "span_days": 13,
            "window_days": 30,
        }

    def test_a_single_full_snapshot_has_no_span(self) -> None:
        result = analyze(make_input([snapshot("s", "2026-10-01T00:00:00Z", [posting(pid="1")])]))
        change = component(company(result, "acme"), "change")
        assert change["reason_code"] == "insufficient_history"
        assert change["inputs"]["span_days"] is None

    def test_additive_snapshots_do_not_contribute_to_the_span(self) -> None:
        snaps = [
            snapshot(
                "a", "2026-08-01T00:00:00Z", [posting()], kind="csv", ref="d", mode="additive"
            ),
            snapshot(
                "b", "2026-10-01T00:00:00Z", [posting()], kind="csv", ref="d", mode="additive"
            ),
        ]
        change = component(company(analyze(make_input(snaps)), "acme"), "change")
        assert change["inputs"]["span_days"] is None

    def test_two_full_snapshots_with_the_same_instant_give_a_zero_day_span(self) -> None:
        # |T| counts snapshots, so two of them at one instant is a span of 0 days (see the
        # ambiguity log); change is still insufficient because 0 < 14.
        snaps = [
            snapshot("a", "2026-10-01T00:00:00Z", [posting(pid="1")]),
            snapshot("b", "2026-10-01T00:00:00Z", [posting(pid="1")]),
        ]
        change = component(company(analyze(make_input(snaps)), "acme"), "change")
        assert change["reason_code"] == "insufficient_history"
        assert change["inputs"]["span_days"] == 0

    def test_span_uses_every_full_snapshot_of_every_supplying_source(self) -> None:
        snaps = [
            # greenhouse supplied a role to acme and was observed twice (Sep 1, Oct 1) ...
            snapshot(
                "g1", "2026-09-01T00:00:00Z", [posting("Acme", pid="1"), posting("Other", pid="2")]
            ),
            # ... the second time acme's role is no longer listed
            snapshot("g2", "2026-10-01T00:00:00Z", [posting("Other", pid="2")]),
            # a csv dataset keeps acme alive; additive snapshots are not part of T
            snapshot(
                "c1",
                "2026-10-05T00:00:00Z",
                [posting("Acme", title="Engineer")],
                kind="csv",
                ref="leads",
                mode="additive",
            ),
        ]
        result = analyze(make_input(snaps))
        acme = company(result, "acme")
        assert acme["active_roles"] == 1
        assert component(acme, "change")["inputs"]["span_days"] == 30
        other = company(result, "other")
        assert component(other, "change")["inputs"]["span_days"] == 30

    def test_sources_that_never_supplied_the_company_do_not_widen_the_span(self) -> None:
        snaps = [
            snapshot("g1", "2026-09-30T00:00:00Z", [posting("Acme", pid="1")]),
            snapshot("g2", "2026-10-01T00:00:00Z", [posting("Acme", pid="1")]),
            snapshot("l1", "2026-06-01T00:00:00Z", [posting("Elsewhere", pid="1")], kind="lever"),
            snapshot("l2", "2026-10-10T00:00:00Z", [posting("Elsewhere", pid="1")], kind="lever"),
        ]
        result = analyze(make_input(snaps))
        assert component(company(result, "acme"), "change")["inputs"]["span_days"] == 1


class TestUrgencyBoundaries:
    def test_posted_at_44_and_45_days(self) -> None:
        # as_of is 2026-10-13T12:00Z: 2026-08-30 is 44 days 12h old, 2026-08-29 is 45 days 12h.
        snaps = [
            snapshot(
                "s",
                "2026-10-01T00:00:00Z",
                [
                    posting(pid="1", title="Younger", posted_at="2026-08-30"),
                    posting(pid="2", title="Older", posted_at="2026-08-29"),
                ],
            )
        ]
        result = analyze(make_input(snaps))
        urgency = component(company(result, "acme"), "urgency")
        assert urgency["inputs"] == {"aged": 1, "known": 2, "threshold_days": 45}
        assert urgency["value"] == 500
        ages = {r["title"]: r["age_days"] for r in result["roles"]}
        assert ages == {"Younger": 44, "Older": 45}

    def test_first_seen_age_needs_a_45_day_span(self) -> None:
        snaps = [
            snapshot("s0", "2026-08-01T00:00:00Z", [posting(pid="1", title="One")]),
            snapshot(
                "s1",
                "2026-08-29T12:00:00Z",
                [posting(pid="1", title="One"), posting(pid="2", title="Two")],
            ),
            snapshot(
                "s2",
                "2026-08-30T12:00:00Z",
                [
                    posting(pid="1", title="One"),
                    posting(pid="2", title="Two"),
                    posting(pid="3", title="Three"),
                ],
            ),
            snapshot(
                "s3",
                "2026-10-01T00:00:00Z",
                [
                    posting(pid="1", title="One"),
                    posting(pid="2", title="Two"),
                    posting(pid="3", title="Three"),
                ],
            ),
        ]
        result = analyze(make_input(snaps))
        acme = company(result, "acme")
        assert component(acme, "change")["inputs"]["span_days"] == 61
        # first_seen ages at 2026-10-13T12:00Z: One 73d, Two 45d (aged), Three 44d (not aged)
        assert component(acme, "urgency")["inputs"] == {"aged": 2, "known": 3, "threshold_days": 45}
        assert component(acme, "urgency")["value"] == 667

    def test_span_of_44_days_leaves_undated_roles_unknown(self) -> None:
        result = two_snapshot_company("2026-08-30T00:00:00Z", "2026-10-13T00:00:00Z")
        change = component(company(result, "acme"), "change")
        assert change["inputs"]["span_days"] == 44
        urgency = component(company(result, "acme"), "urgency")
        assert urgency["reason_code"] == "no_dated_roles"
        assert urgency["value"] is None

    def test_span_of_45_days_makes_first_seen_usable(self) -> None:
        result = two_snapshot_company("2026-08-29T00:00:00Z", "2026-10-13T00:00:00Z")
        urgency = component(company(result, "acme"), "urgency")
        assert urgency["inputs"] == {"aged": 1, "known": 1, "threshold_days": 45}
        assert urgency["value"] == 1000


class TestFreshnessBoundaries:
    @pytest.mark.parametrize(
        ("observed_at", "days", "value"),
        [
            ("2026-10-13T12:00:00Z", 0, 1000),
            ("2026-10-06T12:00:00Z", 7, 1000),
            ("2026-10-05T12:00:01Z", 7, 1000),
            ("2026-10-05T12:00:00Z", 8, 981),
            ("2026-08-15T12:00:00Z", 59, 19),
            ("2026-08-14T12:00:01Z", 59, 19),
            ("2026-08-14T12:00:00Z", 60, 0),
            ("2026-01-01T00:00:00Z", 285, 0),
        ],
    )
    def test_curve_edges(self, observed_at: str, days: int, value: int) -> None:
        result = analyze(make_input([snapshot("s", observed_at, [posting(pid="1")])]))
        freshness = component(company(result, "acme"), "freshness")
        assert freshness["inputs"] == {"days_since_last_seen": days}
        assert freshness["value"] == value

    def test_freshness_uses_the_latest_listing_not_the_first(self) -> None:
        snaps = [
            snapshot("a", "2026-06-01T00:00:00Z", [posting(pid="1")]),
            snapshot("b", "2026-10-12T00:00:00Z", [posting(pid="1")]),
        ]
        freshness = component(company(analyze(make_input(snaps)), "acme"), "freshness")
        assert freshness["inputs"] == {"days_since_last_seen": 1}


class TestKeywords:
    def snaps(self) -> list[dict[str, Any]]:
        return [
            snapshot(
                "s",
                "2026-10-10T00:00:00Z",
                [
                    posting(pid="1", title="Software Engineer"),
                    posting(pid="2", title="Software Engineer Intern"),
                    posting(pid="3", title="Account Executive"),
                ],
            )
        ]

    def test_include_and_exclude(self) -> None:
        result = analyze(
            make_input(self.snaps(), include=["software engineer"], exclude=["intern"])
        )
        acme = company(result, "acme")
        assert (acme["active_roles"], acme["relevant_roles"]) == (3, 1)
        assert component(acme, "role_relevance")["value"] == 333
        assert component(acme, "role_relevance")["inputs"] == {"relevant": 1, "active": 3}
        relevance = {r["title"]: r["relevant"] for r in result["roles"]}
        assert relevance == {
            "Software Engineer": True,
            "Software Engineer Intern": False,
            "Account Executive": False,
        }
        assert component(acme, "volume")["inputs"] == {"scope_roles": 1}

    def test_no_keywords_gives_null_relevance(self) -> None:
        result = analyze(make_input(self.snaps()))
        acme = company(result, "acme")
        assert acme["relevant_roles"] is None
        assert all(r["relevant"] is None for r in result["roles"])
        relevance = component(acme, "role_relevance")
        assert (relevance["value"], relevance["reason_code"]) == (None, "no_keywords")
        assert relevance["inputs"] == {"relevant": None, "active": 3}
        assert component(acme, "volume")["inputs"] == {"scope_roles": 3}

    def test_exclude_only_profile_is_treated_as_no_keywords(self) -> None:
        result = analyze(make_input(self.snaps(), exclude=["intern"]))
        acme = company(result, "acme")
        assert acme["relevant_roles"] is None
        assert component(acme, "role_relevance")["reason_code"] == "no_keywords"
        assert component(acme, "volume")["inputs"] == {"scope_roles": 3}

    def test_matching_uses_the_displayed_title_of_the_canonical_role(self) -> None:
        snaps = [
            snapshot(
                "g",
                "2026-10-01T00:00:00Z",
                [posting(pid="1", title="Engineer (Platform)", location="NYC")],
            ),
            snapshot(
                "c",
                "2026-10-02T00:00:00Z",
                [posting(title="Engineer [Platform]", location="NYC")],
                kind="csv",
                ref="d",
                mode="additive",
            ),
        ]
        result = analyze(make_input(snaps, include=["engineer"]))
        (role,) = result["roles"]
        assert role["relevant"] is True
        assert role["title"] == "Engineer [Platform]"

    def test_keywords_configured_but_company_is_inactive(self) -> None:
        snaps = [
            snapshot("a", "2026-09-01T00:00:00Z", [posting(pid="1")]),
            snapshot("b", "2026-09-20T00:00:00Z", []),
        ]
        acme = company(analyze(make_input(snaps, include=["engineer"])), "acme")
        assert acme["relevant_roles"] == 0
        assert component(acme, "role_relevance")["inputs"] == {"relevant": None, "active": 0}

    def test_keyword_phrase_matching_is_normalized(self) -> None:
        snaps = [
            snapshot(
                "s", "2026-10-10T00:00:00Z", [posting(pid="1", title="Sr. Engineer, ML/AI (US)")]
            )
        ]
        result = analyze(make_input(snaps, include=["ML AI", "  ENGINEER!! "]))
        assert result["roles"][0]["relevant"] is True


class TestAdditiveAndSources:
    def test_source_confidence_through_corroboration(self) -> None:
        snaps = [
            snapshot("g", "2026-10-01T00:00:00Z", [posting(pid="1", location="NYC")]),
            snapshot(
                "c",
                "2026-10-02T00:00:00Z",
                [posting(location="NYC")],
                kind="csv",
                ref="d",
                mode="additive",
            ),
            snapshot(
                "m",
                "2026-10-03T00:00:00Z",
                [posting(title="Designer")],
                kind="manual",
                ref="manual",
                mode="additive",
            ),
        ]
        acme = company(analyze(make_input(snaps)), "acme")
        confidence = component(acme, "source_confidence")
        # Engineer: greenhouse+csv -> min(1000, 1100) = 1000, corroborated; Designer: manual 400
        assert confidence["inputs"] == {"scope_roles": 2, "corroborated": 1}
        assert confidence["value"] == 700

    def test_removed_observation_does_not_count_towards_confidence(self) -> None:
        snaps = [
            snapshot("g1", "2026-10-01T00:00:00Z", [posting(pid="1", location="NYC")]),
            snapshot("g2", "2026-10-02T00:00:00Z", []),
            snapshot(
                "c",
                "2026-10-03T00:00:00Z",
                [posting(location="NYC")],
                kind="csv",
                ref="d",
                mode="additive",
            ),
        ]
        acme = company(analyze(make_input(snaps)), "acme")
        confidence = component(acme, "source_confidence")
        assert confidence["inputs"] == {"scope_roles": 1, "corroborated": 0}
        assert confidence["value"] == 600  # only the csv observation is active

    def test_two_datasets_of_one_kind_corroborate_each_other(self) -> None:
        snaps = [
            snapshot(
                "c1", "2026-10-01T00:00:00Z", [posting()], kind="csv", ref="one", mode="additive"
            ),
            snapshot(
                "c2", "2026-10-02T00:00:00Z", [posting()], kind="csv", ref="two", mode="additive"
            ),
        ]
        confidence = component(company(analyze(make_input(snaps)), "acme"), "source_confidence")
        assert confidence["inputs"] == {"scope_roles": 1, "corroborated": 1}
        assert confidence["value"] == 700

    def test_roles_of_helper_matches_company_roles(self) -> None:
        snaps = [
            snapshot("s", "2026-10-01T00:00:00Z", [posting(pid="1"), posting("Other", pid="2")])
        ]
        result = analyze(make_input(snaps))
        for comp in result["companies"]:
            assert all(r["company_id"] == comp["company_id"] for r in roles_of(result, comp))
        assert len(events(result, "baseline")) == 2
