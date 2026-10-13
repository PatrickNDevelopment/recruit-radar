"""Company identity, merge candidates and canonical role dedup (spec 01 sections 3-5)."""

from __future__ import annotations

import itertools
import random

import pytest
from rr_engine_testkit import (
    company,
    events,
    make_input,
    posting,
    roles_of,
    snapshot,
)

from recruit_radar.engine import analyze
from recruit_radar.engine.identity import (
    RoleGroupItem,
    candidate_id_for,
    candidate_reason,
    company_id_for,
    find_merge_candidates,
    group_canonical_roles,
    resolve_canonical_keys,
    role_id_for,
)
from recruit_radar.engine.models import ParsedDecision
from recruit_radar.engine.normalize import sha12


def merge(a: str, b: str) -> ParsedDecision:
    return ParsedDecision(a, b, "merge")


def not_same(a: str, b: str) -> ParsedDecision:
    return ParsedDecision(a, b, "not_same")


class TestIds:
    def test_company_id(self) -> None:
        assert company_id_for("acme") == "c_" + sha12("acme")

    def test_role_id_format(self) -> None:
        cid = company_id_for("acme")
        assert role_id_for(cid, "engineer", "new york", 0) == "r_" + sha12(
            f"{cid}|engineer|new york|0"
        )
        assert role_id_for(cid, "engineer", "", 1) != role_id_for(cid, "engineer", "", 0)

    def test_candidate_id(self) -> None:
        assert candidate_id_for("door dash", "doordash") == sha12("door dash|doordash")


class TestResolveCanonicalKeys:
    def test_no_decisions_is_identity(self) -> None:
        assert resolve_canonical_keys({"a", "b"}, []) == {"a": "a", "b": "b"}

    def test_merge_uses_smallest_member(self) -> None:
        assert resolve_canonical_keys(
            {"acme", "acme robotics"}, [merge("acme", "acme robotics")]
        ) == {
            "acme": "acme",
            "acme robotics": "acme",
        }
        assert resolve_canonical_keys({"x", "y"}, [merge("x", "y")]) == {"x": "x", "y": "x"}

    def test_transitive(self) -> None:
        decisions = [merge("b", "c"), merge("a", "b"), merge("d", "e")]
        result = resolve_canonical_keys({"a", "b", "c", "d", "e", "f"}, decisions)
        assert result == {"a": "a", "b": "a", "c": "a", "d": "d", "e": "d", "f": "f"}

    def test_decision_order_does_not_matter(self) -> None:
        decisions = [merge("a", "b"), merge("b", "c"), merge("c", "d"), merge("e", "f")]
        keys = {"a", "b", "c", "d", "e", "f"}
        baseline = resolve_canonical_keys(keys, decisions)
        for _ in range(20):
            shuffled = decisions[:]
            random.Random(len(keys)).shuffle(shuffled)
            assert resolve_canonical_keys(keys, shuffled) == baseline

    def test_not_same_never_merges(self) -> None:
        assert resolve_canonical_keys({"a", "b"}, [not_same("a", "b")]) == {"a": "a", "b": "b"}

    def test_canonical_key_is_always_a_present_key(self) -> None:
        # "a" appears only in a decision; it must not become the group's canonical key.
        result = resolve_canonical_keys({"b", "c"}, [merge("a", "b"), merge("a", "c")])
        assert result == {"b": "b", "c": "b"}

    def test_merge_through_an_absent_key_is_still_transitive(self) -> None:
        result = resolve_canonical_keys({"a", "c"}, [merge("a", "b"), merge("b", "c")])
        assert result == {"a": "a", "c": "a"}


