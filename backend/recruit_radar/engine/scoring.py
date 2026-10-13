"""Per-company priority score (spec 02 section 4).

Pure integer arithmetic. Components that cannot be computed are ``None`` with a ``reason_code``
and are excluded from the overall score and from ``coverage``; they are never scored as zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from .normalize import contains_token_sequence, tokens
from .timeutil import SECONDS_PER_DAY, date_to_epoch, days_between, timestamp_to_epoch

WINDOW_DAYS: Final = 30
WINDOW_SECONDS: Final = WINDOW_DAYS * SECONDS_PER_DAY
MIN_SPAN_DAYS_FOR_CHANGE: Final = 14
URGENCY_THRESHOLD_DAYS: Final = 45
FRESH_FULL_SCORE_DAYS: Final = 7
FRESH_ZERO_SCORE_DAYS: Final = 60

COMPONENT_WEIGHTS: Final[tuple[tuple[str, int], ...]] = (
    ("role_relevance", 30),
    ("volume", 20),
    ("change", 15),
    ("urgency", 10),
    ("source_confidence", 15),
    ("freshness", 10),
)

VOLUME_VALUES: Final = (0, 300, 480, 600, 690, 760, 820, 870, 910, 950, 1000)

SOURCE_WEIGHTS: Final[dict[str, int]] = {
    "greenhouse": 1000,
    "lever": 1000,
    "ashby": 1000,
    "csv": 600,
    "manual": 400,
}
CORROBORATION_BONUS: Final = 100

COUNTED_EVENT_TYPES: Final = frozenset({"added", "reappeared", "removed"})

InputValue = int | None


def rhu(num: int, den: int) -> int:
    """Round half up for non-negative integers: ``floor((2*num + den) / (2*den))``."""
    return (2 * num + den) // (2 * den)


@dataclass(frozen=True, slots=True)
class Keywords:
    """The role profile, pre-normalized into token runs."""

    include: tuple[tuple[str, ...], ...]
    exclude: tuple[tuple[str, ...], ...]

    @classmethod
    def build(cls, include: Sequence[str], exclude: Sequence[str]) -> Keywords:
        return cls(
            include=tuple(tuple(tokens(phrase)) for phrase in include),
            exclude=tuple(tuple(tokens(phrase)) for phrase in exclude),
        )

    @property
    def configured(self) -> bool:
        """Keywords are configured iff the include list is non-empty (spec 02 sections 3, 4)."""
        return len(self.include) > 0

    def matches(self, title_key: str) -> bool:
        """Some include phrase matches ``title_key`` and no exclude phrase does."""
        haystack = title_key.split(" ")
        if not any(contains_token_sequence(haystack, phrase) for phrase in self.include):
            return False
        return not any(contains_token_sequence(haystack, phrase) for phrase in self.exclude)


@dataclass(frozen=True, slots=True)
class ScoringRole:
    """A canonical role, as far as scoring is concerned."""

    active: bool
    relevant: bool | None
    posted_at: str | None
    first_seen: str
    last_seen: str
    active_sources: tuple[tuple[str, str], ...]
    """``(source_kind, source_ref)`` of every *active* observation of the role."""


@dataclass(frozen=True, slots=True)
class ScoringEvent:
    at: str
    type: str
    title_key: str


@dataclass(frozen=True, slots=True)
class Component:
    key: str
    weight: int
    value: int | None
    reason_code: str | None
    inputs: dict[str, InputValue]


@dataclass(frozen=True, slots=True)
class CompanyScore:
    components: tuple[Component, ...]
    coverage: int
    score: int | None


def role_age_days(
    posted_at: str | None, first_seen: str, as_of_epoch: int, *, allow_first_seen: bool
) -> int | None:
    """Age of a role in whole days, clamped at 0, or ``None`` when it is unknown.

    ``posted_at`` wins when present. Otherwise the age is measured from ``first_seen`` only when
    ``allow_first_seen`` says the observation history is long enough to trust that.
    """
    if posted_at is not None:
        return max(0, days_between(date_to_epoch(posted_at), as_of_epoch))
    if allow_first_seen:
        return max(0, days_between(timestamp_to_epoch(first_seen), as_of_epoch))
    return None


def freshness_value(days_since_last_seen: int) -> int:
    """1000 within 7 days, 0 from 60 days, linear (round half up) in between."""
    if days_since_last_seen <= FRESH_FULL_SCORE_DAYS:
        return 1000
    if days_since_last_seen >= FRESH_ZERO_SCORE_DAYS:
        return 0
    return rhu(1000 * (FRESH_ZERO_SCORE_DAYS - days_since_last_seen), 53)


def role_confidence(active_sources: Sequence[tuple[str, str]]) -> tuple[int, bool]:
    """``(role_conf, corroborated)`` for one role from its active observations."""
    best = max(SOURCE_WEIGHTS[kind] for kind, _ in active_sources)
    if len(set(active_sources)) >= 2:
        return min(1000, best + CORROBORATION_BONUS), True
    return best, False


def score_company(
    *,
    roles: Sequence[ScoringRole],
    events: Sequence[ScoringEvent],
    keywords: Keywords,
    span_days: int | None,
    as_of_epoch: int,
) -> CompanyScore:
    """Compute the six components, coverage and overall score of one company.

    ``roles`` are all canonical roles of the company; ``events`` all lifecycle events of those
    roles; ``span_days`` is the observation span of the company's full snapshots (or ``None``).
    """
    active = [role for role in roles if role.active]
    active_count = len(active)
    relevant = [role for role in active if role.relevant is True]
    scope = relevant if keywords.configured else active
    scope_count = len(scope)
    weights = dict(COMPONENT_WEIGHTS)

    built: list[Component] = []

    def add(key: str, value: int | None, reason: str | None, inputs: dict[str, InputValue]) -> None:
        built.append(Component(key, weights[key], value, reason, inputs))

    # role_relevance ---------------------------------------------------------------------
    if active_count == 0:
        add("role_relevance", None, "no_active_roles", {"relevant": None, "active": 0})
    elif not keywords.configured:
        add("role_relevance", None, "no_keywords", {"relevant": None, "active": active_count})
    else:
        add(
            "role_relevance",
            rhu(1000 * len(relevant), active_count),
            None,
            {"relevant": len(relevant), "active": active_count},
        )

    # volume -----------------------------------------------------------------------------
    if active_count == 0:
        add("volume", None, "no_active_roles", {"scope_roles": 0})
    else:
        add("volume", VOLUME_VALUES[min(scope_count, 10)], None, {"scope_roles": scope_count})

    # change -----------------------------------------------------------------------------
    uncomputed_change: dict[str, InputValue] = {
        "added": None,
        "removed": None,
        "net": None,
        "span_days": span_days,
        "window_days": WINDOW_DAYS,
    }
    if active_count == 0:
        add("change", None, "no_active_roles", uncomputed_change)
    elif span_days is None or span_days < MIN_SPAN_DAYS_FOR_CHANGE:
        add("change", None, "insufficient_history", uncomputed_change)
    else:
        added = removed = 0
        for event in events:
            if event.type not in COUNTED_EVENT_TYPES:
                continue
            at = timestamp_to_epoch(event.at)
            if not as_of_epoch - WINDOW_SECONDS < at <= as_of_epoch:
                continue
            if keywords.configured and not keywords.matches(event.title_key):
                continue
            if event.type == "removed":
                removed += 1
            else:
                added += 1
        net = added - removed
        add(
            "change",
            max(0, min(1000, 500 + 100 * net)),
            None,
            {
                "added": added,
                "removed": removed,
                "net": net,
                "span_days": span_days,
                "window_days": WINDOW_DAYS,
            },
        )

    # urgency ----------------------------------------------------------------------------
    if active_count == 0:
        add(
            "urgency",
            None,
            "no_active_roles",
            {"aged": None, "known": None, "threshold_days": URGENCY_THRESHOLD_DAYS},
        )
    else:
        allow_first_seen = span_days is not None and span_days >= URGENCY_THRESHOLD_DAYS
        ages = [
            role_age_days(r.posted_at, r.first_seen, as_of_epoch, allow_first_seen=allow_first_seen)
            for r in scope
        ]
        known_ages = [age for age in ages if age is not None]
        known = len(known_ages)
        aged = sum(1 for age in known_ages if age >= URGENCY_THRESHOLD_DAYS)
        inputs: dict[str, InputValue] = {
            "aged": aged,
            "known": known,
            "threshold_days": URGENCY_THRESHOLD_DAYS,
        }
        if scope_count == 0:
            add("urgency", None, "no_scope_roles", inputs)
        elif known == 0:
            add("urgency", None, "no_dated_roles", inputs)
        else:
            add("urgency", rhu(1000 * aged, known), None, inputs)

    # source_confidence ------------------------------------------------------------------
    if active_count == 0:
        add(
            "source_confidence",
            None,
            "no_active_roles",
            {"scope_roles": 0, "corroborated": None},
        )
    elif scope_count == 0:
        add("source_confidence", None, "no_scope_roles", {"scope_roles": 0, "corroborated": 0})
    else:
        confidences = [role_confidence(role.active_sources) for role in scope]
        add(
            "source_confidence",
            rhu(sum(conf for conf, _ in confidences), scope_count),
            None,
            {
                "scope_roles": scope_count,
                "corroborated": sum(1 for _, corroborated in confidences if corroborated),
            },
        )

    # freshness --------------------------------------------------------------------------
    if active_count == 0:
        add("freshness", None, "no_active_roles", {"days_since_last_seen": None})
    else:
        last_seen = max(role.last_seen for role in active)
        days = max(0, days_between(timestamp_to_epoch(last_seen), as_of_epoch))
        add("freshness", freshness_value(days), None, {"days_since_last_seen": days})

    # overall ----------------------------------------------------------------------------
    coverage = sum(c.weight for c in built if c.value is not None)
    if coverage == 0:
        score: int | None = None
    else:
        weighted = sum(c.weight * c.value for c in built if c.value is not None)
        score = rhu(weighted, coverage)
    return CompanyScore(components=tuple(built), coverage=coverage, score=score)
