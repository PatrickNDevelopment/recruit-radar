"""Assemble engine input from stored snapshots and call the pure engine.

The Analysis is never stored: every request replays the stored snapshots through
``recruit_radar.engine.analyze``. Only the documented signature of the engine is used.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import is_valid_ts
from ..db.models import (
    MergeDecision,
    PostingObservation,
    Profile,
    Snapshot,
    snapshot_id_for,
)
from ..engine import EngineInputError, analyze
from ..errors import AppError

JsonObject = dict[str, Any]


def parse_as_of(value: str | None, default: str) -> str:
    """``?as_of=`` handling shared by every endpoint that accepts it."""
    if value is None:
        return default
    if not is_valid_ts(value):
        raise AppError(
            422,
            "invalid_as_of",
            "as_of must be a UTC instant formatted YYYY-MM-DDTHH:MM:SSZ",
            details={"as_of": value},
        )
    return value


def load_keywords(session: Session) -> tuple[list[str], list[str]]:
    row = session.get(Profile, 1)
    if row is None:
        return [], []
    return _loads_list(row.include_keywords), _loads_list(row.exclude_keywords)


def _loads_list(text: str) -> list[str]:
    value = json.loads(text)
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def load_decisions(session: Session) -> list[JsonObject]:
    rows = session.scalars(select(MergeDecision).order_by(MergeDecision.id))
    return [{"a_key": r.a_key, "b_key": r.b_key, "decision": r.decision} for r in rows]


def load_snapshots(
    session: Session,
    *,
    as_of: str,
    source: tuple[str, str] | None = None,
    exclude_snapshot_id: int | None = None,
) -> list[JsonObject]:
    """Stored snapshots (observed at or before ``as_of``) in the engine's input shape."""
    wanted = [Snapshot.observed_at <= as_of]
    if source is not None:
        wanted += [Snapshot.source_kind == source[0], Snapshot.source_ref == source[1]]
    if exclude_snapshot_id is not None:
        wanted.append(Snapshot.id != exclude_snapshot_id)

    snapshots = session.scalars(select(Snapshot).where(*wanted).order_by(Snapshot.id)).all()
    postings: dict[int, list[JsonObject]] = defaultdict(list)
    rows = session.execute(
        select(
            PostingObservation.snapshot_id,
            PostingObservation.source_posting_id,
            PostingObservation.company_name,
            PostingObservation.title,
            PostingObservation.location,
            PostingObservation.work_mode,
            PostingObservation.department,
            PostingObservation.url,
            PostingObservation.posted_at,
        )
        .join(Snapshot, Snapshot.id == PostingObservation.snapshot_id)
        .where(*wanted)
        .order_by(PostingObservation.snapshot_id, PostingObservation.position)
    )
    for row in rows:
        postings[row.snapshot_id].append(
            {
                "source_posting_id": row.source_posting_id,
                "company_name": row.company_name,
                "title": row.title,
                "location": row.location,
                "work_mode": row.work_mode,
                "department": row.department,
                "url": row.url,
                "posted_at": row.posted_at,
            }
        )
    return [
        {
            "snapshot_id": snapshot_id_for(snapshot.id),
            "source_kind": snapshot.source_kind,
            "source_ref": snapshot.source_ref,
            "observed_at": snapshot.observed_at,
            "mode": snapshot.mode,
            "postings": postings.get(snapshot.id, []),
        }
        for snapshot in snapshots
    ]


def run_engine(payload: JsonObject) -> JsonObject:
    try:
        return analyze(payload)
    except EngineInputError as exc:
        # Everything stored passed the same validation the engine applies, so this means the
        # database was edited by hand or the engine contract moved. Say so; never guess.
        raise AppError(
            500, "analysis_failed", f"Stored data was rejected by the analysis engine: {exc}"
        ) from exc


def build_analysis(session: Session, as_of: str) -> JsonObject:
    """The full Analysis (spec 02 section 5) of everything stored, as of ``as_of``."""
    include, exclude = load_keywords(session)
    return run_engine(
        {
            "as_of": as_of,
            "profile": {"include_keywords": include, "exclude_keywords": exclude},
            "decisions": load_decisions(session),
            "snapshots": load_snapshots(session, as_of=as_of),
        }
    )


def source_events(
    session: Session,
    *,
    source: tuple[str, str],
    as_of: str,
    exclude_snapshot_id: int | None = None,
) -> JsonObject:
    """Analysis restricted to one source's snapshots (used for refresh counters).

    Profile and decisions do not influence lifecycle events, so they are left empty.
    """
    return run_engine(
        {
            "as_of": as_of,
            "snapshots": load_snapshots(
                session, as_of=as_of, source=source, exclude_snapshot_id=exclude_snapshot_id
            ),
        }
    )
