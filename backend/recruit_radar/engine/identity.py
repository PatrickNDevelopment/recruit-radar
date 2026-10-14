"""Company identity, merge candidates and canonical role dedup (spec 01 sections 3 and 4)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Final

from .models import ParsedDecision
from .normalize import levenshtein, sha12

REASON_SPACING_VARIANT: Final = "spacing_variant"
REASON_TOKEN_OVERLAP: Final = "token_overlap"
REASON_NEAR_TYPO: Final = "near_typo"
REASON_ORDER: Final = (REASON_SPACING_VARIANT, REASON_TOKEN_OVERLAP, REASON_NEAR_TYPO)

NEAR_TYPO_MIN_CODE_POINTS: Final = 6


# ---------------------------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------------------------
def company_id_for(canonical_key: str) -> str:
    """``"c_" + sha12(canonical_key)``."""
    return "c_" + sha12(canonical_key)


def role_id_for(company_id: str, title_key: str, location_key: str, index: int) -> str:
    """``"r_" + sha12(company_id|title_key|location_key|index)``."""
    return "r_" + sha12(f"{company_id}|{title_key}|{location_key}|{index}")


def candidate_id_for(a_key: str, b_key: str) -> str:
    """``sha12(a_key + "|" + b_key)``."""
    return sha12(a_key + "|" + b_key)


# ---------------------------------------------------------------------------------------------
# Merge decisions
# ---------------------------------------------------------------------------------------------
def resolve_canonical_keys(
    present_keys: Collection[str], decisions: Iterable[ParsedDecision]
) -> dict[str, str]:
    """Map every company key in ``present_keys`` to the canonical key of its merge group.

    ``merge`` decisions are unioned transitively (union-find). The canonical key of a group is
    its lexicographically smallest *member* key (spec 01 section 3.3): every key a ``merge``
    decision names is a member, including a key no posting currently has (a stale decision), so
    such a key can be canonical. Keeping that literal reading is what makes the Python and
    TypeScript engines and the oracle agree (``docs/spec/ambiguities/differential.md`` D-3).

    The union always attaches the larger root under the smaller one, so a root is always the
    smallest member of its group and no separate "smallest" pass is needed.
    """
    parent: dict[str, str] = {}

    def find(item: str) -> str:
        root = item
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(item, item) != root:
            following = parent[item]
            parent[item] = root
            item = following
        return root

    for decision in decisions:
        if decision.decision != "merge":
            continue
        root_a, root_b = find(decision.a_key), find(decision.b_key)
        if root_a == root_b:
            continue
        if root_a < root_b:
            parent[root_b] = root_a
        else:
            parent[root_a] = root_b

    return {key: find(key) for key in present_keys}


def not_same_pairs(decisions: Iterable[ParsedDecision]) -> frozenset[tuple[str, str]]:
    """``(a_key, b_key)`` pairs the user marked as ``not_same``."""
    return frozenset((d.a_key, d.b_key) for d in decisions if d.decision == "not_same")


# ---------------------------------------------------------------------------------------------
# Merge candidates
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MergeCandidate:
    candidate_id: str
    a_key: str
    b_key: str
    a_name: str
    b_name: str
    reason: str


def _ordered(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def candidate_reason(a: str, b: str) -> str | None:
    """First matching candidate reason for two distinct keys, or ``None`` (spec 01 section 3).

    This is the direct, quadratic-friendly statement of the rule; :func:`find_merge_candidates`
    uses indexes to avoid comparing every pair and is checked against this function.
    """
    if a == b:
        return None
    if a.replace(" ", "") == b.replace(" ", ""):
        return REASON_SPACING_VARIANT
    tokens_a, tokens_b = a.split(" "), b.split(" ")
    if len(tokens_a) >= 2 and len(tokens_b) >= 2:
        set_a, set_b = set(tokens_a), set(tokens_b)
        if len(set_a & set_b) * 100 >= 75 * len(set_a | set_b):
            return REASON_TOKEN_OVERLAP
    if (
        len(a) >= NEAR_TYPO_MIN_CODE_POINTS
        and len(b) >= NEAR_TYPO_MIN_CODE_POINTS
        and levenshtein(a, b) <= 1
    ):
        return REASON_NEAR_TYPO
    return None


def _one_deletion_variants(key: str) -> set[str]:
    return {key[:i] + key[i + 1 :] for i in range(len(key))}


def find_merge_candidates(
    display_names: Mapping[str, str], not_same: AbstractSet[tuple[str, str]]
) -> list[MergeCandidate]:
    """Merge candidates between the distinct (post-merge canonical) company keys.

    ``display_names`` maps each canonical company key to its display name. A pair is reported
    with the first matching reason (spacing_variant, token_overlap, near_typo) unless it is
    marked ``not_same``. Results are sorted by (reason order, a_key, b_key).
    """
    keys = sorted(display_names)
    best_reason: dict[tuple[str, str], int] = {}

    def note(a: str, b: str, reason: str) -> None:
        pair = _ordered(a, b)
        rank = REASON_ORDER.index(reason)
        if rank < best_reason.get(pair, len(REASON_ORDER)):
            best_reason[pair] = rank

    # spacing_variant: equal once every space is removed.
    by_squashed: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        by_squashed[key.replace(" ", "")].append(key)
    for group in by_squashed.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                note(a, b, REASON_SPACING_VARIANT)

    # token_overlap: both have >= 2 tokens and |A n B| * 100 >= 75 * |A u B| over token sets.
    # Such a pair always shares at least one token, so an inverted index finds every pair.
    token_sets: dict[str, frozenset[str]] = {}
    postings: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        parts = key.split(" ")
        if len(parts) >= 2:
            members = frozenset(parts)
            token_sets[key] = members
            for token in members:
                postings[token].append(key)
    for key, members in token_sets.items():
        shared: dict[str, int] = defaultdict(int)
        for token in members:
            for other in postings[token]:
                if other > key:
                    shared[other] += 1
        for other, common in shared.items():
            union = len(members) + len(token_sets[other]) - common
            if common * 100 >= 75 * union:
                note(key, other, REASON_TOKEN_OVERLAP)

    # near_typo: both >= 6 code points and Levenshtein distance <= 1. Two such keys share the
    # key itself or a one-character deletion of it, so bucket by those and verify exactly.
    buckets: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        if len(key) >= NEAR_TYPO_MIN_CODE_POINTS:
            for variant in _one_deletion_variants(key) | {key}:
                buckets[variant].append(key)
    verified: set[tuple[str, str]] = set()
    for bucket in buckets.values():
        for i, a in enumerate(bucket):
            for b in bucket[i + 1 :]:
                pair = _ordered(a, b)
                if pair in verified:
                    continue
                verified.add(pair)
                if abs(len(a) - len(b)) <= 1 and levenshtein(a, b) <= 1:
                    note(a, b, REASON_NEAR_TYPO)

    candidates = [
        MergeCandidate(
            candidate_id=candidate_id_for(a, b),
            a_key=a,
            b_key=b,
            a_name=display_names[a],
            b_name=display_names[b],
            reason=REASON_ORDER[rank],
        )
        for (a, b), rank in best_reason.items()
        if (a, b) not in not_same
    ]
    candidates.sort(key=lambda c: (REASON_ORDER.index(c.reason), c.a_key, c.b_key))
    return candidates


# ---------------------------------------------------------------------------------------------
# Canonical role dedup
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RoleGroupItem:
    """What role dedup needs to know about one source role."""

    ident: int
    company_id: str
    title_key: str
    location_key: str
    source: tuple[str, str]
    key_str: str
    key: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CanonicalGroup:
    company_id: str
    title_key: str
    location_key: str
    index: int
    role_id: str
    members: tuple[int, ...]
    """``ident`` of every member source role, ordered by ascending ``(source_kind, source_ref)``."""


def group_canonical_roles(items: Sequence[RoleGroupItem]) -> list[CanonicalGroup]:
    """Dedup source roles into canonical roles (spec 01 section 4).

    Within one ``(company, title_key, location_key)`` group each source's role keys are sorted
    ascending; canonical role ``i`` takes the ``i``-th role of every source holding at least
    ``i + 1`` of them, so two headcounts of one source stay two roles while the same opening
    reported by several sources collapses into one.
    """
    groups: dict[tuple[str, str, str], dict[tuple[str, str], list[RoleGroupItem]]] = {}
    for item in items:
        by_source = groups.setdefault((item.company_id, item.title_key, item.location_key), {})
        by_source.setdefault(item.source, []).append(item)

    result: list[CanonicalGroup] = []
    for (company_id, title_key, location_key), by_source in groups.items():
        for members in by_source.values():
            members.sort(key=lambda m: (m.key_str, m.key))
        depth = max(len(members) for members in by_source.values())
        for index in range(depth):
            picked = tuple(
                by_source[source][index].ident
                for source in sorted(by_source)
                if len(by_source[source]) > index
            )
            result.append(
                CanonicalGroup(
                    company_id=company_id,
                    title_key=title_key,
                    location_key=location_key,
                    index=index,
                    role_id=role_id_for(company_id, title_key, location_key, index),
                    members=picked,
                )
            )
    return result
