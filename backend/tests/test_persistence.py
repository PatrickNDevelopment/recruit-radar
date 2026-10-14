"""Everything the user stores survives a restart: a new app instance on the same database."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rr_support import (
    FakeAts,
    FakeClock,
    add_source,
    analysis,
    company_named,
    csv_of,
    error_of,
    gh_job,
    import_csv,
    refresh,
)

from recruit_radar.db import session as session_module


def restart(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[..., TestClient],
    old: TestClient,
) -> TestClient:
    """Stop the running app (dispose its engine) and start a fresh one on the same file."""
    old.app.state.recruit_radar.engine.dispose()  # type: ignore[attr-defined]
    return client_factory(make_app())


def test_all_user_data_persists_across_an_app_restart(
    client: TestClient,
    make_app: Callable[..., FastAPI],
    client_factory: Callable[..., TestClient],
    ats: FakeAts,
    clock: FakeClock,
) -> None:
    client.put(
        "/api/profile", json={"include_keywords": ["engineer"], "exclude_keywords": ["intern"]}
    )
    ats.greenhouse("acme", [gh_job(1, "Engineer"), gh_job(2, "Designer")])
    sid = add_source(client, company_name="Acme")["id"]
    refresh(client, sid)
    clock.advance(seconds=120)
    import_csv(
        client,
        csv_of(("DoorDash", "Engineer", "SF", ""), ("Door Dash", "Analyst", "SF", "")),
        label="leads",
    )
    client.post("/api/postings", json={"company_name": "Initech", "title": "Recruiter"})
    decision = client.post(
        "/api/merge-decisions",
        json={"a_key": "door dash", "b_key": "doordash", "decision": "merge"},
    ).json()
    acme_id = company_named(analysis(client), "Acme")["company_id"]
    client.put(
        f"/api/companies/{acme_id}/shortlist", json={"shortlisted": True, "note": "Great fit"}
    )
    before = {
        "analysis": analysis(client),
        "profile": client.get("/api/profile").json(),
        "sources": client.get("/api/sources").json(),
        "runs": client.get(f"/api/sources/{sid}/runs").json(),
        "decisions": client.get("/api/merge-decisions").json(),
        "shortlist": client.get("/api/shortlist").json(),
        "export": client.get("/api/shortlist/export.csv").text,
        "detail": client.get(f"/api/companies/{acme_id}").json(),
    }

    reopened = restart(make_app, client_factory, client)

    assert analysis(reopened) == before["analysis"]
    assert reopened.get("/api/profile").json() == before["profile"]
    assert reopened.get("/api/sources").json() == before["sources"]
    assert reopened.get(f"/api/sources/{sid}/runs").json() == before["runs"]
    assert reopened.get("/api/merge-decisions").json() == before["decisions"]
    assert reopened.get("/api/shortlist").json() == before["shortlist"]
    assert reopened.get("/api/shortlist/export.csv").text == before["export"]
    assert reopened.get(f"/api/companies/{acme_id}").json() == before["detail"]
    assert before["shortlist"][0]["note"] == "Great fit"
    assert before["decisions"][0]["id"] == decision["id"]


def test_ids_keep_counting_after_a_restart_and_the_schema_is_not_recreated(
    client: TestClient,
    make_app: Callable[..., FastAPI],
    client_factory: Callable[..., TestClient],
) -> None:
    first = add_source(client, token="one", company_name="One")
    reopened = restart(make_app, client_factory, client)
    assert reopened.get("/api/health").json()["schema_version"] == 1
    second = add_source(reopened, token="two", company_name="Two")
    assert second["id"] > first["id"]
    assert [s["token"] for s in reopened.get("/api/sources").json()] == ["one", "two"]


def test_refresh_history_and_the_interval_survive_a_restart(
    client: TestClient,
    make_app: Callable[..., FastAPI],
    client_factory: Callable[..., TestClient],
    ats: FakeAts,
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    sid = add_source(client)["id"]
    assert refresh(client, sid).status_code == 200
    reopened = restart(make_app, client_factory, client)
    too_soon = refresh(reopened, sid)  # the clock did not move: still inside the minimum interval
    assert too_soon.status_code == 429
    assert len(reopened.get(f"/api/sources/{sid}/runs").json()) == 1


def test_two_apps_on_one_database_see_each_others_writes(
    client: TestClient,
    make_app: Callable[..., FastAPI],
    client_factory: Callable[..., TestClient],
) -> None:
    other = client_factory(make_app())
    client.put("/api/profile", json={"include_keywords": ["from-first"]})
    assert other.get("/api/profile").json()["include_keywords"] == ["from-first"]
    import_csv(other, csv_of(("Acme", "Engineer", "", "")))
    assert [c["name"] for c in analysis(client)["companies"]] == ["Acme"]


def test_a_database_locked_by_another_program_is_503_database_busy_and_loses_nothing(
    make_app: Callable[..., FastAPI],
    client_factory: Callable[..., TestClient],
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Another process holds the write lock longer than the busy timeout (shortened here, before
    # the app opens its connections: the pragma is applied when a connection is created).
    monkeypatch.setattr(session_module, "BUSY_TIMEOUT_MS", 50)
    client = client_factory(make_app())
    import_csv(client, csv_of(("Before", "Engineer", "", "")))
    holder = sqlite3.connect(db_path, isolation_level=None, timeout=1)
    try:
        holder.execute("BEGIN IMMEDIATE")
        blocked = client.post("/api/postings", json={"company_name": "Locked Co", "title": "x"})
        reading = client.get("/api/analysis")
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert blocked.status_code == 503
    assert blocked.headers["retry-after"] == "5"
    assert error_of(blocked)["code"] == "database_busy"
    assert reading.status_code == 200  # WAL: readers are never blocked by a writer
    again = client.post("/api/postings", json={"company_name": "After Co", "title": "x"})
    assert again.status_code == 201
    assert sorted(c["name"] for c in analysis(client)["companies"]) == ["After Co", "Before"]
