"""Snapshot replay and lifecycle events (spec 02 sections 2 and 3)."""

from __future__ import annotations

from typing import Any

from rr_engine_testkit import (
    company,
    events,
    make_input,
    posting,
    roles_of,
    snapshot,
)

from recruit_radar.engine import analyze


def event_summary(analysis: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(e["at"], e["type"], e["title"]) for e in analysis["events"]]


T1 = "2026-09-01T08:00:00Z"
T2 = "2026-09-10T08:00:00Z"
T3 = "2026-09-20T08:00:00Z"
T4 = "2026-10-01T08:00:00Z"


class TestBaselineAndAdded:
    def test_first_snapshot_of_a_source_is_its_baseline(self) -> None:
        result = analyze(
            make_input(
                [
                    snapshot("a", T1, [posting(pid="1", title="One")]),
                    snapshot(
                        "b", T2, [posting(pid="1", title="One"), posting(pid="2", title="Two")]
                    ),
                ]
            )
        )
        assert event_summary(result) == [(T1, "baseline", "One"), (T2, "added", "Two")]

    def test_each_source_has_its_own_baseline(self) -> None:
        result = analyze(
            make_input(
                [
                    snapshot("a", T1, [posting(pid="1", title="One")], ref="acme"),
                    snapshot("b", T2, [posting(pid="9", title="Nine")], kind="lever", ref="acme"),
                ]
            )
        )
        assert [(e["type"], e["source_kind"]) for e in result["events"]] == [
            ("baseline", "greenhouse"),
            ("baseline", "lever"),
        ]

    def test_additive_first_snapshot_is_still_the_baseline(self) -> None:
        result = analyze(
            make_input(
                [
                    snapshot("a", T1, [posting(title="One")], kind="csv", ref="d", mode="additive"),
                    snapshot("b", T2, [posting(title="Two")], kind="csv", ref="d", mode="additive"),
                ]
            )
        )
        assert [e["type"] for e in result["events"]] == ["baseline", "added"]

    def test_processing_order_is_observed_at_then_snapshot_id_not_input_order(self) -> None:
        snaps = [
            snapshot("z", T2, [posting(pid="3", title="Three")]),
            snapshot("a", T2, [posting(pid="2", title="Two")]),
            snapshot("m", T1, [posting(pid="1", title="One")]),
        ]
        result = analyze(make_input(snaps))
        # m (T1) is the baseline. At T2 "a" sorts before "z": "a" adds Two and removes One,
        # then "z" adds Three and removes Two. Within a snapshot additions precede removals.
        assert event_summary(result) == [
            (T1, "baseline", "One"),
            (T2, "added", "Two"),
            (T2, "removed", "One"),
            (T2, "added", "Three"),
            (T2, "removed", "Two"),
        ]
        assert analyze(make_input(list(reversed(snaps)))) == result


