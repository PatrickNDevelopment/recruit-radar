"""Unit tests of scoring.py against hand-computed values (spec 02 section 4)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from recruit_radar.engine.scoring import (
    COMPONENT_WEIGHTS,
    VOLUME_VALUES,
    CompanyScore,
    Keywords,
    ScoringEvent,
    ScoringRole,
    freshness_value,
    rhu,
    role_age_days,
    role_confidence,
    score_company,
)
from recruit_radar.engine.timeutil import timestamp_to_epoch

AS_OF = "2026-10-13T12:00:00Z"
AS_OF_EPOCH = timestamp_to_epoch(AS_OF)
NO_KEYWORDS = Keywords.build([], [])
GH = ("greenhouse", "acme")


def role(
    *,
    active: bool = True,
    relevant: bool | None = None,
    posted_at: str | None = None,
    first_seen: str = "2026-10-01T00:00:00Z",
    last_seen: str = "2026-10-12T00:00:00Z",
    sources: Sequence[tuple[str, str]] = (GH,),
) -> ScoringRole:
    return ScoringRole(
        active=active,
        relevant=relevant,
        posted_at=posted_at,
        first_seen=first_seen,
        last_seen=last_seen,
        active_sources=tuple(sources) if active else (),
    )


def score(
    roles: Sequence[ScoringRole],
    *,
    events: Sequence[ScoringEvent] = (),
    keywords: Keywords = NO_KEYWORDS,
    span_days: int | None = None,
) -> CompanyScore:
    return score_company(
        roles=roles,
        events=events,
        keywords=keywords,
        span_days=span_days,
        as_of_epoch=AS_OF_EPOCH,
    )


def comp(result: CompanyScore, key: str) -> Any:
    return next(c for c in result.components if c.key == key)


class TestRoundHalfUp:
    @pytest.mark.parametrize(
        ("num", "den", "expected"),
        [
            (0, 5, 0),
            (1, 2, 1),  # exactly one half rounds up
            (1, 3, 0),
            (2, 3, 1),
            (5, 5, 1),
            (2000, 3, 667),
            (1000, 3, 333),
            (3, 2, 2),  # 1.5 -> 2
            (5, 2, 3),  # 2.5 -> 3
            (7, 4, 2),  # 1.75
            (36999, 100, 370),  # 369.99
            (37049, 100, 370),  # 370.49
            (37050, 100, 371),  # 370.50
        ],
    )
    def test_values(self, num: int, den: int, expected: int) -> None:
        assert rhu(num, den) == expected


class TestStaticTables:
    def test_weights_sum_to_one_hundred_in_fixed_order(self) -> None:
        assert [k for k, _ in COMPONENT_WEIGHTS] == [
            "role_relevance",
            "volume",
            "change",
            "urgency",
            "source_confidence",
            "freshness",
        ]
        assert dict(COMPONENT_WEIGHTS) == {
            "role_relevance": 30,
            "volume": 20,
            "change": 15,
            "urgency": 10,
            "source_confidence": 15,
            "freshness": 10,
        }
        assert sum(w for _, w in COMPONENT_WEIGHTS) == 100

    def test_volume_table(self) -> None:
        assert VOLUME_VALUES == (0, 300, 480, 600, 690, 760, 820, 870, 910, 950, 1000)

    @pytest.mark.parametrize(
        ("scope", "value"),
        [(0, 0), (1, 300), (3, 600), (10, 1000), (11, 1000), (500, 1000)],
    )
    def test_volume_saturates_at_ten(self, scope: int, value: int) -> None:
        keywords = Keywords.build(["x"], [])
        if scope == 0:
            roles = [role(relevant=False)]  # active, but nothing is in scope
        else:
            roles = [role(relevant=True) for _ in range(scope)]
        result = score(roles, keywords=keywords)
        assert comp(result, "volume").value == value
        assert comp(result, "volume").inputs == {"scope_roles": scope}


class TestFreshness:
    @pytest.mark.parametrize(
        ("days", "value"),
        [
            (0, 1000),
            (6, 1000),
            (7, 1000),
            (8, 981),
            (30, 566),
            (52, 151),
            (59, 19),
            (60, 0),
            (61, 0),
            (400, 0),
        ],
    )
    def test_curve(self, days: int, value: int) -> None:
        assert freshness_value(days) == value

    @pytest.mark.parametrize(
        ("last_seen", "days", "value"),
        [
            ("2026-10-06T12:00:00Z", 7, 1000),  # exactly 7 days
            ("2026-10-05T12:00:01Z", 7, 1000),  # 7d 23:59:59 floors to 7
            ("2026-10-05T12:00:00Z", 8, 981),
            ("2026-08-15T12:00:00Z", 59, 19),
            ("2026-08-14T12:00:00Z", 60, 0),
            ("2026-01-01T00:00:00Z", 285, 0),
            ("2026-10-13T12:00:00Z", 0, 1000),
        ],
    )
    def test_through_score_company(self, last_seen: str, days: int, value: int) -> None:
        result = score([role(last_seen=last_seen)])
        freshness = comp(result, "freshness")
        assert freshness.inputs == {"days_since_last_seen": days}
        assert freshness.value == value

    def test_uses_the_most_recent_last_seen_of_active_roles_only(self) -> None:
        result = score(
            [
                role(last_seen="2026-08-01T00:00:00Z"),
                role(last_seen="2026-10-12T00:00:00Z"),
                role(active=False, last_seen="2026-10-13T00:00:00Z"),
            ]
        )
        assert comp(result, "freshness").inputs == {"days_since_last_seen": 1}

    def test_future_last_seen_clamps_to_zero(self) -> None:
        result = score([role(last_seen="2026-12-01T00:00:00Z")])
        assert comp(result, "freshness").inputs == {"days_since_last_seen": 0}


class TestRoleAge:
    def test_posted_at_wins(self) -> None:
        assert (
            role_age_days("2026-09-13", "2026-10-12T00:00:00Z", AS_OF_EPOCH, allow_first_seen=False)
            == 30
        )

    def test_first_seen_only_when_allowed(self) -> None:
        assert (
            role_age_days(None, "2026-09-13T12:00:00Z", AS_OF_EPOCH, allow_first_seen=False) is None
        )
        assert role_age_days(None, "2026-09-13T12:00:00Z", AS_OF_EPOCH, allow_first_seen=True) == 30

    def test_negative_clamps_to_zero(self) -> None:
        assert (
            role_age_days("2026-12-31", "2026-10-12T00:00:00Z", AS_OF_EPOCH, allow_first_seen=False)
            == 0
        )


class TestRoleConfidence:
    @pytest.mark.parametrize(
        ("sources", "expected"),
        [
            ([("greenhouse", "a")], (1000, False)),
            ([("lever", "a")], (1000, False)),
            ([("ashby", "a")], (1000, False)),
            ([("csv", "d")], (600, False)),
            ([("manual", "manual")], (400, False)),
            ([("csv", "d"), ("manual", "manual")], (700, True)),  # 600 + 100
            ([("manual", "manual"), ("csv", "d")], (700, True)),
            ([("greenhouse", "a"), ("csv", "d")], (1000, True)),  # capped at 1000
            ([("greenhouse", "a"), ("lever", "a")], (1000, True)),
            ([("csv", "one"), ("csv", "two")], (700, True)),  # same kind, different dataset
        ],
    )
    def test_values(self, sources: list[tuple[str, str]], expected: tuple[int, bool]) -> None:
        assert role_confidence(sources) == expected

    def test_same_source_twice_is_not_corroboration(self) -> None:
        assert role_confidence([("csv", "d"), ("csv", "d")]) == (600, False)


class TestKeywords:
    def test_not_configured_when_include_is_empty(self) -> None:
        assert not Keywords.build([], ["intern"]).configured
        assert Keywords.build(["engineer"], []).configured
        assert Keywords.build([""], []).configured  # configured, but can never match

    def test_matches_whole_token_runs_case_insensitively(self) -> None:
        keywords = Keywords.build(["Software Engineer", "ml"], ["intern", "staff engineer"])
        assert keywords.matches("senior software engineer")
        assert keywords.matches("ml scientist")
        assert not keywords.matches("software developer")
        assert not keywords.matches("html designer")  # "ml" is a token, not a substring
        assert not keywords.matches("software engineer intern")
        assert not keywords.matches("ml staff engineer")
        assert keywords.matches("ml engineering staff")

    def test_blank_phrases_never_match(self) -> None:
        assert not Keywords.build([""], []).matches("engineer")
        assert not Keywords.build(["---"], []).matches("engineer")
        # a blank exclude phrase excludes nothing
        assert Keywords.build(["engineer"], [""]).matches("engineer")


class TestNullComponentsAndInputs:
    def test_no_active_roles_nulls_everything(self) -> None:
        result = score([role(active=False)], span_days=20)
        assert result.score is None
        assert result.coverage == 0
        assert [c.key for c in result.components] == [k for k, _ in COMPONENT_WEIGHTS]
        assert all(
            c.value is None and c.reason_code == "no_active_roles" for c in result.components
        )
        assert comp(result, "role_relevance").inputs == {"relevant": None, "active": 0}
        assert comp(result, "volume").inputs == {"scope_roles": 0}
        assert comp(result, "change").inputs == {
            "added": None,
            "removed": None,
            "net": None,
            "span_days": 20,
            "window_days": 30,
        }
        assert comp(result, "urgency").inputs == {
            "aged": None,
            "known": None,
            "threshold_days": 45,
        }
        assert comp(result, "source_confidence").inputs == {"scope_roles": 0, "corroborated": None}
        assert comp(result, "freshness").inputs == {"days_since_last_seen": None}

    def test_no_active_roles_with_unknown_span(self) -> None:
        result = score([], span_days=None)
        assert comp(result, "change").inputs["span_days"] is None
        assert result.score is None

    def test_no_active_roles_beats_insufficient_history(self) -> None:
        result = score([role(active=False)], span_days=3)
        assert comp(result, "change").reason_code == "no_active_roles"

    def test_no_keywords(self) -> None:
        result = score([role(), role(), role()])
        relevance = comp(result, "role_relevance")
        assert relevance.value is None
        assert relevance.reason_code == "no_keywords"
        assert relevance.inputs == {"relevant": None, "active": 3}
        # without keywords the scope is every active role
        assert comp(result, "volume").value == 600
        assert comp(result, "volume").inputs == {"scope_roles": 3}

    def test_keywords_but_no_relevant_role(self) -> None:
        result = score(
            [role(relevant=False), role(relevant=False)],
            keywords=Keywords.build(["engineer"], []),
        )
        assert comp(result, "role_relevance").value == 0
        assert comp(result, "role_relevance").inputs == {"relevant": 0, "active": 2}
        assert comp(result, "volume").value == 0
        assert comp(result, "volume").reason_code is None
        urgency = comp(result, "urgency")
        assert (urgency.value, urgency.reason_code) == (None, "no_scope_roles")
        assert urgency.inputs == {"aged": 0, "known": 0, "threshold_days": 45}
        confidence = comp(result, "source_confidence")
        assert (confidence.value, confidence.reason_code) == (None, "no_scope_roles")
        assert confidence.inputs == {"scope_roles": 0, "corroborated": 0}
        # role_relevance 0, volume 0, change n/a, urgency n/a, confidence n/a, freshness 1000
        assert result.coverage == 30 + 20 + 10
        assert result.score == rhu(30 * 0 + 20 * 0 + 10 * 1000, 60)  # 167

    def test_no_dated_roles(self) -> None:
        result = score([role(), role()], span_days=10)
        urgency = comp(result, "urgency")
        assert (urgency.value, urgency.reason_code) == (None, "no_dated_roles")
        assert urgency.inputs == {"aged": 0, "known": 0, "threshold_days": 45}

    def test_insufficient_history(self) -> None:
        for span in (None, 0, 13):
            result = score([role()], span_days=span)
            change = comp(result, "change")
            assert (change.value, change.reason_code) == (None, "insufficient_history")
            assert change.inputs == {
                "added": None,
                "removed": None,
                "net": None,
                "span_days": span,
                "window_days": 30,
            }


class TestChange:
    @staticmethod
    def ev(
        kind: str, at: str = "2026-10-01T00:00:00Z", title_key: str = "engineer"
    ) -> ScoringEvent:
        return ScoringEvent(at=at, type=kind, title_key=title_key)

    def test_counts_added_reappeared_removed_only(self) -> None:
        events = [
            self.ev("added"),
            self.ev("reappeared"),
            self.ev("removed"),
            self.ev("baseline"),
            self.ev("changed"),
        ]
        change = comp(score([role()], events=events, span_days=14), "change")
        assert change.inputs == {
            "added": 2,
            "removed": 1,
            "net": 1,
            "span_days": 14,
            "window_days": 30,
        }
        assert change.value == 600

    @pytest.mark.parametrize(
        ("net_added", "net_removed", "value"),
        [
            (0, 0, 500),
            (1, 0, 600),
            (5, 0, 1000),
            (6, 0, 1000),
            (0, 4, 100),
            (0, 5, 0),
            (0, 9, 0),
            (3, 3, 500),
        ],
    )
    def test_value_is_clamped(self, net_added: int, net_removed: int, value: int) -> None:
        events = [self.ev("added")] * net_added + [self.ev("removed")] * net_removed
        assert comp(score([role()], events=events, span_days=20), "change").value == value

    @pytest.mark.parametrize(
        ("at", "counted"),
        [
            ("2026-09-13T11:59:59Z", False),  # 30d + 1s old
            ("2026-09-13T12:00:00Z", False),  # exactly 30d old: the window is open at the start
            ("2026-09-13T12:00:01Z", True),
            ("2026-10-13T11:59:59Z", True),
            ("2026-10-13T12:00:00Z", True),  # as_of itself is inside the window
        ],
    )
    def test_window_edges(self, at: str, counted: bool) -> None:
        change = comp(score([role()], events=[self.ev("added", at)], span_days=20), "change")
        assert change.inputs["added"] == (1 if counted else 0)

    def test_events_are_filtered_by_title_when_keywords_are_configured(self) -> None:
        keywords = Keywords.build(["engineer"], ["intern"])
        events = [
            self.ev("added", title_key="software engineer"),
            self.ev("added", title_key="engineer intern"),  # excluded
            self.ev("added", title_key="account executive"),  # not an include match
            self.ev("removed", title_key="staff engineer"),
        ]
        change = comp(
            score([role(relevant=True)], events=events, keywords=keywords, span_days=30), "change"
        )
        assert change.inputs["added"] == 1
        assert change.inputs["removed"] == 1

    def test_every_event_counts_without_keywords(self) -> None:
        events = [self.ev("added", title_key="whatever"), self.ev("added", title_key="")]
        change = comp(score([role()], events=events, span_days=30), "change")
        assert change.inputs["added"] == 2

    def test_exclude_only_profile_is_not_configured(self) -> None:
        keywords = Keywords.build([], ["intern"])
        events = [self.ev("added", title_key="intern")]
        change = comp(score([role()], events=events, keywords=keywords, span_days=30), "change")
        assert change.inputs["added"] == 1  # still "no keywords configured"


class TestUrgency:
    def test_threshold_is_45_days(self) -> None:
        # as_of 2026-10-13T12:00Z: 2026-08-30 is 44d12h old, 2026-08-29 is 45d12h old.
        result = score([role(posted_at="2026-08-30"), role(posted_at="2026-08-29")])
        urgency = comp(result, "urgency")
        assert urgency.inputs == {"aged": 1, "known": 2, "threshold_days": 45}
        assert urgency.value == 500

    def test_exact_boundaries_in_whole_days(self) -> None:
        for posted, aged in [("2026-08-30", 0), ("2026-08-29", 1)]:
            urgency = comp(score([role(posted_at=posted)]), "urgency")
            assert urgency.inputs["aged"] == aged

    @pytest.mark.parametrize(("span", "known"), [(None, 0), (30, 0), (44, 0), (45, 1), (400, 1)])
    def test_first_seen_is_used_only_with_a_45_day_span(self, span: int | None, known: int) -> None:
        result = score([role(first_seen="2026-08-01T00:00:00Z")], span_days=span)
        assert comp(result, "urgency").inputs["known"] == known

    def test_posted_at_is_preferred_over_first_seen(self) -> None:
        result = score(
            [role(posted_at="2026-10-10", first_seen="2026-01-01T00:00:00Z")], span_days=100
        )
        assert comp(result, "urgency").inputs == {"aged": 0, "known": 1, "threshold_days": 45}
        assert comp(result, "urgency").value == 0

    def test_only_scope_roles_count(self) -> None:
        keywords = Keywords.build(["engineer"], [])
        result = score(
            [
                role(relevant=True, posted_at="2026-01-01"),
                role(relevant=False, posted_at="2026-01-01"),
                role(relevant=True, posted_at="2026-10-01"),
            ],
            keywords=keywords,
        )
        assert comp(result, "urgency").inputs == {"aged": 1, "known": 2, "threshold_days": 45}

    def test_future_posted_at_is_known_but_not_aged(self) -> None:
        result = score([role(posted_at="2027-01-01")])
        assert comp(result, "urgency").inputs == {"aged": 0, "known": 1, "threshold_days": 45}


class TestSourceConfidence:
    def test_average_with_round_half_up_and_corroboration(self) -> None:
        roles = [
            role(sources=[("greenhouse", "acme")]),  # 1000
            role(sources=[("csv", "d")]),  # 600
            role(sources=[("manual", "manual"), ("csv", "d")]),  # 400/600 -> 700, corroborated
        ]
        confidence = comp(score(roles), "source_confidence")
        assert confidence.inputs == {"scope_roles": 3, "corroborated": 1}
        assert confidence.value == rhu(1000 + 600 + 700, 3)  # 767

    def test_only_active_observations_count(self) -> None:
        # the caller passes active sources only, so a removed greenhouse observation is absent
        result = score([role(sources=[("csv", "d")])])
        assert comp(result, "source_confidence").value == 600


class TestOverall:
    def test_hand_computed_company(self) -> None:
        roles = [
            role(posted_at="2026-08-14", sources=[("greenhouse", "acme")]),  # 60d old
            role(posted_at="2026-10-01", sources=[("csv", "d")], last_seen="2026-10-05T00:00:00Z"),
            role(sources=[("manual", "manual")], last_seen="2026-09-01T00:00:00Z"),  # undated
        ]
        result = score(roles, span_days=None)
        values = {c.key: c.value for c in result.components}
        assert values == {
            "role_relevance": None,
            "volume": 600,
            "change": None,
            "urgency": 500,
            "source_confidence": 667,
            "freshness": 1000,
        }
        assert result.coverage == 20 + 10 + 15 + 10
        assert result.score == 673  # (20*600 + 10*500 + 15*667 + 10*1000) / 55 = 672.8

    def test_fully_computed_company(self) -> None:
        keywords = Keywords.build(["engineer"], [])
        roles = [
            role(
                relevant=True,
                posted_at="2026-08-01",
                sources=[("greenhouse", "acme"), ("csv", "d")],
            ),
            role(relevant=True, posted_at="2026-10-10", sources=[("greenhouse", "acme")]),
            role(relevant=False, sources=[("greenhouse", "acme")]),
        ]
        events = [
            ScoringEvent("2026-10-10T00:00:00Z", "added", "engineer"),
            ScoringEvent("2026-10-11T00:00:00Z", "added", "senior engineer"),
            ScoringEvent("2026-10-12T00:00:00Z", "removed", "engineer"),
            ScoringEvent("2026-10-12T00:00:00Z", "added", "recruiter"),  # not in scope
        ]
        result = score(roles, events=events, keywords=keywords, span_days=40)
        values = {c.key: c.value for c in result.components}
        assert values == {
            "role_relevance": 667,  # rhu(2000, 3)
            "volume": 480,  # two relevant roles
            "change": 600,  # added 2, removed 1
            "urgency": 500,  # one of two aged
            "source_confidence": 1000,  # (1000 + 1000) / 2 with one corroborated (capped)
            "freshness": 1000,
        }
        assert result.coverage == 100
        # (30*667 + 20*480 + 15*600 + 10*500 + 15*1000 + 10*1000) / 100 = 68610 / 100 = 686.1
        assert result.score == 686

    def test_score_stays_within_range_at_extremes(self) -> None:
        best = score(
            [
                role(
                    relevant=True,
                    posted_at="2026-01-01",
                    sources=[("greenhouse", "a"), ("csv", "d")],
                )
            ]
            * 10,
            keywords=Keywords.build(["x"], []),
            events=[ScoringEvent("2026-10-12T00:00:00Z", "added", "x")] * 9,
            span_days=100,
        )
        assert best.score == 1000
        worst = score(
            [role(relevant=False, posted_at="2026-10-01", last_seen="2025-01-01T00:00:00Z")],
            keywords=Keywords.build(["x"], []),
            span_days=100,
        )
        assert worst.score is not None and 0 <= worst.score <= 1000
