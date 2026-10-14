"""ATS source management (spec 03 ``/api/sources``)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..adapters import InvalidToken, validate_token
from ..db.models import RefreshRun, Source
from ..errors import AppError
from ..normalization import MAX_COMPANY_NAME, trim

RUN_HISTORY_LIMIT = 100


@dataclass(frozen=True, slots=True)
class SourceView:
    source: Source
    last_run: RefreshRun | None
    last_ok_at: str | None
    runs_total: int


def get_source(session: Session, source_id: int) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise AppError(404, "not_found", f"No source with id {source_id}")
    return source


def create_source(
    session: Session, *, provider: str, token: str, company_name: str, now: str
) -> Source:
    try:
        validate_token(token)
    except InvalidToken as exc:
        raise AppError(422, "invalid_token", str(exc), details={"field": "token"}) from exc
    name = trim(company_name)
    if not 1 <= len(name) <= MAX_COMPANY_NAME:
        raise AppError(
            422,
            "invalid_source",
            f"company_name must be 1-{MAX_COMPANY_NAME} characters after trimming",
            details={"field": "company_name"},
        )
    # Board tokens are compared ignoring ASCII case so one board cannot be watched twice.
    duplicate = session.scalars(
        select(Source).where(Source.provider == provider, func.lower(Source.token) == token.lower())
    ).first()
    if duplicate is not None:
        raise _exists(duplicate)
    source = Source(provider=provider, token=token, company_name=name, created_at=now)
    session.add(source)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AppError(409, "source_exists", "This source is already being watched") from exc
    return source


def _exists(source: Source) -> AppError:
    return AppError(
        409,
        "source_exists",
        f"{source.provider} board {source.token!r} is already a source",
        details={"source_id": source.id},
    )


def list_sources(session: Session) -> list[SourceView]:
    views: list[SourceView] = []
    for source in session.scalars(select(Source).order_by(Source.id)):
        last_run = session.scalars(
            select(RefreshRun)
            .where(RefreshRun.source_id == source.id)
            .order_by(RefreshRun.id.desc())
        ).first()
        last_ok = session.scalars(
            select(RefreshRun.finished_at)
            .where(RefreshRun.source_id == source.id, RefreshRun.status == "ok")
            .order_by(RefreshRun.id.desc())
        ).first()
        total = session.scalar(
            select(func.count()).select_from(RefreshRun).where(RefreshRun.source_id == source.id)
        )
        views.append(SourceView(source, last_run, last_ok, total or 0))
    return views


def delete_source(session: Session, source_id: int) -> None:
    source = get_source(session, source_id)
    # ON DELETE CASCADE removes the source's runs, snapshots and observations.
    session.delete(source)
    session.commit()


def list_runs(session: Session, source_id: int) -> list[RefreshRun]:
    get_source(session, source_id)
    return list(
        session.scalars(
            select(RefreshRun)
            .where(RefreshRun.source_id == source_id)
            .order_by(RefreshRun.id.desc())
            .limit(RUN_HISTORY_LIMIT)
        )
    )