class TestCandidateReason:
    @pytest.mark.parametrize(
        ("a", "b", "reason"),
        [
            # spacing_variant outranks near_typo for a pair that satisfies both (distance 1)
            ("doordash", "door dash", "spacing_variant"),
            ("new relic", "newrelic", "spacing_variant"),
            ("a b c", "ab c", "spacing_variant"),
            # token overlap: |A n B| * 100 >= 75 * |A u B|, both with >= 2 tokens
            ("acme robotics labs", "acme robotics labs europe", "token_overlap"),  # 3/4 = 75%
            ("a b c d", "a b c e", "near_typo"),  # 3/5 = 60% overlap, but one substitution apart
            ("alpha beta gamma delta", "alpha beta gamma omega", None),  # 3/5 = 60%
            ("acme robotics", "acme robotics group", None),  # 2/3 = 66.7%
            ("one two", "two one", "token_overlap"),  # same token sets, 100%
            ("acme robotics", "acme robotic", "near_typo"),  # spec example
            ("abcdef", "abcdeg", "near_typo"),  # 6 code points, one substitution
            ("abcdef", "abcdf", None),  # second key has only 5 code points
            ("abcde", "abcdf", None),  # both only 5 code points
            ("abcdef", "abcxxf", None),  # distance 2
            ("acme", "acme", None),  # identical keys are never a candidate
            ("acme", "globex", None),
            ("", "acme", None),
            # a single shared token is not enough for overlap, and "x y" has two tokens only:
            ("alpha beta", "alpha gamma", None),  # 1/3
        ],
    )
    def test_reasons(self, a: str, b: str, reason: str | None) -> None:
        assert candidate_reason(a, b) == reason
        assert candidate_reason(b, a) == reason

    def test_token_overlap_needs_two_tokens_on_both_sides(self) -> None:
        # "acme" has 1 token, so token_overlap is not applicable; neither is near_typo (4 chars).
        assert candidate_reason("acme", "acme labs") is None


class TestFindMergeCandidates:
    def test_sorted_by_reason_then_keys(self) -> None:
        names = {
            "doordash": "DoorDash",
            "door dash": "Door Dash",
            "acme robotics": "Acme Robotics",
            "acme robotic": "Acme Robotic",
            "one two": "One Two",
            "two one": "Two One",
            "newrelic": "NewRelic",
            "new relic": "New Relic",
        }
        found = find_merge_candidates(names, frozenset())
        assert [(c.reason, c.a_key, c.b_key) for c in found] == [
            ("spacing_variant", "door dash", "doordash"),
            ("spacing_variant", "new relic", "newrelic"),
            ("token_overlap", "one two", "two one"),
            ("near_typo", "acme robotic", "acme robotics"),
        ]
        first = found[0]
        assert first.a_name == "Door Dash"
        assert first.b_name == "DoorDash"
        assert first.candidate_id == sha12("door dash|doordash")

    def test_not_same_suppresses_exactly_that_pair(self) -> None:
        names = {
            "doordash": "DoorDash",
            "door dash": "Door Dash",
            "acme robotics": "A",
            "acme robotic": "B",
        }
        found = find_merge_candidates(names, {("door dash", "doordash")})
        assert [(c.a_key, c.b_key) for c in found] == [("acme robotic", "acme robotics")]

    def test_matches_the_direct_rule_on_random_keys(self) -> None:
        rng = random.Random(20261013)
        words = ["acme", "labs", "robotics", "group", "data", "cloud", "ai", "x", "ab", "abc"]
        for _ in range(60):
            keys: set[str] = set()
            for _ in range(rng.randint(2, 40)):
                keys.add(" ".join(rng.choice(words) for _ in range(rng.randint(1, 4))))
            if rng.random() < 0.5:
                # add typo variants and spacing variants of existing keys
                for key in list(keys)[:5]:
                    if len(key) > 3:
                        cut = rng.randrange(len(key))
                        keys.add(key[:cut] + key[cut + 1 :])
                        keys.add(key.replace(" ", "", 1))
                        keys.add(key[:cut] + "z" + key[cut:])
            keys.discard("")
            expected = {}
            for a, b in itertools.combinations(sorted(keys), 2):
                reason = candidate_reason(a, b)
                if reason is not None:
                    expected[(a, b)] = reason
            found = find_merge_candidates({k: k.title() for k in keys}, frozenset())
            assert {(c.a_key, c.b_key): c.reason for c in found} == expected
            assert all(c.a_key < c.b_key for c in found)


