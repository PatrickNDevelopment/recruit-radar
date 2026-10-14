"""UTC, whole-second timestamps in the fixed textual forms of spec 01/02.

The backend never formats a time any other way: every stored and returned instant is
``YYYY-MM-DDTHH:MM:SSZ`` and every stored posting date is ``YYYY-MM-DD``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Final

Clock = Callable[[], datetime]
"""A source of "now". Injected so tests control time; always returns an aware UTC datetime."""

_TIMESTAMP_RE: Final = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z"
)
_DATE_RE: Final = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")


def utc_now() -> datetime:
    """The real clock: current UTC time truncated to whole seconds."""
    return datetime.now(UTC).replace(microsecond=0)


def format_ts(value: datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ`` of ``value`` (naive datetimes are taken to be UTC)."""
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ts(clock: Clock) -> str:
    return format_ts(clock())


def parse_ts(value: str) -> datetime:
    """Parse exactly ``YYYY-MM-DDTHH:MM:SSZ``; ``ValueError`` for anything else."""
    match = _TIMESTAMP_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"not a YYYY-MM-DDTHH:MM:SSZ timestamp: {value!r}")
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def is_valid_ts(value: str) -> bool:
    try:
        parse_ts(value)
    except ValueError:
        return False
    return True


def parse_date(value: str) -> date:
    """Parse exactly ``YYYY-MM-DD`` (ASCII digits, real calendar date)."""
    match = _DATE_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"not a YYYY-MM-DD date: {value!r}")
    return date(int(match[1]), int(match[2]), int(match[3]))


def is_valid_date(value: str) -> bool:
    try:
        parse_date(value)
    except ValueError:
        return False
    return True
