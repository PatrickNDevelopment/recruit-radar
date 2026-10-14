"""``GET/PUT /api/profile``: the role keywords."""

from __future__ import annotations

from fastapi import APIRouter

from ...clock import now_ts
from ...services import profile as profile_service
from ..schemas import ProfileBody, ProfileOut
from ..state import SessionDep, StateDep
from . import ERROR_RESPONSES

router = APIRouter(tags=["profile"], responses=ERROR_RESPONSES)


def _out(data: profile_service.ProfileData) -> ProfileOut:
    return ProfileOut(
        include_keywords=data.include_keywords, exclude_keywords=data.exclude_keywords
    )


@router.get("/profile", response_model=ProfileOut, summary="Role keywords")
def get_profile(session: SessionDep) -> ProfileOut:
    return _out(profile_service.get_profile(session))


@router.put("/profile", response_model=ProfileOut, summary="Replace the role keywords")
def put_profile(body: ProfileBody, session: SessionDep, state: StateDep) -> ProfileOut:
    saved = profile_service.save_profile(
        session,
        include=body.include_keywords,
        exclude=body.exclude_keywords,
        now=now_ts(state.clock),
    )
    return _out(saved)