class TestGroupCanonicalRoles:
    @staticmethod
    def item(
        ident: int,
        source: tuple[str, str],
        key_tail: str,
        *,
        company: str = "c_x",
        title: str = "engineer",
        location: str = "",
    ) -> RoleGroupItem:
        key = (*source, "id", key_tail)
        return RoleGroupItem(ident, company, title, location, source, "|".join(key), key)

    def test_same_source_roles_are_never_merged(self) -> None:
        gh = ("greenhouse", "acme")
        groups = group_canonical_roles([self.item(0, gh, "1"), self.item(1, gh, "2")])
        assert [g.members for g in groups] == [(0,), (1,)]
        assert [g.index for g in groups] == [0, 1]
        assert groups[0].role_id != groups[1].role_id

    def test_cross_source_roles_pair_up_by_sorted_key(self) -> None:
        gh, csv = ("greenhouse", "acme"), ("csv", "ds")
        groups = group_canonical_roles(
            [
                self.item(0, gh, "2"),
                self.item(1, gh, "1"),
                self.item(2, csv, "b"),
            ]
        )
        by_index = {g.index: g.members for g in groups}
        # greenhouse sorted: id 1 (ident 1), id 2 (ident 0); csv has one role -> pairs with index 0
        assert by_index == {0: (2, 1), 1: (0,)}  # sources ascending: csv before greenhouse

    def test_different_company_title_or_location_do_not_group(self) -> None:
        gh, csv = ("greenhouse", "acme"), ("csv", "ds")
        groups = group_canonical_roles(
            [
                self.item(0, gh, "1"),
                self.item(1, csv, "1", title="designer"),
                self.item(2, csv, "2", location="berlin"),
                self.item(3, csv, "3", company="c_y"),
            ]
        )
        assert sorted(g.members for g in groups) == [(0,), (1,), (2,), (3,)]

    def test_role_id_uses_group_index(self) -> None:
        gh = ("greenhouse", "acme")
        groups = group_canonical_roles([self.item(0, gh, "1"), self.item(1, gh, "2")])
        assert groups[1].role_id == role_id_for("c_x", "engineer", "", 1)


