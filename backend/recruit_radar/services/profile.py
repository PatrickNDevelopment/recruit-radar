"""Role-keyword profile (spec 03: ``GET/PUT /api/profile``)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from ..db.models import Profile
from ..errors import AppError
from ..normalization import norm_text, trim
from .analysis import load_keywords

MAX_KEYWORDS: Final = 50
MAX_KEYWORD_LENGTH: Final = 60


@dataclass(frozen=True, slots=True)
class ProfileData:
    include_keywords: list[str]
    exclude_keywords: list[str]


def get_profile(session: Session) -> ProfileData:
    include, exclude = load_keywords(session)
    return ProfileData(include, exclude)


def _clean(field: str, values: Sequence[str]) -> list[str]:
    if len(values) > MAX_KEYWORDS:
        raise AppError(
            422,
            "invalid_profile",
            f"{field} may hold at most {MAX_KEYWORDS} keywords (got {len(values)})",
            details={"field": field},
        )
    cleaned: list[str] = []
    for index, value in enumerate(values):
        keyword = trim(value)
        problem: str | None = None
        if not keyword:
            problem = "must not be empty"
        elif len(keyword) > MAX_KEYWORD_LENGTH:
            problem = f"must be at most {MAX_KEYWORD_LENGTH} characters"
        elif not norm_text(keyword):
            # Letters/numbers only count: a keyword like "!!!" can never match a title.
            problem = "must contain at least one letter or number"
        if problem is not None:
            raise AppError(
                422,
                "invalid_profile",
                f"{field}[{index}] {problem}",
                details={"field": field, "index": index},
            )
        if keyword not in cleaned:
            cleaned.append(keyword)
    return cleaned


def save_profile(
    session: Session, *, include: Sequence[str], exclude: Sequence[str], now: str
) -> ProfileData:
    data = ProfileData(_clean("include_keywords", include), _clean("exclude_keywords", exclude))
    row = session.get(Profile, 1)
    if row is None:
        row = Profile(id=1)
        session.add(row)
    row.include_keywords = json.dumps(data.include_keywords, ensure_ascii=False)
    row.exclude_keywords = json.dumps(data.exclude_keywords, ensure_ascii=False)
    row.updated_at = now
    session.commit()
    return data
