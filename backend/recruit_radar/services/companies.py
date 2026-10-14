"""Company detail view assembled from the Analysis (spec 03 ``GET /api/companies/{id}``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Snapshot, Source
from ..errors import AppError
from .shortlist import CompanyIndex, ShortlistState, state_for

JsonObject = dict[str, Any]


def company_detail(
    session: Session, analysis: JsonObject, company_id: str
) -> tuple[JsonObject, list[JsonObject], list[JsonObject], list[JsonObject], ShortlistState]:
    """(company, roles, events, per-source freshness, shortlist state) for ``company_id``."""
    index = CompanyIndex(analysis)
    company = index.by_id.get(company_id)
    if company is None:
        raise AppError(
            404,
            "not_found",
            f"No company {company_id!r} in the loaded data",
            details={"company_id": company_id},
        )
    roles = [r for r in analysis["roles"] if r["company_id"] == company_id]
    events = [e for e in analysis["events"] if e["company_id"] == company_id]
    return (
        company,
        roles,
        events,
        _freshness(session, roles, analysis["as_of"]),
        state_for(session, index, company),
    )


def _freshness(session: Session, roles: list[JsonObject], as_of: str) -> list[JsonObject]:
    """How current each source's evidence for this company is."""
    per_source: dict[tuple[str, str], JsonObject] = {}
    for role in roles:
        for observation in role["observations"]:
            key = (observation["source_kind"], observation["source_ref"])
            entry = per_source.setdefault(
                key,
                {
                    "source_kind": key[0],
                    "source_ref": key[1],
                    "active_roles": 0,
                    "removed_roles": 0,
                    "first_seen": observation["first_seen"],
                    "last_seen": observation["last_seen"],
                },
            )
            entry["active_roles" if observation["status"] == "active" else "removed_roles"] += 1
            entry["first_seen"] = min(entry["first_seen"], observation["first_seen"])
            entry["last_seen"] = max(entry["last_seen"], observation["last_seen"])

    result: list[JsonObject] = []
    for (kind, ref), entry in sorted(per_source.items()):
        latest = session.scalar(
            select(func.max(Snapshot.observed_at)).where(
                Snapshot.source_kind == kind,
                Snapshot.source_ref == ref,
                Snapshot.observed_at <= as_of,
            )
        )
        source_id = session.scalar(
            select(Source.id).where(Source.provider == kind, Source.token == ref)
        )
        result.append({**entry, "source_id": source_id, "last_observed_at": latest})
    return result
