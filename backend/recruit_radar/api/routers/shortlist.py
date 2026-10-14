"""Shortlist, qualification notes and the shortlist CSV export."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ...clock import now_ts
from ...services import shortlist as shortlist_service
from ...services.analysis import build_analysis, parse_as_of
from ..schemas import ShortlistBody, ShortlistEntryOut, ShortlistStateOut
from ..state import SessionDep, StateDep
from . import ERROR_RESPONSES, AsOf

router = APIRouter(tags=["shortlist"], responses=ERROR_RESPONSES)


@router.get("/shortlist", response_model=list[ShortlistEntryOut], summary="Shortlisted companies")
def list_shortlist(session: SessionDep, state: StateDep) -> list[ShortlistEntryOut]:
    analysis = build_analysis(session, now_ts(state.clock))
    return [
        ShortlistEntryOut(
            company_id=item.company_id,
            name=item.name,
            note=item.note,
            added_at=item.added_at or "",
        )
        for item in shortlist_service.list_shortlist(session, analysis)
    ]


@router.put(
    "/companies/{company_id}/shortlist",
    response_model=ShortlistStateOut,
    summary="Shortlist (or un-shortlist) a company and set its qualification note",
)
def put_company_shortlist(
    company_id: str, body: ShortlistBody, session: SessionDep, state: StateDep
) -> ShortlistStateOut:
    now = now_ts(state.clock)
    analysis = build_analysis(session, now)
    result = shortlist_service.update_shortlist(
        session,
        analysis,
        company_id=company_id,
        shortlisted=body.shortlisted,
        note=body.note,
        now=now,
    )
    return ShortlistStateOut(
        company_id=result.company_id,
        shortlisted=result.shortlisted,
        name=result.name,
        note=result.note,
        added_at=result.added_at,
    )


@router.get(
    "/shortlist/export.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Shortlist as CSV"}},
    summary="Shortlist CSV with score and evidence summary",
)
def export_shortlist(session: SessionDep, state: StateDep, as_of: AsOf = None) -> Response:
    effective = parse_as_of(as_of, now_ts(state.clock))
    analysis = build_analysis(session, effective)
    text = shortlist_service.export_shortlist_csv(session, analysis)
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="recruit-radar-shortlist.csv"'},
    )
