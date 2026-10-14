"""Writing snapshots and their observations."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import insert
from sqlalchemy.orm import Session

from ..db.models import PostingObservation, Snapshot
from ..normalization import CleanPosting


def store_snapshot(
    session: Session,
    *,
    source_id: int | None,
    source_kind: str,
    source_ref: str,
    observed_at: str,
    mode: str,
    dataset_label: str | None,
    created_at: str,
    postings: Sequence[CleanPosting],
) -> Snapshot:
    """Insert one snapshot with its postings (in listed order). Flushes; does not commit."""
    snapshot = Snapshot(
        source_id=source_id,
        source_kind=source_kind,
        source_ref=source_ref,
        observed_at=observed_at,
        mode=mode,
        dataset_label=dataset_label,
        created_at=created_at,
    )
    session.add(snapshot)
    session.flush()
    if postings:
        session.execute(
            insert(PostingObservation),
            [
                {
                    "snapshot_id": snapshot.id,
                    "position": position,
                    "source_posting_id": posting.source_posting_id,
                    "company_name": posting.company_name,
                    "title": posting.title,
                    "location": posting.location,
                    "work_mode": posting.work_mode,
                    "department": posting.department,
                    "url": posting.url,
                    "posted_at": posting.posted_at,
                    "company_key": posting.company_key,
                    "title_key": posting.title_key,
                    "location_key": posting.location_key,
                }
                for position, posting in enumerate(postings)
            ],
        )
    return snapshot
