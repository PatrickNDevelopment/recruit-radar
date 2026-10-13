"""Snapshot replay (spec 02 section 2).

Snapshots are folded, in ``(observed_at, snapshot_id)`` order, into one :class:`SourceRole` per
source role key, emitting lifecycle events in processing order. Nothing here knows about company
identity: that is resolved afterwards, over the finished replay.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from .models import ParsedPosting, ParsedSnapshot

SourceKey = tuple[str, str]
"""``(source_kind, source_ref)``."""

RoleKey = tuple[str, ...]
"""``(kind, ref, "id", posting_id)`` or ``(kind, ref, "k", company_key, title_key, location_key)``."""

TRACKED_FIELDS: Final = ("title", "location", "work_mode", "department", "url", "posted_at")

KEY_SEPARATOR: Final = "|"


def role_key_string(key: RoleKey) -> str:
    """The joined form of a source role key, used wherever the spec orders keys as strings."""
    return KEY_SEPARATOR.join(key)


@dataclass(slots=True)
class SourceRole:
    """One role as seen by one source, folded over every snapshot of that source."""

    key: RoleKey
    key_str: str
    source: SourceKey
    source_posting_id: str | None
    company_name: str
    company_key: str
    title: str
    title_key: str
    location: str | None
    location_key: str
    work_mode: str
    department: str | None
    url: str | None
    posted_at: str | None
    status: str
    first_seen: str
    last_seen: str
    removed_at: str | None
    # (observed_at, raw company_name) of every posting that was observed for this role,
    # including postings superseded inside a snapshot (they are still observed postings).
    name_log: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    at: str
    type: str
    role_key: RoleKey
    source_kind: str
    source_ref: str
    title: str
    fields: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ReplayResult:
    roles: dict[RoleKey, SourceRole]
    events: tuple[ReplayEvent, ...]
    postings_observed: int


def source_role_key(source: SourceKey, posting: ParsedPosting) -> RoleKey:
    """Source role key of ``posting`` as seen by ``source`` (spec 01 section 4)."""
    kind, ref = source
    if posting.source_posting_id is not None:
        return (kind, ref, "id", posting.source_posting_id)
    return (kind, ref, "k", posting.company_key, posting.title_key, posting.location_key)


def _tracked_values(posting: ParsedPosting) -> dict[str, str | None]:
    return {
        "title": posting.title,
        "location": posting.location,
        "work_mode": posting.work_mode,
        "department": posting.department,
        "url": posting.url,
        "posted_at": posting.posted_at,
    }


def _current_values(role: SourceRole) -> dict[str, str | None]:
    return {
        "title": role.title,
        "location": role.location,
        "work_mode": role.work_mode,
        "department": role.department,
        "url": role.url,
        "posted_at": role.posted_at,
    }


def _apply_posting(role: SourceRole, posting: ParsedPosting) -> None:
    role.company_name = posting.company_name
    role.company_key = posting.company_key
    role.title = posting.title
    role.title_key = posting.title_key
    role.location = posting.location
    role.location_key = posting.location_key
    role.work_mode = posting.work_mode
    role.department = posting.department
    role.url = posting.url
    role.posted_at = posting.posted_at


def replay(snapshots: Sequence[ParsedSnapshot]) -> ReplayResult:
    """Fold ``snapshots`` (already restricted to ``observed_at <= as_of``) into source roles."""
    ordered = sorted(snapshots, key=lambda s: (s.observed_epoch, s.snapshot_id))

    roles: dict[RoleKey, SourceRole] = {}
    roles_by_source: dict[SourceKey, list[RoleKey]] = {}
    baseline_taken: set[SourceKey] = set()
    events: list[ReplayEvent] = []
    postings_observed = 0

    for snapshot in ordered:
        source: SourceKey = (snapshot.source_kind, snapshot.source_ref)
        is_baseline = source not in baseline_taken
        baseline_taken.add(source)
        source_roles = roles_by_source.setdefault(source, [])
        observed_at = snapshot.observed_at
        postings_observed += len(snapshot.postings)

        # Step 1: within a snapshot the last posting of a key wins, no event for the loser.
        winner: dict[RoleKey, tuple[int, ParsedPosting]] = {}
        names: dict[RoleKey, list[str]] = {}
        for index, posting in enumerate(snapshot.postings):
            key = source_role_key(source, posting)
            winner[key] = (index, posting)
            names.setdefault(key, []).append(posting.company_name)

        # Step 2: distinct keys in order of last occurrence.
        listed = set(winner)
        for key in sorted(winner, key=lambda k: winner[k][0]):
            posting = winner[key][1]
            role = roles.get(key)
            if role is None:
                role = SourceRole(
                    key=key,
                    key_str=role_key_string(key),
                    source=source,
                    source_posting_id=posting.source_posting_id,
                    company_name=posting.company_name,
                    company_key=posting.company_key,
                    title=posting.title,
                    title_key=posting.title_key,
                    location=posting.location,
                    location_key=posting.location_key,
                    work_mode=posting.work_mode,
                    department=posting.department,
                    url=posting.url,
                    posted_at=posting.posted_at,
                    status="active",
                    first_seen=observed_at,
                    last_seen=observed_at,
                    removed_at=None,
                )
                roles[key] = role
                source_roles.append(key)
                event_type = "baseline" if is_baseline else "added"
                events.append(
                    ReplayEvent(
                        observed_at, event_type, key, source[0], source[1], role.title, None
                    )
                )
            elif role.status == "active":
                before = _current_values(role)
                after = _tracked_values(posting)
                changed = tuple(
                    sorted(name for name in TRACKED_FIELDS if before[name] != after[name])
                )
                _apply_posting(role, posting)
                role.last_seen = observed_at
                if changed:
                    events.append(
                        ReplayEvent(
                            observed_at, "changed", key, source[0], source[1], role.title, changed
                        )
                    )
            else:
                _apply_posting(role, posting)
                role.status = "active"
                role.removed_at = None
                role.last_seen = observed_at
                events.append(
                    ReplayEvent(
                        observed_at, "reappeared", key, source[0], source[1], role.title, None
                    )
                )
            role.name_log.extend((observed_at, name) for name in names[key])

        # Step 3: a full snapshot removes every active role of the source it did not list.
        if snapshot.mode == "full":
            vanished = sorted(
                (
                    roles[key]
                    for key in source_roles
                    if roles[key].status == "active" and key not in listed
                ),
                key=lambda r: (r.key_str, r.key),
            )
            for role in vanished:
                role.status = "removed"
                role.removed_at = observed_at
                events.append(
                    ReplayEvent(
                        observed_at, "removed", role.key, source[0], source[1], role.title, None
                    )
                )

    return ReplayResult(roles=roles, events=tuple(events), postings_observed=postings_observed)
