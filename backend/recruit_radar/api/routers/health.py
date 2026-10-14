"""``GET /api/health``."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ... import __version__
from ...db.models import Meta
from ..schemas import HealthOut
from ..state import SessionDep
from . import ERROR_RESPONSES

router = APIRouter(tags=["health"], responses=ERROR_RESPONSES)


@router.get("/health", response_model=HealthOut, summary="Liveness and schema version")
def get_health(session: SessionDep) -> HealthOut:
    schema_version: int | None = None
    db_ok = True
    try:
        session.execute(text("SELECT 1"))
        row = session.get(Meta, "schema_version")
        if row is not None:
            schema_version = int(row.value)
        else:
            db_ok = False
    except (SQLAlchemyError, ValueError):  # the endpoint's job is to report, not to fail
        db_ok = False
    return HealthOut(
        status="ok" if db_ok else "degraded",
        app_version=__version__,
        schema_version=schema_version,
        db_ok=db_ok,
    )
