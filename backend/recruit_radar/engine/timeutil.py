"""Integer-only UTC time helpers (spec 02 section 1, "day math").

No clock, no locale, no floating point: every timestamp is converted to integer epoch seconds
from its fixed textual form, and day differences are floor divisions of integers.
"""

from __future__ import annotations

import re
from datetime import date
from functools import cache
from typing import Final

SECONDS_PER_DAY: Final = 86_400

_UNIX_EPOCH_ORDINAL: Final = date(1970, 1, 1).toordinal()
# [0-9] on purpose: \d would also match non-ASCII decimal digits.
_DATE_RE: Final = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_TIMESTAMP_RE: Final = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z"
)


def _date_ordinal_seconds(year: int, month: int, day: int) -> int:
    # date() raises ValueError for anything that is not a real calendar date.
    return (date(year, month, day).toordinal() - _UNIX_EPOCH_ORDINAL) * SECONDS_PER_DAY


@cache
def date_to_epoch(value: str) -> int:
    """Epoch seconds of ``YYYY-MM-DD`` read as ``00:00:00Z``.

    Raises ``ValueError`` when the text is not exactly that shape or not a real date.
    """
    match = _DATE_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"not a YYYY-MM-DD date: {value!r}")
    return _date_ordinal_seconds(int(match[1]), int(match[2]), int(match[3]))


@cache
def timestamp_to_epoch(value: str) -> int:
    """Epoch seconds of ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, whole seconds).

    Raises ``ValueError`` when the text is not exactly that shape or not a real instant.
    """
    match = _TIMESTAMP_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"not a YYYY-MM-DDTHH:MM:SSZ timestamp: {value!r}")
    hour, minute, second = int(match[4]), int(match[5]), int(match[6])
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError(f"time of day out of range: {value!r}")
    base = _date_ordinal_seconds(int(match[1]), int(match[2]), int(match[3]))
    return base + hour * 3600 + minute * 60 + second


def days_between(start_epoch: int, end_epoch: int) -> int:
    """``floor((end - start) / 86400)``; negative when ``end`` precedes ``start``."""
    return (end_epoch - start_epoch) // SECONDS_PER_DAY
