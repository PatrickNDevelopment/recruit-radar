"""Helpers shared by the provider mappings. Provider data is untrusted: every access is typed."""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..normalization import CleanPosting, clean_posting
from .base import Tally


def as_text(value: object) -> str | None:
    """``value`` if it is a string, else ``None`` (numbers, lists, objects are not text)."""
    return value if isinstance(value, str) else None


def as_identifier(value: object) -> str | None:
    """A provider id: a non-empty string or an integer (never a bool or float)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def dict_of(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _utc_date(moment: datetime) -> date:
    aware = moment.astimezone(UTC) if moment.tzinfo is not None else moment
    return aware.date()


def iso_to_date(value: object, tally: Tally, field_name: str = "posted_at") -> str | None:
    """``YYYY-MM-DD`` (UTC) of an ISO 8601 date or datetime; absent -> None, invalid -> omitted."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            return _utc_date(datetime.fromisoformat(value.strip())).isoformat()
        except ValueError:
            pass
    tally.omitted[field_name] += 1
    return None


def epoch_ms_to_date(value: object, tally: Tally, field_name: str = "posted_at") -> str | None:
    """UTC date of a numeric epoch-milliseconds value; absent -> None, invalid -> omitted."""
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC).date().isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    tally.omitted[field_name] += 1
    return None


def finish_job(raw: dict[str, object], tally: Tally) -> CleanPosting | None:
    """Clean one mapped job. A bad required field drops the job; bad optional ones are nulled."""
    result = clean_posting(raw, lenient=True)
    for problem in result.omitted:
        tally.omitted[problem.field] += 1
    if result.posting is None:
        first = result.problems[0]
        tally.dropped[f"invalid {first.field}"] += 1
        return None
    return result.posting
