"""Erase everything the user stored (spec 03 ``DELETE /api/data?confirm=erase-all``)."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db.models import (
    MergeDecision,
    PostingObservation,
    Profile,
    RefreshRun,
    ShortlistEntry,
    Snapshot,
    Source,
)

ERASE_CONFIRMATION = "erase-all"


def erase_all(session: Session) -> None:
    """Delete sources, runs, snapshots, observations, decisions, shortlist and profile.

    Only the ``meta`` table (schema version) is kept. Runs in one transaction.
    """
    for model in (
        RefreshRun,
        PostingObservation,
        Snapshot,
        Source,
        MergeDecision,
        ShortlistEntry,
        Profile,
    ):
        session.execute(delete(model))
    session.commit()
