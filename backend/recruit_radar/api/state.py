"""Per-application state and the FastAPI dependencies that hand it to routes."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated

import httpx
from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..clock import Clock
from ..config import Settings


@dataclass(slots=True)
class AppState:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    clock: Clock
    # Injected only by tests; ``None`` means the real network.
    transport: httpx.BaseTransport | None
    # One provider request at a time, and no source delete racing a refresh of it.
    refresh_lock: threading.Lock = field(default_factory=threading.Lock)


def get_state(request: Request) -> AppState:
    state = request.app.state.recruit_radar
    if not isinstance(state, AppState):  # pragma: no cover - wiring error
        raise TypeError("application state is not initialised")
    return state


StateDep = Annotated[AppState, Depends(get_state)]


def get_session(state: StateDep) -> Iterator[Session]:
    session = state.session_factory()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
