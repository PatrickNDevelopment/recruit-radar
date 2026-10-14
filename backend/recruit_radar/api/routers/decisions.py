"""``/api/merge-decisions``: the user's merge / not-the-same choices."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ...clock import now_ts
from ...services import decisions as decision_service
from ..schemas import DecisionBody, MergeDecisionOut
from ..state import SessionDep, StateDep
from . import ERROR_RESPONSES

router = APIRouter(tags=["merge decisions"], responses=ERROR_RESPONSES)


@router.get(
    "/merge-decisions", response_model=list[MergeDecisionOut], summary="All stored decisions"
)
def list_merge_decisions(session: SessionDep) -> list[MergeDecisionOut]:
    return [MergeDecisionOut.model_validate(d) for d in decision_service.list_decisions(session)]


@router.post(
    "/merge-decisions",
    response_model=MergeDecisionOut,
    status_code=201,
    summary="Record that two company keys are (or are not) the same company",
)
def create_merge_decision(
    body: DecisionBody, session: SessionDep, state: StateDep
) -> MergeDecisionOut:
    row = decision_service.create_decision(
        session,
        a_key=body.a_key,
        b_key=body.b_key,
        decision=body.decision,
        now=now_ts(state.clock),
    )
    return MergeDecisionOut.model_validate(row)


@router.delete("/merge-decisions/{decision_id}", status_code=204, summary="Undo a decision")
def delete_merge_decision(decision_id: int, session: SessionDep) -> Response:
    decision_service.delete_decision(session, decision_id)
    return Response(status_code=204)