class TestSpecConsequences:
    """The five bullet points of spec 01 section 5, end to end."""

    def test_spelling_variants_are_one_company_and_roles_dedup(self) -> None:
        snaps = [
            snapshot("g", "2026-10-01T00:00:00Z", [posting("Acme", "Engineer", pid="1")]),
            snapshot(
                "c1",
                "2026-10-02T00:00:00Z",
                [posting("ACME Inc.", "Engineer")],
                kind="csv",
                ref="one",
                mode="additive",
            ),
            snapshot(
                "c2",
                "2026-10-03T00:00:00Z",
                [posting("acme, inc", "Engineer")],
                kind="csv",
                ref="two",
                mode="additive",
            ),
        ]
        result = analyze(make_input(snaps))
        assert result["stats"]["companies"] == 1
        assert result["stats"]["postings_observed"] == 3
        acme = company(result, "acme")
        assert acme["active_roles"] == 1
        assert acme["aliases"] == ["ACME Inc.", "Acme", "acme, inc"]
        assert acme["name"] == "Acme"  # earliest observed posting
        (role,) = roles_of(result, acme)
        assert len(role["observations"]) == 3

    def test_doordash_spacing_variant_is_a_candidate_not_a_merge(self) -> None:
        snaps = [
            snapshot(
                "s",
                "2026-10-01T00:00:00Z",
                [
                    posting("DoorDash", "Engineer", pid="1"),
                    posting("Door Dash", "Engineer", pid="2"),
                ],
            ),
        ]
        result = analyze(make_input(snaps))
        assert result["stats"]["companies"] == 2
        assert result["merge_candidates"] == [
            {
                "candidate_id": sha12("door dash|doordash"),
                "a_key": "door dash",
                "b_key": "doordash",
                "a_name": "Door Dash",
                "b_name": "DoorDash",
                "reason": "spacing_variant",
            }
        ]

    def test_merging_the_candidate_collapses_the_companies(self) -> None:
        snaps = [
            snapshot(
                "s",
                "2026-10-01T00:00:00Z",
                [
                    posting("DoorDash", "Engineer", pid="1"),
                    posting("Door Dash", "Engineer", pid="2"),
                ],
            ),
        ]
        decision = {"a_key": "door dash", "b_key": "doordash", "decision": "merge"}
        result = analyze(make_input(snaps, decisions=[decision]))
        assert result["stats"]["companies"] == 1
        assert result["merge_candidates"] == []
        merged = company(result, "door dash")
        assert merged["company_id"] == company_id_for("door dash")
        assert merged["aliases"] == ["Door Dash", "DoorDash"]
        # both roles are the same title/location from the same source: two headcounts
        assert merged["active_roles"] == 2

    def test_near_typo_candidate(self) -> None:
        snaps = [
            snapshot(
                "s",
                "2026-10-01T00:00:00Z",
                [
                    posting("Acme Robotics", "Engineer", pid="1"),
                    posting("Acme Robotic", "Engineer", pid="2"),
                ],
            ),
        ]
        result = analyze(make_input(snaps))
        (cand,) = result["merge_candidates"]
        assert (cand["a_key"], cand["b_key"], cand["reason"]) == (
            "acme robotic",
            "acme robotics",
            "near_typo",
        )

    def test_not_same_hides_the_candidate_but_not_exact_equality(self) -> None:
        snaps = [
            snapshot(
                "s",
                "2026-10-01T00:00:00Z",
                [
                    posting("DoorDash", "Engineer", pid="1"),
                    posting("Door Dash", "Engineer", pid="2"),
                    posting("DOORDASH INC", "Designer", pid="3"),
                ],
            ),
        ]
        decision = {"a_key": "door dash", "b_key": "doordash", "decision": "not_same"}
        result = analyze(make_input(snaps, decisions=[decision]))
        assert result["merge_candidates"] == []
        assert result["stats"]["companies"] == 2  # DoorDash and DOORDASH INC are still equal

    def test_same_source_identical_roles_are_two_headcounts(self) -> None:
        snaps = [
            snapshot(
                "s",
                "2026-10-01T00:00:00Z",
                [
                    posting("Acme", "Engineer", pid="100", location="NYC"),
                    posting("Acme", "Engineer", pid="101", location="NYC"),
                ],
            )
        ]
        result = analyze(make_input(snaps))
        acme = company(result, "acme")
        assert acme["active_roles"] == 2
        assert len({r["role_id"] for r in result["roles"]}) == 2

    def test_same_role_in_board_and_csv_is_one_role_two_observations(self) -> None:
        snaps = [
            snapshot(
                "g", "2026-10-01T00:00:00Z", [posting("Acme", "Engineer", pid="9", location="NYC")]
            ),
            snapshot(
                "c",
                "2026-10-02T00:00:00Z",
                [posting("Acme", "Engineer", location="NYC")],
                kind="csv",
                ref="leads",
                mode="additive",
            ),
        ]
        result = analyze(make_input(snaps))
        (role,) = result["roles"]
        assert [(o["source_kind"], o["source_ref"]) for o in role["observations"]] == [
            ("csv", "leads"),
            ("greenhouse", "acme"),
        ]
        assert role["role_id"] == role_id_for(company_id_for("acme"), "engineer", "nyc", 0)

    def test_merge_applies_to_history(self) -> None:
        # Events recorded under the old company key are attributed to the merged company.
        snaps = [
            snapshot("s1", "2026-09-01T00:00:00Z", [posting("Acme Labs", "Engineer", pid="1")]),
            snapshot(
                "s2",
                "2026-10-01T00:00:00Z",
                [posting("Acme Labs", "Engineer", pid="1"), posting("Acme", "Designer", pid="2")],
            ),
        ]
        decision = {"a_key": "acme", "b_key": "acme labs", "decision": "merge"}
        result = analyze(make_input(snaps, decisions=[decision]))
        acme = company(result, "acme")
        assert {e["company_id"] for e in events(result)} == {acme["company_id"]}
        assert acme["active_roles"] == 2

    def test_company_assignment_follows_the_latest_company_name(self) -> None:
        snaps = [
            snapshot("s1", "2026-09-01T00:00:00Z", [posting("Old Name", "Engineer", pid="1")]),
            snapshot("s2", "2026-10-01T00:00:00Z", [posting("New Name", "Engineer", pid="1")]),
        ]
        result = analyze(make_input(snaps))
        assert [c["key"] for c in result["companies"]] == ["new name"]
        assert events(result, "changed") == []  # company_name is not a tracked field
        assert result["companies"][0]["aliases"] == ["New Name", "Old Name"]
        assert result["companies"][0]["name"] == "Old Name"  # earliest observed posting
