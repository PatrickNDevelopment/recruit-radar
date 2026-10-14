"""``DELETE /api/data``: erase everything the user stored."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from ...errors import AppError
from ...services.data import ERASE_CONFIRMATION, erase_all
from ..state import SessionDep, StateDep
from . import ERROR_RESPONSES

router = APIRouter(tags=["data"], responses=ERROR_RESPONSES)


@router.delete(
    "/data",
    status_code=204,
    summary="Erase all stored data",
    description=(
        "Deletes sources, runs, snapshots, postings, decisions, the shortlist and the profile. "
        "Requires `?confirm=erase-all`; anything else is 400 `confirmation_required`."
    ),
)
def delete_data(
    session: SessionDep,
    state: StateDep,
    confirm: Annotated[str | None, Query(description="Must be exactly `erase-all`.")] = None,
) -> Response:
    if confirm != ERASE_CONFIRMATION:
        raise AppError(
            400,
            "confirmation_required",
            f"Erasing all data requires ?confirm={ERASE_CONFIRMATION}",
            details={"required": {"confirm": ERASE_CONFIRMATION}},
        )
    with state.refresh_lock:  # not while a refresh is writing a snapshot
        erase_all(session)
    return Response(status_code=204)
