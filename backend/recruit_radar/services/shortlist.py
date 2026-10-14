"""Shortlist, qualification notes and the shortlist CSV export (spec 03, spec 05)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ShortlistEntry
from ..errors import AppError
from ..normalization import company_key as raw_company_key
from ..normalization import trim
from .csv_io import write_csv

JsonObject = dict[str, Any]

EXPORT_HEADER = (
    "rank",
    "company",
    "score",
    "coverage_percent",
    "active_roles",
    "relevant_roles",
    "last_seen",
    "strongest_evidence",
    "missing_information",
    "note",
    "as_of",
)

_LABELS = {
    "role_relevance": "Role relevance",
    "volume": "Volume",
    "change": "Change (30 days)",
    "urgency": "Possible urgency signal",
    "source_confidence": "Source confidence",
    "freshness": "Freshness",
}
_REASONS = {
    "no_active_roles": "no active roles",
    "no_keywords": "no role keywords configured",
    "insufficient_history": "fewer than two full snapshots at least 14 days apart",
    "no_scope_roles": "no active role matches the configured keywords",
    "no_dated_roles": "no role has a known posting age",
}


@dataclass(frozen=True, slots=True)
class ShortlistItem:
    company_id: str
    name: str
    note: str
    added_at: str | None
    in_analysis: bool


@dataclass(frozen=True, slots=True)
class ShortlistState:
    company_id: str
    shortlisted: bool
    name: str
    note: str
    added_at: str | None


def member_keys(company: JsonObject) -> set[str]:
    """Every raw company key that currently belongs to ``company`` (canonical key + aliases)."""
    keys = {company["key"]}
    keys.update(raw_company_key(alias) for alias in company["aliases"])
    return keys


class CompanyIndex:
    """Look companies up by id, or by any raw key that was merged into them."""

    def __init__(self, analysis: JsonObject) -> None:
        self.companies: list[JsonObject] = analysis["companies"]
        self.by_id = {c["company_id"]: c for c in self.companies}
        self.by_member_key: dict[str, JsonObject] = {}
        for company in self.companies:
            for key in member_keys(company):
                self.by_member_key.setdefault(key, company)

    def resolve(self, entry: ShortlistEntry) -> JsonObject | None:
        return self.by_id.get(entry.company_id) or self.by_member_key.get(entry.company_key)


def state_for(session: Session, index: CompanyIndex, company: JsonObject) -> ShortlistState:
    """The shortlist/note state of a current company (found by id or by merged-in key)."""
    keys = member_keys(company)
    entry = session.get(ShortlistEntry, company["company_id"])
    if entry is None:
        entry = _orphan_for(session, keys, company["company_id"])
    if entry is None:
        return ShortlistState(company["company_id"], False, company["name"], "", None)
    return ShortlistState(
        company["company_id"], entry.shortlisted, company["name"], entry.note, entry.added_at
    )


def _orphan_for(session: Session, keys: set[str], company_id: str) -> ShortlistEntry | None:
    """An entry written under an older id of this company (a merge changed the canonical key)."""
    return session.scalars(
        select(ShortlistEntry)
        .where(
            ShortlistEntry.company_key.in_(sorted(keys)), ShortlistEntry.company_id != company_id
        )
        .order_by(ShortlistEntry.added_at, ShortlistEntry.company_id)
    ).first()


def list_shortlist(session: Session, analysis: JsonObject) -> list[ShortlistItem]:
    index = CompanyIndex(analysis)
    items: dict[str, ShortlistItem] = {}
    rows = session.scalars(
        select(ShortlistEntry)
        .where(ShortlistEntry.shortlisted.is_(True))
        .order_by(ShortlistEntry.added_at, ShortlistEntry.company_id)
    )
    for entry in rows:
        company = index.resolve(entry)
        item = ShortlistItem(
            company_id=company["company_id"] if company else entry.company_id,
            name=company["name"] if company else entry.name,
            note=entry.note,
            added_at=entry.added_at,
            in_analysis=company is not None,
        )
        items.setdefault(item.company_id, item)
    return list(items.values())


def update_shortlist(
    session: Session,
    analysis: JsonObject,
    *,
    company_id: str,
    shortlisted: bool,
    note: str | None,
    now: str,
) -> ShortlistState:
    index = CompanyIndex(analysis)
    company = index.by_id.get(company_id)
    if company is None:
        raise AppError(
            404,
            "unknown_company",
            f"No company {company_id!r} in the loaded data",
            details={"company_id": company_id},
        )
    entry = session.get(ShortlistEntry, company_id)
    if entry is None:
        orphan = _orphan_for(session, member_keys(company), company_id)
        if orphan is not None:
            orphan.company_id = company_id  # the entry follows its company through a merge
            entry = orphan
    cleaned_note = trim(note) if note is not None else None

    if entry is None:
        if not shortlisted and not cleaned_note:
            return ShortlistState(company_id, False, company["name"], "", None)
        entry = ShortlistEntry(
            company_id=company_id,
            company_key=company["key"],
            name=company["name"],
            note="",
            shortlisted=False,
            added_at=None,
            updated_at=now,
        )
        session.add(entry)

    if cleaned_note is not None:
        entry.note = cleaned_note
    if shortlisted and not entry.shortlisted:
        entry.added_at = now
    entry.shortlisted = shortlisted
    entry.company_key = company["key"]
    entry.name = company["name"]
    entry.updated_at = now

    state = ShortlistState(
        company_id, entry.shortlisted, company["name"], entry.note, entry.added_at
    )
    if not entry.shortlisted and not entry.note:
        session.delete(entry)  # nothing left worth keeping
    session.commit()
    return state


# ---------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------
def display_score(score: int | None) -> str:
    """Score 0..1000 shown with one decimal as 0.0..100.0, integer arithmetic only."""
    return "" if score is None else f"{score // 10}.{score % 10}"


def _strongest_evidence(company: JsonObject) -> str:
    best: JsonObject | None = None
    for component in company["components"]:
        if component["value"] is None:
            continue
        if best is None or component["weight"] * component["value"] > (
            best["weight"] * best["value"]
        ):
            best = component
    if best is None:
        return ""
    inputs = best["inputs"]
    detail = {
        "role_relevance": lambda i: (
            f"{i['relevant']} of {i['active']} active roles match the keywords"
        ),
        "volume": lambda i: f"{i['scope_roles']} active roles in scope",
        "change": lambda i: (
            f"{i['added']} added and {i['removed']} removed in the last {i['window_days']} days"
        ),
        "urgency": lambda i: (
            f"{i['aged']} of {i['known']} dated roles are {i['threshold_days']}+ days old"
        ),
        "source_confidence": lambda i: (
            f"{i['corroborated']} of {i['scope_roles']} in-scope roles seen in more than one source"
        ),
        "freshness": lambda i: f"last seen {i['days_since_last_seen']} days before the report",
    }[best["key"]](inputs)
    return f"{_LABELS[best['key']]}: {detail}"


def _missing_information(company: JsonObject) -> str:
    parts = [
        f"{_LABELS[c['key']]}: {_REASONS.get(c['reason_code'] or '', c['reason_code'] or 'unknown')}"
        for c in company["components"]
        if c["value"] is None
    ]
    return "; ".join(parts)


def export_shortlist_csv(session: Session, analysis: JsonObject) -> str:
    index = CompanyIndex(analysis)
    order = {c["company_id"]: position for position, c in enumerate(index.companies)}
    as_of = analysis["as_of"]

    rows: list[tuple[int, str, Sequence[str]]] = []
    seen: set[str] = set()
    entries = session.scalars(
        select(ShortlistEntry)
        .where(ShortlistEntry.shortlisted.is_(True))
        .order_by(ShortlistEntry.added_at, ShortlistEntry.company_id)
    )
    for entry in entries:
        company = index.resolve(entry)
        if company is None:
            rows.append(
                (
                    len(order),
                    entry.name,
                    (
                        "",
                        entry.name,
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "Company is not present in the loaded data",
                        entry.note,
                        as_of,
                    ),
                )
            )
            continue
        if company["company_id"] in seen:
            continue
        seen.add(company["company_id"])
        rows.append(
            (
                order[company["company_id"]],
                company["name"],
                (
                    "" if company["rank"] is None else str(company["rank"]),
                    company["name"],
                    display_score(company["score"]),
                    str(company["coverage"]),
                    str(company["active_roles"]),
                    "" if company["relevant_roles"] is None else str(company["relevant_roles"]),
                    company["last_seen"] or "",
                    _strongest_evidence(company),
                    _missing_information(company),
                    entry.note,
                    as_of,
                ),
            )
        )
    rows.sort(key=lambda r: (r[0], r[1]))
    return write_csv([EXPORT_HEADER, *(r[2] for r in rows)])
