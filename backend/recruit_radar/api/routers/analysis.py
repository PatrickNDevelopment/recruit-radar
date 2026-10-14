"""``GET /api/analysis`` and ``GET /api/companies/{company_id}``."""

from __future__ import annotations

from fastapi import APIRouter

from ...clock import now_ts
from ...services.analysis import build_analysis, parse_as_of
from ...services.companies import company_detail
from ..schemas import (
    AnalysisOut,
    CompanyDetailOut,
    CompanyOut,
    EventOut,
    RoleOut,
    ShortlistStateOut,
    SourceFreshnessOut,
)
from ..state import SessionDep, StateDep
from . import ERROR_RESPONSES, AsOf

router = APIRouter(tags=["analysis"], responses=ERROR_RESPONSES)


@router.get(
    "/analysis",
    response_model=AnalysisOut,
    summary="Companies, roles, events and scores",
    description=(
        "Derived by replaying every stored snapshot through the pure analysis engine; nothing "
        "derived is stored."
    ),
)
def get_analysis(session: SessionDep, state: StateDep, as_of: AsOf = None) -> AnalysisOut:
    effective = parse_as_of(as_of, now_ts(state.clock))
    return AnalysisOut.model_validate(build_analysis(session, effective))


@router.get(
    "/companies/{company_id}",
    response_model=CompanyDetailOut,
    summary="One company with its roles, events and per-source freshness",
)
def get_company(
    company_id: str, session: SessionDep, state: StateDep, as_of: AsOf = None
) -> CompanyDetailOut:
    effective = parse_as_of(as_of, now_ts(state.clock))
    analysis = build_analysis(session, effective)
    company, roles, events, freshness, shortlist = company_detail(session, analysis, company_id)
    return CompanyDetailOut(
        as_of=effective,
        company=CompanyOut.model_validate(company),
        roles=[RoleOut.model_validate(role) for role in roles],
        events=[EventOut.model_validate(event) for event in events],
        source_freshness=[SourceFreshnessOut.model_validate(item) for item in freshness],
        shortlist=ShortlistStateOut(
            company_id=shortlist.company_id,
            shortlisted=shortlist.shortlisted,
            name=shortlist.name,
            note=shortlist.note,
            added_at=shortlist.added_at,
        ),
    )