class TestChanged:
    def test_changed_fields_are_sorted_and_use_the_new_title(self) -> None:
        old = posting(
            title="Engineer",
            pid="1",
            location="NYC",
            department="Eng",
            url="https://x.test/1",
            posted_at="2026-08-01",
            work_mode="onsite",
        )
        new = posting(
            title="Staff Engineer",
            pid="1",
            location="Remote",
            department="Platform",
            url="https://x.test/2",
            posted_at="2026-08-02",
            work_mode="remote",
        )
        result = analyze(make_input([snapshot("a", T1, [old]), snapshot("b", T2, [new])]))
        (changed,) = events(result, "changed")
        assert changed["fields"] == [
            "department",
            "location",
            "posted_at",
            "title",
            "url",
            "work_mode",
        ]
        assert changed["title"] == "Staff Engineer"
        assert changed["at"] == T2

    def test_null_versus_null_is_not_a_change(self) -> None:
        a = posting(pid="1", title="Engineer")
        result = analyze(make_input([snapshot("a", T1, [a]), snapshot("b", T2, [dict(a)])]))
        assert events(result, "changed") == []

    def test_null_to_value_and_back_is_a_change(self) -> None:
        snaps = [
            snapshot("a", T1, [posting(pid="1", location=None)]),
            snapshot("b", T2, [posting(pid="1", location="Berlin")]),
            snapshot("c", T3, [posting(pid="1", location=None)]),
        ]
        result = analyze(make_input(snaps))
        assert [e["fields"] for e in events(result, "changed")] == [["location"], ["location"]]

    def test_whitespace_only_difference_is_not_a_change(self) -> None:
        snaps = [
            snapshot("a", T1, [posting(pid="1", title="Engineer", location="NYC")]),
            snapshot("b", T2, [posting(pid="1", title="  Engineer ", location=" NYC")]),
        ]
        assert events(analyze(make_input(snaps)), "changed") == []

    def test_unchanged_role_updates_last_seen_only(self) -> None:
        snaps = [
            snapshot("a", T1, [posting(pid="1")]),
            snapshot("b", T3, [posting(pid="1")]),
        ]
        result = analyze(make_input(snaps))
        (role,) = result["roles"]
        assert role["first_seen"] == T1
        assert role["last_seen"] == T3
        assert [e["type"] for e in result["events"]] == ["baseline"]

    def test_company_name_is_not_a_tracked_field(self) -> None:
        snaps = [
            snapshot("a", T1, [posting("Acme", pid="1")]),
            snapshot("b", T2, [posting("ACME Inc.", pid="1")]),
        ]
        assert events(analyze(make_input(snaps)), "changed") == []

    def test_key_based_role_title_case_change_is_reported(self) -> None:
        # same title_key, different raw title: same source role key, so "changed", not add+remove
        snaps = [
            snapshot(
                "a", T1, [posting(title="Senior Engineer")], kind="csv", ref="d", mode="additive"
            ),
            snapshot(
                "b", T2, [posting(title="SENIOR ENGINEER")], kind="csv", ref="d", mode="additive"
            ),
        ]
        result = analyze(make_input(snaps))
        assert [e["type"] for e in result["events"]] == ["baseline", "changed"]
        assert events(result, "changed")[0]["fields"] == ["title"]


class TestRemovalAndReappearance:
    def test_full_snapshot_removes_missing_roles_in_key_order(self) -> None:
        snaps = [
            snapshot(
                "a",
                T1,
                [
                    posting(pid="b", title="B"),
                    posting(pid="c", title="C"),
                    posting(pid="a", title="A"),
                ],
            ),
            snapshot("b", T2, [posting(pid="c", title="C")]),
        ]
        result = analyze(make_input(snaps))
        removed = events(result, "removed")
        assert [e["title"] for e in removed] == ["A", "B"]  # ascending source role key
        assert all(e["at"] == T2 for e in removed)
        roles = {r["title"]: r for r in result["roles"]}
        assert roles["A"]["status"] == "removed"
        assert roles["A"]["removed_at"] == T2
        assert roles["A"]["last_seen"] == T1
        assert roles["C"]["status"] == "active"

    def test_additive_snapshot_never_removes(self) -> None:
        snaps = [
            snapshot("a", T1, [posting(pid="1"), posting(pid="2", title="Two")]),
            snapshot("b", T2, [posting(pid="1")], mode="additive"),
        ]
        result = analyze(make_input(snaps))
        assert events(result, "removed") == []
        assert all(r["status"] == "active" for r in result["roles"])

    def test_removal_event_title_is_the_title_at_removal_time(self) -> None:
        snaps = [
            snapshot("a", T1, [posting(pid="1", title="Old Title")]),
            snapshot("b", T2, [posting(pid="1", title="New Title")]),
            snapshot("c", T3, []),
        ]
        result = analyze(make_input(snaps))
        assert events(result, "removed")[0]["title"] == "New Title"

    def test_reappearance_reactivates_and_clears_removed_at(self) -> None:
        snaps = [
            snapshot("a", T1, [posting(pid="1", title="One", location="NYC")]),
            snapshot("b", T2, []),
            snapshot("c", T3, [posting(pid="1", title="One v2", location="Berlin")]),
        ]
        result = analyze(make_input(snaps))
        assert [e["type"] for e in result["events"]] == ["baseline", "removed", "reappeared"]
        reappeared = events(result, "reappeared")[0]
        assert reappeared["title"] == "One v2"
        assert reappeared["fields"] is None  # reappeared carries no field list
        (role,) = result["roles"]
        assert role["status"] == "active"
        assert role["removed_at"] is None
        assert role["first_seen"] == T1
        assert role["last_seen"] == T3
        assert role["title"] == "One v2"
        assert role["location"] == "Berlin"

    def test_additive_snapshot_can_reappear_a_role(self) -> None:
        snaps = [
            snapshot("a", T1, [posting(pid="1")]),
            snapshot("b", T2, []),
            snapshot("c", T3, [posting(pid="1")], mode="additive"),
        ]
        assert [e["type"] for e in analyze(make_input(snaps))["events"]] == [
            "baseline",
            "removed",
            "reappeared",
        ]

    def test_removed_is_independent_per_source(self) -> None:
        snaps = [
            snapshot("g1", T1, [posting(pid="1")], kind="greenhouse", ref="acme"),
            snapshot("l1", T1, [posting(pid="1")], kind="lever", ref="acme"),
            snapshot("g2", T2, [], kind="greenhouse", ref="acme"),
        ]
        result = analyze(make_input(snaps))
        (role,) = result["roles"]
        assert role["status"] == "active"  # the lever observation keeps it alive
        statuses = {o["source_kind"]: o["status"] for o in role["observations"]}
        assert statuses == {"greenhouse": "removed", "lever": "active"}

    def test_empty_full_snapshot_is_a_baseline_with_no_events(self) -> None:
        result = analyze(make_input([snapshot("a", T1, [])]))
        assert result["events"] == []
        assert result["stats"]["snapshots"] == 1


