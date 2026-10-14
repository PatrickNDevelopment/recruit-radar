"""CSV import and manual postings (``/api/imports/csv``, ``/api/postings``)."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Response

from ...clock import now_ts
from ...services import intake
from ..schemas import (
    CsvImportBody,
    ImportResultOut,
    ManualPostingOut,
    PostingBody,
    RowErrorOut,
    RowWarningOut,
    StoredPostingOut,
    WorkMode,
)
from ..state import SessionDep, StateDep
from . import ERROR_RESPONSES

router = APIRouter(tags=["imports"], responses=ERROR_RESPONSES)


@router.post(
    "/imports/csv",
    response_model=ImportResultOut,
    status_code=201,
    responses={200: {"model": ImportResultOut, "description": "No row was valid; nothing stored"}},
    summary="Import postings from CSV text",
    description=(
        "Rows are validated one by one; valid rows are stored as an additive snapshot and "
        "invalid ones come back in `errors` with their 1-based line number. Answers 201 when "
        "at least one row was stored and 200 when none was. A file-level problem (empty file, "
        "missing header, duplicate header, unterminated quote, over the size limits) is 422 "
        "`invalid_csv`."
    ),
)
def import_csv(
    body: CsvImportBody, response: Response, session: SessionDep, state: StateDep
) -> ImportResultOut:
    outcome = intake.import_csv(
        session,
        dataset_label=body.dataset_label,
        csv_text=body.csv_text,
        observed_at=body.observed_at,
        now=now_ts(state.clock),
    )
    if outcome.accepted == 0:
        response.status_code = 200
    return ImportResultOut(
        snapshot_id=outcome.snapshot_id,
        dataset_label=outcome.dataset_label,
        accepted=outcome.accepted,
        rejected=outcome.rejected,
        errors=[RowErrorOut.model_validate(e) for e in outcome.errors],
        warnings=[RowWarningOut.model_validate(w) for w in outcome.warnings],
    )


@router.post(
    "/postings",
    response_model=ManualPostingOut,
    status_code=201,
    summary="Add one manual posting",
)
def create_posting(body: PostingBody, session: SessionDep, state: StateDep) -> ManualPostingOut:
    raw = {
        "source_posting_id": body.source_posting_id,
        "company_name": body.company_name,
        "title": body.title,
        "location": body.location,
        "work_mode": body.work_mode,
        "department": body.department,
        "url": body.url,
        "posted_at": body.posted_at,
    }
    outcome = intake.add_manual_posting(
        session,
        raw=raw,
        dataset_label=body.dataset_label,
        observed_at=body.observed_at,
        now=now_ts(state.clock),
    )
    posting = outcome.posting
    return ManualPostingOut(
        snapshot_id=outcome.snapshot_id,
        source_kind="manual",
        source_ref=outcome.source_ref,
        dataset_label=outcome.dataset_label,
        observed_at=outcome.observed_at,
        posting=StoredPostingOut(
            source_posting_id=posting.source_posting_id,
            company_name=posting.company_name,
            title=posting.title,
            location=posting.location,
            work_mode=cast(WorkMode, posting.work_mode),  # clean_posting only yields valid modes
            department=posting.department,
            url=posting.url,
            posted_at=posting.posted_at,
        ),
    )
