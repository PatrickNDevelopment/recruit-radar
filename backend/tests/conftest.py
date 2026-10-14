"""Fixtures shared by the backend service tests (the engine tests have their own conftest)."""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

with warnings.catch_warnings():
    # Starlette 1.x prefers httpx2 for its TestClient; the pinned toolchain uses httpx.
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from fastapi import FastAPI
from rr_support import FakeAts, FakeClock

from recruit_radar.api import create_app
from recruit_radar.config import Settings


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ats() -> FakeAts:
    return FakeAts()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "recruit_radar.sqlite3"


@pytest.fixture
def settings(db_path: Path) -> Settings:
    # The default 60 s interval, so the spec behaviour is what the tests see unless they opt out.
    return Settings(db_path=db_path)


AppFactory = Callable[..., FastAPI]


@pytest.fixture
def make_app(settings: Settings, clock: FakeClock, ats: FakeAts) -> Iterator[AppFactory]:
    """Build apps on the test database; every one is disposed when the test ends."""
    built: list[FastAPI] = []

    def factory(**overrides: Any) -> FastAPI:
        chosen = overrides.pop("settings", settings)
        app = create_app(
            chosen,
            clock=overrides.pop("clock", clock),
            transport=overrides.pop("transport", ats.transport()),
            **overrides,
        )
        built.append(app)
        return app

    yield factory
    for app in built:
        app.state.recruit_radar.engine.dispose()


@pytest.fixture
def app(make_app: AppFactory) -> FastAPI:
    return make_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_factory() -> Iterator[Callable[..., TestClient]]:
    """Clients for extra apps (a restart, a second configuration)."""
    clients: list[TestClient] = []

    def build(app: FastAPI, **kwargs: Any) -> TestClient:
        test_client = TestClient(app, **kwargs)
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield build
    for test_client in clients:
        test_client.__exit__(None, None, None)