class TestWithinSnapshot:
    def test_last_duplicate_wins_without_events(self) -> None:
        snaps = [
            snapshot(
                "a",
                T1,
                [
                    posting(pid="1", title="First"),
                    posting(pid="2", title="Other"),
                    posting(pid="1", title="Second"),
                ],
            )
        ]
        result = analyze(make_input(snaps))
        # distinct keys in order of last occurrence: id 2 (index 1) then id 1 (index 2)
        assert event_summary(result) == [(T1, "baseline", "Other"), (T1, "baseline", "Second")]
        assert result["stats"]["postings_observed"] == 3
        assert {r["title"] for r in result["roles"]} == {"Other", "Second"}

    def test_key_based_duplicates_collapse(self) -> None:
        snaps = [
            snapshot(
                "a",
                T1,
                [
                    posting("Acme", "Engineer (Remote)", location="NYC"),
                    posting("ACME Inc.", "engineer", location="nyc"),
                ],
                kind="csv",
                ref="d",
                mode="additive",
            )
        ]
        result = analyze(make_input(snaps))
        (role,) = result["roles"]
        assert role["title"] == "engineer"  # last one wins
        assert [e["type"] for e in result["events"]] == ["baseline"]


class TestSnapshotsAfterAsOf:
    def test_future_snapshots_are_ignored_entirely(self) -> None:
        snaps = [
            snapshot("a", T1, [posting(pid="1")]),
            snapshot("b", "2026-10-13T12:00:01Z", [posting(pid="2", title="Late")]),
            snapshot("c", "2027-01-01T00:00:00Z", []),
        ]
        result = analyze(make_input(snaps))
        assert result["stats"] == {
            "snapshots": 1,
            "postings_observed": 1,
            "companies": 1,
            "active_roles": 1,
        }
        assert [e["title"] for e in result["events"]] == ["Engineer"]

    def test_snapshot_exactly_at_as_of_is_included(self) -> None:
        snaps = [snapshot("a", "2026-10-13T12:00:00Z", [posting(pid="1")])]
        assert analyze(make_input(snaps))["stats"]["snapshots"] == 1

    def test_future_snapshot_does_not_remove_roles(self) -> None:
        snaps = [
            snapshot("a", T1, [posting(pid="1")]),
            snapshot("b", "2026-11-01T00:00:00Z", []),
        ]
        (role,) = analyze(make_input(snaps))["roles"]
        assert role["status"] == "active"


