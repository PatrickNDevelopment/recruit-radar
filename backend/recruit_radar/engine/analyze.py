"""``analyze``: the pure analysis function (spec 02).

Pipeline: validate -> drop snapshots after ``as_of`` -> replay -> resolve company identity ->
dedup canonical roles -> score companies -> rank -> assemble the JSON-compatible Analysis.
No clock, no randomness, no I/O: the same input always yields the same output.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .identity import (
    RoleGroupItem,
    company_id_for,
    find_merge_candidates,
    group_canonical_roles,
    not_same_pairs,
    resolve_canonical_keys,
)
from .models import parse_input
from .normalize import title_key
from .replay import RoleKey, SourceKey, SourceRole, replay
from .scoring import (
    CompanyScore,
    Component,
    Keywords,
    ScoringEvent,
    ScoringRole,
    role_age_days,
    score_company,
)
from .timeutil import days_between, timestamp_to_epoch

JsonObject = dict[str, Any]


@dataclass(slots=True)
class _CanonicalRole:
    role_id: str
    company_id: str
    members: list[SourceRole]
    display: SourceRole
    status: str
    first_seen: str
    last_seen: str
    removed_at: str | None
    posted_at: str | None
    relevant: bool | None

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass(slots=True)
class _Company:
    company_id: str
    key: str
    name: str
    aliases: list[str]
    first_seen: str
    last_seen: str | None
    roles: list[_CanonicalRole]
    relevant_roles: int | None
    score: CompanyScore
    rank: int | None = None


def _build_canonical_role(
    role_id: str, company_id: str, members: list[SourceRole], keywords: Keywords
) -> _CanonicalRole:
    active_members = [m for m in members if m.status == "active"]
    status = "active" if active_members else "removed"
    removed_ats = [m.removed_at for m in members if m.removed_at is not None]
    posted_ats = [m.posted_at for m in members if m.posted_at is not None]

    # Display fields come from the member with the greatest last_seen; ties go to the
    # smallest source role key string.
    display = min(members, key=lambda m: (-timestamp_to_epoch(m.last_seen), m.key_str, m.key))

    return _CanonicalRole(
        role_id=role_id,
        company_id=company_id,
        members=members,
        display=display,
        status=status,
        first_seen=min(m.first_seen for m in members),
        last_seen=max(m.last_seen for m in (active_members or members)),
        removed_at=None if active_members else max(removed_ats),
        posted_at=min(posted_ats) if posted_ats else None,
        relevant=keywords.matches(display.title_key) if keywords.configured else None,
    )


def _observation(member: SourceRole) -> JsonObject:
    return {
        "source_kind": member.source[0],
        "source_ref": member.source[1],
        "source_posting_id": member.source_posting_id,
        "url": member.url,
        "status": member.status,
        "first_seen": member.first_seen,
        "last_seen": member.last_seen,
    }


def _component_json(component: Component) -> JsonObject:
    return {
        "key": component.key,
        "weight": component.weight,
        "value": component.value,
        "reason_code": component.reason_code,
        "inputs": dict(component.inputs),
    }


def analyze(input: Mapping[str, Any]) -> JsonObject:
    """Compute the Analysis of spec 02 section 5 from the plain-dict ``input``.

    Raises :class:`~recruit_radar.engine.errors.EngineInputError` when the input is invalid.
    """
    parsed = parse_input(input)
    as_of_epoch = parsed.as_of_epoch
    keywords = Keywords.build(parsed.include_keywords, parsed.exclude_keywords)

    processed = [s for s in parsed.snapshots if s.observed_epoch <= as_of_epoch]
    replayed = replay(processed)
    source_roles = list(replayed.roles.values())

    # --- company identity (resolved after replay, so merges apply to history) ----------------
    canonical_of = resolve_canonical_keys({r.company_key for r in source_roles}, parsed.decisions)
    company_id_of_key = {raw: company_id_for(canon) for raw, canon in canonical_of.items()}
    canonical_key_of_company = {company_id_for(c): c for c in set(canonical_of.values())}

    # --- canonical roles ----------------------------------------------------------------------
    items = [
        RoleGroupItem(
            ident=index,
            company_id=company_id_of_key[role.company_key],
            title_key=role.title_key,
            location_key=role.location_key,
            source=role.source,
            key_str=role.key_str,
            key=role.key,
        )
        for index, role in enumerate(source_roles)
    ]
    canonical_roles: list[_CanonicalRole] = []
    canonical_of_source_role: dict[RoleKey, _CanonicalRole] = {}
    for group in group_canonical_roles(items):
        canonical = _build_canonical_role(
            group.role_id, group.company_id, [source_roles[i] for i in group.members], keywords
        )
        canonical_roles.append(canonical)
        for member in canonical.members:
            canonical_of_source_role[member.key] = canonical

    roles_by_company: dict[str, list[_CanonicalRole]] = defaultdict(list)
    for canonical in canonical_roles:
        roles_by_company[canonical.company_id].append(canonical)

    # --- observation history per company ------------------------------------------------------
    full_times: dict[SourceKey, list[int]] = defaultdict(list)
    for snapshot in processed:
        if snapshot.mode == "full":
            full_times[(snapshot.source_kind, snapshot.source_ref)].append(snapshot.observed_epoch)

    scoring_events: dict[str, list[ScoringEvent]] = defaultdict(list)
    for event in replayed.events:
        company_of_event = canonical_of_source_role[event.role_key].company_id
        scoring_events[company_of_event].append(
            ScoringEvent(at=event.at, type=event.type, title_key=title_key(event.title))
        )

    # --- per-company assembly and scoring -----------------------------------------------------
    companies: list[_Company] = []
    for company_id, roles in roles_by_company.items():
        members = [m for role in roles for m in role.members]

        postings = [entry for m in members for entry in m.name_log]
        name = min(postings)[1]  # earliest observed posting; ties -> smallest raw name
        aliases = sorted({raw for _, raw in postings})

        # T is a *set* of instants (spec 02 section 4 writes |T|, min T, max T): two full
        # snapshots at one instant are one element, so their span is unknown (null), not 0.
        sources = {m.source for m in members}
        times = sorted({t for source in sources for t in full_times.get(source, [])})
        span_days = days_between(times[0], times[-1]) if len(times) >= 2 else None

        active_roles = [r for r in roles if r.active]
        score = score_company(
            roles=[
                ScoringRole(
                    active=r.active,
                    relevant=r.relevant,
                    posted_at=r.posted_at,
                    first_seen=r.first_seen,
                    last_seen=r.last_seen,
                    active_sources=tuple(m.source for m in r.members if m.status == "active"),
                )
                for r in roles
            ],
            events=scoring_events[company_id],
            keywords=keywords,
            span_days=span_days,
            as_of_epoch=as_of_epoch,
        )
        companies.append(
            _Company(
                company_id=company_id,
                key=canonical_key_of_company[company_id],
                name=name,
                aliases=aliases,
                first_seen=min(r.first_seen for r in roles),
                last_seen=max((r.last_seen for r in active_roles), default=None),
                roles=roles,
                relevant_roles=(
                    sum(1 for r in active_roles if r.relevant is True)
                    if keywords.configured
                    else None
                ),
                score=score,
            )
        )

    # --- ranking and ordering -----------------------------------------------------------------
    scored = sorted(
        (c for c in companies if c.score.score is not None),
        key=lambda c: (-(c.score.score or 0), c.key, c.company_id),
    )
    for position, company in enumerate(scored, start=1):
        company.rank = position
    unscored = sorted(
        (c for c in companies if c.score.score is None), key=lambda c: (c.key, c.company_id)
    )
    ordered = scored + unscored

    # --- merge candidates ---------------------------------------------------------------------
    candidates = find_merge_candidates(
        {c.key: c.name for c in companies}, not_same_pairs(parsed.decisions)
    )

    # --- output -------------------------------------------------------------------------------
    companies_json: list[JsonObject] = []
    roles_json: list[JsonObject] = []
    for company in ordered:
        active_count = sum(1 for r in company.roles if r.active)
        companies_json.append(
            {
                "company_id": company.company_id,
                "key": company.key,
                "name": company.name,
                "aliases": company.aliases,
                "first_seen": company.first_seen,
                "last_seen": company.last_seen,
                "active_roles": active_count,
                "relevant_roles": company.relevant_roles,
                "removed_roles": len(company.roles) - active_count,
                "score": company.score.score,
                "coverage": company.score.coverage,
                "rank": company.rank,
                "components": [_component_json(c) for c in company.score.components],
            }
        )
        for role in sorted(
            company.roles,
            key=lambda r: (0 if r.active else 1, r.first_seen, r.role_id),
        ):
            age = role_age_days(role.posted_at, role.first_seen, as_of_epoch, allow_first_seen=True)
            roles_json.append(
                {
                    "role_id": role.role_id,
                    "company_id": role.company_id,
                    "title": role.display.title,
                    "location": role.display.location,
                    "work_mode": role.display.work_mode,
                    "department": role.display.department,
                    "posted_at": role.posted_at,
                    "status": role.status,
                    "first_seen": role.first_seen,
                    "last_seen": role.last_seen,
                    "removed_at": role.removed_at,
                    "relevant": role.relevant,
                    "age_days": age,
                    "observations": [
                        _observation(m)
                        for m in sorted(
                            role.members,
                            key=lambda m: (
                                m.source[0],
                                m.source[1],
                                m.source_posting_id or "",
                                m.key_str,
                            ),
                        )
                    ],
                }
            )

    events_json: list[JsonObject] = []
    for event in replayed.events:
        owner = canonical_of_source_role[event.role_key]
        events_json.append(
            {
                "at": event.at,
                "type": event.type,
                "company_id": owner.company_id,
                "role_id": owner.role_id,
                "source_kind": event.source_kind,
                "source_ref": event.source_ref,
                "title": event.title,
                "fields": list(event.fields) if event.fields is not None else None,
            }
        )

    return {
        "as_of": parsed.as_of,
        "companies": companies_json,
        "roles": roles_json,
        "events": events_json,
        "merge_candidates": [
            {
                "candidate_id": c.candidate_id,
                "a_key": c.a_key,
                "b_key": c.b_key,
                "a_name": c.a_name,
                "b_name": c.b_name,
                "reason": c.reason,
            }
            for c in candidates
        ],
        "stats": {
            "snapshots": len(processed),
            "postings_observed": replayed.postings_observed,
            "companies": len(companies),
            "active_roles": sum(1 for r in canonical_roles if r.active),
        },
    }
