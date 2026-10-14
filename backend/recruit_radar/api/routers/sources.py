"""ATS sources, their refresh and refresh history (``/api/sources``)."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Response

from ...clock import now_ts
from ...services import refresh as refresh_service
from ...services import sources as source_service
from ..schemas import Provider, RefreshRunOut, SourceBody, SourceOut
from ..state import AppState, SessionDep, StateDep
from . import ERROR_RESPONSES

router = APIRouter(tags=["sources"], responses=ERROR_RESPONSES)


def _source_out(state: AppState, view: source_service.SourceView) -> SourceOut:
    source = view.source
    return SourceOut(
        id=source.id,
        provider=cast(Provider, source.provider),  # CHECK constraint: three providers
        token=source.token,
        company_name=source.company_name,
        created_at=source.created_at,
        base_host=state.settings.base_host(source.provider),
        last_run=RefreshRunOut.model_validate(view.last_run) if view.last_run else None,
        last_ok_at=view.last_ok_at,
        runs_total=view.runs_total,
    )


@router.get("/sources", response_model=list[SourceOut], summary="Sources with their last run")
def list_sources(session: SessionDep, state: StateDep) -> list[SourceOut]:
    return [_source_out(state, view) for view in source_service.list_sources(session)]


@router.post(
    "/sources",
    response_model=SourceOut,
    status_code=201,
    summary="Watch an ATS board",
)
def create_source(body: SourceBody, session: SessionDep, state: StateDep) -> SourceOut:
    source = source_service.create_source(
        session,
        provider=body.provider,
        token=body.token,
        company_name=body.company_name,
        now=now_ts(state.clock),
    )
    return _source_out(state, source_service.SourceView(source, None, None, 0))


@router.delete("/sources/{source_id}", status_code=204, summary="Remove a source and its data")
def delete_source(source_id: int, session: SessionDep, state: StateDep) -> Response:
    with state.refresh_lock:  # never delete a source while it is being refreshed
        source_service.delete_source(session, source_id)
    return Response(status_code=204)


@router.post(
    "/sources/{source_id}/refresh",
    response_model=RefreshRunOut,
    summary="One read-only fetch of the board",
    description=(
        "Fetches the provider's public JSON once (one request per page), stores a snapshot and "
        "returns the run. A failed fetch still returns 200 with `status: failed`; it stores no "
        "snapshot and removes nothing. 429 `too_soon` when the source was refreshed within the "
        "minimum interval."
    ),
)
def refresh_source(source_id: int, session: SessionDep, state: StateDep) -> RefreshRunOut:
    run = refresh_service.refresh_source(
        session,
        source_id,
        settings=state.settings,
        clock=state.clock,
        transport=state.transport,
        lock=state.refresh_lock,
    )
    return RefreshRunOut.model_validate(run)


@router.get(
    "/sources/{source_id}/runs",
    response_model=list[RefreshRunOut],
    summary="Refresh history, newest first (at most 100)",
)
def list_runs(source_id: int, session: SessionDep) -> list[RefreshRunOut]:
    return [
        RefreshRunOut.model_validate(run) for run in source_service.list_runs(session, source_id)
    ]