class TestCanonicalRoleAggregation:
    def test_status_active_if_any_member_active(self) -> None:
        snaps = [
            snapshot("g1", T1, [posting(pid="1", location="NYC")]),
            snapshot("g2", T2, []),
            snapshot("c", T3, [posting(location="NYC")], kind="csv", ref="d", mode="additive"),
        ]
        result = analyze(make_input(snaps))
        (role,) = result["roles"]
        assert role["status"] == "active"
        assert role["removed_at"] is None
        assert role["first_seen"] == T1
        assert role["last_seen"] == T3  # max over *active* members only
        assert company(result, "acme")["removed_roles"] == 0

    def test_removed_canonical_role_has_latest_removed_at_and_last_seen(self) -> None:
        snaps = [
            snapshot("g1", T1, [posting(pid="1")], ref="acme"),
            snapshot("l1", T1, [posting(pid="x")], kind="lever", ref="acme"),
            snapshot("g2", T2, [], ref="acme"),
            snapshot("l2", T3, [], kind="lever", ref="acme"),
        ]
        result = analyze(make_input(snaps))
        (role,) = result["roles"]
        assert role["status"] == "removed"
        assert role["removed_at"] == T3  # max member removed_at
        assert role["last_seen"] == T1  # all members considered when none is active

    def test_posted_at_is_the_earliest_non_null(self) -> None:
        snaps = [
            snapshot("g", T1, [posting(pid="1", posted_at="2026-08-10")]),
            snapshot("l", T1, [posting(pid="x", posted_at="2026-08-01")], kind="lever", ref="acme"),
            snapshot("c", T1, [posting()], kind="csv", ref="d", mode="additive"),
        ]
        (role,) = analyze(make_input(snaps))["roles"]
        assert role["posted_at"] == "2026-08-01"

    def test_display_fields_come_from_the_member_seen_most_recently(self) -> None:
        snaps = [
            snapshot(
                "g", T1, [posting(pid="1", title="Engineer", location="NYC", work_mode="onsite")]
            ),
            snapshot(
                "c",
                T2,
                [posting(title="engineer", location="nyc", work_mode="remote")],
                kind="csv",
                ref="d",
                mode="additive",
            ),
        ]
        (role,) = analyze(make_input(snaps))["roles"]
        assert (role["title"], role["location"], role["work_mode"]) == ("engineer", "nyc", "remote")

    def test_display_tie_goes_to_the_smallest_source_role_key(self) -> None:
        snaps = [
            snapshot("g", T1, [posting(pid="1", title="Engineer", work_mode="onsite")]),
            snapshot(
                "c",
                T1,
                [posting(title="ENGINEER", work_mode="remote")],
                kind="csv",
                ref="d",
                mode="additive",
            ),
        ]
        (role,) = analyze(make_input(snaps))["roles"]
        # "csv|d|k|..." sorts before "greenhouse|acme|id|1"
        assert (role["title"], role["work_mode"]) == ("ENGINEER", "remote")

    def test_age_days_uses_posted_at_else_first_seen(self) -> None:
        snaps = [
            snapshot("a", "2026-10-03T12:00:00Z", [posting(pid="1", posted_at="2026-09-13")]),
            snapshot("b", "2026-10-03T12:00:00Z", [posting(pid="2", title="Other")], ref="other"),
        ]
        result = analyze(make_input(snaps))
        ages = {r["title"]: r["age_days"] for r in result["roles"]}
        assert ages == {"Engineer": 30, "Other": 10}

    def test_age_days_clamps_future_posted_at_to_zero(self) -> None:
        snaps = [snapshot("a", T1, [posting(pid="1", posted_at="2026-12-31")])]
        (role,) = analyze(make_input(snaps))["roles"]
        assert role["age_days"] == 0

    def test_events_reference_the_canonical_role(self) -> None:
        snaps = [
            snapshot("g", T1, [posting(pid="1", location="NYC")]),
            snapshot("c", T2, [posting(location="NYC")], kind="csv", ref="d", mode="additive"),
        ]
        result = analyze(make_input(snaps))
        (role,) = result["roles"]
        assert {e["role_id"] for e in result["events"]} == {role["role_id"]}
        acme = company(result, "acme")
        assert roles_of(result, acme) == [role]
