"""User merge decisions (spec 01 section 3; spec 03 ``/api/merge-decisions``)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.models import MergeDecision, PostingObservation
from ..errors import AppError


def list_decisions(session: Session) -> list[MergeDecision]:
    return list(session.scalars(select(MergeDecision).order_by(MergeDecision.id)))


def create_decision(
    session: Session, *, a_key: str, b_key: str, decision: str, now: str
) -> MergeDecision:
    if not a_key < b_key:
        raise AppError(
            422,
            "invalid_decision",
            "a_key must sort strictly before b_key (code point order)",
            details={"a_key": a_key, "b_key": b_key},
        )
    known = set(
        session.scalars(
            select(PostingObservation.company_key)
            .where(PostingObservation.company_key.in_([a_key, b_key]))
            .distinct()
        )
    )
    unknown = [key for key in (a_key, b_key) if key not in known]
    if unknown:
        raise AppError(
            422,
            "invalid_decision",
            "Both keys must be company keys present in the stored data; unknown: "
            + ", ".join(repr(key) for key in unknown),
            details={"unknown_keys": unknown},
        )
    existing = session.scalars(
        select(MergeDecision).where(MergeDecision.a_key == a_key, MergeDecision.b_key == b_key)
    ).first()
    if existing is not None:
        raise AppError(
            409,
            "decision_exists",
            f"A {existing.decision!r} decision already exists for this pair; delete it first",
            details={"id": existing.id, "decision": existing.decision},
        )
    row = MergeDecision(a_key=a_key, b_key=b_key, decision=decision, created_at=now)
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AppError(409, "decision_exists", "A decision already exists for this pair") from exc
    return row


def delete_decision(session: Session, decision_id: int) -> None:
    row = session.get(MergeDecision, decision_id)
    if row is None:
        raise AppError(404, "not_found", f"No merge decision with id {decision_id}")
    session.delete(row)
    session.commit()
