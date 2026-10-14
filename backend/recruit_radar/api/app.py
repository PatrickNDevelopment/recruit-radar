"""The FastAPI application factory (spec 03).

``create_app(settings)`` builds a fully wired app: migrated database, error envelope, CORS
limited to the configured origins and one router per area under ``/api``. Time and the network
are injected so tests control both; production passes neither.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import __version__
from ..clock import Clock, utc_now
from ..config import Settings
from ..db.migrate import upgrade
from ..db.session import create_db_engine, create_session_factory
from .errors import envelope, install_error_handlers
from .routers import analysis, data, decisions, health, imports, profile, shortlist, sources
from .state import AppState

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

DESCRIPTION = (
    "Local-only backend of RecruitRadar. It turns public job-posting data (three read-only ATS "
    "JSON APIs, CSV files and manual entries) into an evidence-backed view of observed hiring "
    "activity. There is no authentication: bind it to a loopback address (the default)."
)


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    transport: httpx.BaseTransport | None = None,
    run_migrations: bool = True,
) -> FastAPI:
    """Build the application.

    ``clock`` and ``transport`` exist for tests (a fixed clock, an ``httpx.MockTransport``).
    ``run_migrations=False`` is for schema export, which never needs a database.
    """
    config = settings if settings is not None else Settings.from_env()
    engine = create_db_engine(config.db_path)
    if run_migrations:
        upgrade(engine)
    state = AppState(
        settings=config,
        engine=engine,
        session_factory=create_session_factory(engine),
        clock=clock if clock is not None else utc_now,
        transport=transport,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(
        title="RecruitRadar API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        # Route function names are unique and make readable operation ids in generated clients.
        generate_unique_id_function=lambda route: route.name,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.recruit_radar = state
    install_error_handlers(app)

    allowed_origins = frozenset(config.cors_origins)

    @app.middleware("http")
    async def reject_foreign_origins(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """A browser page on another origin cannot change data, even with a "simple" request.

        CORS alone stops a foreign page from *reading* answers, but a POST without a JSON body is
        a "simple" request that is sent anyway. Requests without an ``Origin`` header (curl, the
        tests, server-side callers) are unaffected.
        """
        origin = request.headers.get("origin")
        if (
            origin is not None
            and request.method not in _SAFE_METHODS
            and origin.rstrip("/") not in allowed_origins
        ):
            return JSONResponse(
                status_code=403,
                content=envelope(
                    "origin_not_allowed",
                    f"Origin {origin!r} is not in RECRUIT_RADAR_CORS_ORIGINS",
                ),
            )
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["Retry-After", "Content-Disposition"],
        allow_credentials=False,
    )

    for module in (health, profile, sources, imports, analysis, decisions, shortlist, data):
        app.include_router(module.router, prefix="/api")
    return app
