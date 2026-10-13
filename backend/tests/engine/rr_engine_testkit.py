"""Small builders shared by the engine tests (not a test module itself)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

AS_OF = "2026-10-13T12:00:00Z"

Json = dict[str, Any]


def posting(
    company: str = "Acme",
    title: str = "Engineer",
    *,
    pid: str | None = None,
    location: str | None = None,
    work_mode: str | None = None,
    department: str | None = None,
    url: str | None = None,
    posted_at: str | None = None,
) -> Json:
    """A RawPosting dict; keys with ``None`` values are simply omitted."""
    raw: Json = {"company_name": company, "title": title}
    optional = {
        "source_posting_id": pid,
        "location": location,
        "work_mode": work_mode,
        "department": department,
        "url": url,
        "posted_at": posted_at,
    }
    raw.update({key: value for key, value in optional.items() if value is not None})
    return raw


def snapshot(
    snapshot_id: str,
    observed_at: str,
    postings: Iterable[Json],
    *,
    kind: str = "greenhouse",
    ref: str = "acme",
    mode: str = "full",
) -> Json:
    return {
        "snapshot_id": snapshot_id,
        "source_kind": kind,
        "source_ref": ref,
        "observed_at": observed_at,
        "mode": mode,
        "postings": list(postings),
    }


def make_input(
    snapshots: Sequence[Json],
    *,
    as_of: str = AS_OF,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    decisions: Sequence[Json] = (),
) -> Json:
    return {
        "as_of": as_of,
        "profile": {"include_keywords": list(include), "exclude_keywords": list(exclude)},
        "decisions": [dict(d) for d in decisions],
        "snapshots": [dict(s) for s in snapshots],
    }


def company(analysis: Json, key: str) -> Json:
    """The company with the given canonical key."""
    matches = [c for c in analysis["companies"] if c["key"] == key]
    assert len(matches) == 1, f"expected exactly one company {key!r}, got {len(matches)}"
    found: Json = matches[0]
    return found


def component(company_json: Json, key: str) -> Json:
    found: Json = next(c for c in company_json["components"] if c["key"] == key)
    return found


def roles_of(analysis: Json, company_json: Json) -> list[Json]:
    return [r for r in analysis["roles"] if r["company_id"] == company_json["company_id"]]


def events(analysis: Json, event_type: str | None = None) -> list[Json]:
    return [e for e in analysis["events"] if event_type is None or e["type"] == event_type]
