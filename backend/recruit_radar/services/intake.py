"""CSV import and manual entry: the two ways user-provided postings enter the system."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..clock import is_valid_ts
from ..db.models import snapshot_id_for
from ..errors import AppError
from ..normalization import CleanPosting, clean_posting, trim
from .csv_io import CsvFileError, ParsedRow, RowError, RowWarning, parse_postings
from .store import store_snapshot

MAX_LABEL = 200
MANUAL_SOURCE_REF = "manual"


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    snapshot_id: str | None
    dataset_label: str
    accepted: int
    rejected: int
    errors: list[RowError]
    warnings: list[RowWarning]


@dataclass(frozen=True, slots=True)
class ManualOutcome:
    snapshot_id: str
    source_kind: str
    source_ref: str
    dataset_label: str | None
    observed_at: str
    posting: CleanPosting


def _label(value: str, *, code: str) -> str:
    label = trim(value)
    if not 1 <= len(label) <= MAX_LABEL:
        raise AppError(
            422,
            code,
            f"dataset_label must be 1-{MAX_LABEL} characters after trimming",
            details={"field": "dataset_label"},
        )
    return label


def _instant(value: str | None, *, code: str, field: str) -> str | None:
    if value is None:
        return None
    if not is_valid_ts(value):
        raise AppError(
            422,
            code,
            f"{field} must be a UTC instant formatted YYYY-MM-DDTHH:MM:SSZ",
            details={"field": field},
        )
    return value


def import_csv(
    session: Session,
    *,
    dataset_label: str,
    csv_text: str,
    observed_at: str | None,
    now: str,
) -> ImportOutcome:
    """Validate ``csv_text`` row by row and store the valid rows as additive snapshot(s).

    Rows normally share one observation time (the request's ``observed_at`` or ``now``). Rows that
    carry their own ``observed_at`` are stored in one snapshot per distinct instant, because an
    engine snapshot has exactly one ``observed_at``.
    """
    label = _label(dataset_label, code="invalid_csv")
    default_observed = _instant(observed_at, code="invalid_csv", field="observed_at") or now
    try:
        parsed = parse_postings(csv_text)
    except CsvFileError as exc:
        details = {"line": exc.line} if exc.line is not None else None
        raise AppError(422, "invalid_csv", exc.message, details=details) from exc

    groups: dict[str, list[ParsedRow]] = defaultdict(list)
    warnings = list(parsed.warnings)
    for row in parsed.rows:
        effective = row.observed_at or default_observed
        groups[effective].append(row)
        if effective > now:
            warnings.append(
                RowWarning(
                    row.line,
                    f"observed_at {effective} is after the import time {now}; the analysis "
                    "ignores this row until then",
                )
            )
    warnings.sort(key=lambda w: w.line)

    snapshot_id: str | None = None
    for effective in sorted(groups):
        snapshot = store_snapshot(
            session,
            source_id=None,
            source_kind="csv",
            source_ref=label,
            observed_at=effective,
            mode="additive",
            dataset_label=label,
            created_at=now,
            postings=[row.posting for row in groups[effective]],
        )
        snapshot_id = snapshot_id_for(snapshot.id)
    session.commit()
    return ImportOutcome(
        snapshot_id=snapshot_id,
        dataset_label=label,
        accepted=len(parsed.rows),
        rejected=parsed.rejected,
        errors=parsed.errors,
        warnings=warnings,
    )


def add_manual_posting(
    session: Session,
    *,
    raw: Mapping[str, object],
    dataset_label: str | None,
    observed_at: str | None,
    now: str,
) -> ManualOutcome:
    """Store one manually entered posting as an additive snapshot of the ``manual`` source."""
    label = _label(dataset_label, code="invalid_posting") if dataset_label is not None else None
    observed = _instant(observed_at, code="invalid_posting", field="observed_at") or now
    cleaned = clean_posting(raw)
    if cleaned.posting is None:
        first = cleaned.problems[0]
        raise AppError(
            422,
            "invalid_posting",
            first.message,
            details={
                "errors": [{"field": p.field, "message": p.message} for p in cleaned.problems]
            },
        )
    snapshot = store_snapshot(
        session,
        source_id=None,
        source_kind="manual",
        source_ref=MANUAL_SOURCE_REF,
        observed_at=observed,
        mode="additive",
        dataset_label=label,
        created_at=now,
        postings=[cleaned.posting],
    )
    session.commit()
    return ManualOutcome(
        snapshot_id=snapshot_id_for(snapshot.id),
        source_kind="manual",
        source_ref=MANUAL_SOURCE_REF,
        dataset_label=label,
        observed_at=observed,
        posting=cleaned.posting,
    )
