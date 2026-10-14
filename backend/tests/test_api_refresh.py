"""``POST /api/sources/{id}/refresh`` and ``GET /api/sources/{id}/runs`` (spec 03 + 04)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rr_support import (
    ASHBY_HOST,
    GREENHOUSE_HOST,
    LEVER_HOST,
    FakeAts,
    FakeClock,
    add_source,
    analysis,
    ashby_job,
    error_of,
    gh_job,
    lever_posting,
    refresh,
)

from recruit_radar.config import Settings

GH_PATH = "/v1/boards/acme/jobs"


@pytest.fixture
def fast_client(
    make_app: Callable[..., FastAPI],
    settings: Settings,
    client_factory: Callable[..., TestClient],
) -> TestClient:
    """A client whose app allows back-to-back refreshes (the 60 s rule has its own tests)."""
    return client_factory(make_app(settings=settings.with_overrides(min_refresh_interval_s=0)))


def run_of(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    return dict(response.json())


COUNTERS = ("added", "changed", "removed", "reappeared", "unchanged")


def counters(run: dict[str, Any]) -> dict[str, int]:
    return {name: run[name] for name in COUNTERS}


# -- success ----------------------------------------------------------------------------------
def test_first_refresh_stores_a_baseline_snapshot(client: TestClient, ats: FakeAts) -> None:
    ats.greenhouse(
        "acme",
        [gh_job(1, "Backend Engineer", location="Remote - US"), gh_job(2, "Designer")],
    )
    source = add_source(client)
    run = run_of(refresh(client, source["id"]))

    assert set(run) == {
        "id",
        "source_id",
        "started_at",
        "finished_at",
        "status",
        "error_kind",
        "http_status",
        "retry_after_s",
        "items_seen",
        "added",
        "changed",
        "removed",
        "reappeared",
        "unchanged",
        "message",
    }
    assert run["source_id"] == source["id"]
    assert run["status"] == "ok"
    assert run["error_kind"] is None
    assert run["http_status"] == 200
    assert run["retry_after_s"] is None
    assert run["items_seen"] == 2
    assert counters(run) == dict.fromkeys(COUNTERS, 0)  # a baseline is not "added"
    assert run["started_at"] == run["finished_at"] == "2026-10-13T12:00:00Z"
    assert "Baseline snapshot recorded: 2 postings" in run["message"]
    assert GREENHOUSE_HOST in run["message"]

    data = analysis(client)
    assert data["stats"] == {
        "snapshots": 1,
        "postings_observed": 2,
        "companies": 1,
        "active_roles": 2,
    }
    (company,) = data["companies"]
    assert company["name"] == "Acme Inc."  # the user's name for the board
    assert {e["type"] for e in data["events"]} == {"baseline"}
    assert {r["title"] for r in data["roles"]} == {"Backend Engineer", "Designer"}
    remote = next(r for r in data["roles"] if r["title"] == "Backend Engineer")
    assert remote["work_mode"] == "remote"
    assert remote["posted_at"] == "2026-09-20"
    assert remote["observations"][0]["source_kind"] == "greenhouse"
    assert remote["observations"][0]["source_ref"] == "acme"


def test_second_refresh_reports_added_changed_removed_from_the_engine_replay(
    fast_client: TestClient, ats: FakeAts, clock: FakeClock
) -> None:
    source = add_source(fast_client)
    sid = source["id"]
    ats.greenhouse(
        "acme",
        [gh_job(1, "Engineer"), gh_job(2, "Designer"), gh_job(3, "Analyst")],
    )
    first = run_of(refresh(fast_client, sid))
    assert counters(first) == dict.fromkeys(COUNTERS, 0)

    clock.advance(seconds=3600)
    ats.greenhouse(
        "acme",
        [
            gh_job(1, "Senior Engineer"),  # renamed -> changed
            gh_job(3, "Analyst"),  # untouched
            gh_job(4, "Recruiter Liaison"),  # new -> added
            # 2 is gone -> removed
        ],
    )
    second = run_of(refresh(fast_client, sid))
    assert second["status"] == "ok"
    assert second["items_seen"] == 3
    assert counters(second) == {
        "added": 1,
        "changed": 1,
        "removed": 1,
        "reappeared": 0,
        "unchanged": 1,
    }
    assert "1 added, 1 changed, 1 removed, 0 reappeared, 1 unchanged" in second["message"]

    clock.advance(seconds=3600)
    ats.greenhouse(
        "acme",
        [
            gh_job(1, "Senior Engineer"),
            gh_job(2, "Designer"),  # back -> reappeared
            gh_job(3, "Analyst"),
            gh_job(4, "Recruiter Liaison"),
        ],
    )
    third = run_of(refresh(fast_client, sid))
    assert counters(third) == {
        "added": 0,
        "changed": 0,
        "removed": 0,
        "reappeared": 1,
        "unchanged": 3,
    }

    data = analysis(fast_client)
    by_type: dict[str, list[str]] = {}
    for event in data["events"]:
        by_type.setdefault(event["type"], []).append(event["title"])
    assert sorted(by_type) == ["added", "baseline", "changed", "reappeared", "removed"]
    assert by_type["changed"] == ["Senior Engineer"]
    assert by_type["removed"] == ["Designer"]
    assert by_type["reappeared"] == ["Designer"]
    assert by_type["added"] == ["Recruiter Liaison"]
    assert data["stats"]["snapshots"] == 3
    assert all(r["status"] == "active" for r in data["roles"])


def test_unchanged_board_reports_only_unchanged(
    fast_client: TestClient, ats: FakeAts, clock: FakeClock
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer"), gh_job(2, "Designer")])
    sid = add_source(fast_client)["id"]
    refresh(fast_client, sid)
    clock.advance(seconds=120)
    run = run_of(refresh(fast_client, sid))
    assert counters(run) == {
        "added": 0,
        "changed": 0,
        "removed": 0,
        "reappeared": 0,
        "unchanged": 2,
    }


def test_history_is_newest_first_and_capped_at_100(
    fast_client: TestClient, ats: FakeAts, clock: FakeClock
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    sid = add_source(fast_client)["id"]
    ids = []
    for _ in range(103):
        clock.advance(seconds=1)
        ids.append(run_of(refresh(fast_client, sid))["id"])
    runs = fast_client.get(f"/api/sources/{sid}/runs").json()
    assert len(runs) == 100
    assert [r["id"] for r in runs] == sorted(ids, reverse=True)[:100]
    assert runs[0]["started_at"] >= runs[-1]["started_at"]
    summary = fast_client.get("/api/sources").json()[0]
    assert summary["runs_total"] == 103


def test_refresh_unknown_source_is_404(client: TestClient) -> None:
    response = refresh(client, 4242)
    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"
    assert client.get("/api/sources/4242/runs").status_code == 404


def test_provider_name_is_never_used_for_the_company(client: TestClient, ats: FakeAts) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer", company_name="Totally Different LLC")])
    sid = add_source(client, company_name="Acme Robotics")["id"]
    refresh(client, sid)
    assert [c["name"] for c in analysis(client)["companies"]] == ["Acme Robotics"]


# -- failure semantics -------------------------------------------------------------------------
FAILURES: list[tuple[str, Callable[[FakeAts], None], dict[str, Any]]] = [
    (
        "404",
        lambda a: a.status(GREENHOUSE_HOST, GH_PATH, 404),
        {"error_kind": "not_found", "http_status": 404},
    ),
    (
        "401",
        lambda a: a.status(GREENHOUSE_HOST, GH_PATH, 401),
        {"error_kind": "unauthorized", "http_status": 401},
    ),
    (
        "403",
        lambda a: a.status(GREENHOUSE_HOST, GH_PATH, 403),
        {"error_kind": "unauthorized", "http_status": 403},
    ),
    (
        "429 with Retry-After",
        lambda a: a.status(GREENHOUSE_HOST, GH_PATH, 429, headers={"Retry-After": "120"}),
        {"error_kind": "rate_limited", "http_status": 429, "retry_after_s": 120},
    ),
    (
        "429 with an HTTP date",
        lambda a: a.status(
            GREENHOUSE_HOST, GH_PATH, 429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
        ),
        {"error_kind": "rate_limited", "http_status": 429, "retry_after_s": None},
    ),
    (
        "500",
        lambda a: a.status(GREENHOUSE_HOST, GH_PATH, 500),
        {"error_kind": "server_error", "http_status": 500},
    ),
    (
        "503",
        lambda a: a.status(GREENHOUSE_HOST, GH_PATH, 503),
        {"error_kind": "server_error", "http_status": 503},
    ),
    (
        "timeout",
        lambda a: a.fail(GREENHOUSE_HOST, GH_PATH, httpx.ReadTimeout("slow")),
        {"error_kind": "timeout", "http_status": None},
    ),
    (
        "network",
        lambda a: a.fail(GREENHOUSE_HOST, GH_PATH, httpx.ConnectError("refused")),
        {"error_kind": "network", "http_status": None},
    ),
    (
        "html instead of JSON",
        lambda a: a.raw(GREENHOUSE_HOST, GH_PATH, b"<html>Down for maintenance</html>"),
        {"error_kind": "malformed", "http_status": 200},
    ),
    (
        "wrong JSON shape",
        lambda a: a.json(GREENHOUSE_HOST, GH_PATH, {"jobs": "none"}),
        {"error_kind": "malformed", "http_status": 200},
    ),
    (
        "every job invalid",
        lambda a: a.greenhouse("acme", [{"id": 1}, {"id": 2, "title": ""}]),
        {"error_kind": "malformed", "http_status": 200, "items_seen": 2},
    ),
    (
        "too many items",
        lambda a: a.greenhouse("acme", [{"id": i, "title": "T"} for i in range(5001)]),
        {"error_kind": "too_large", "http_status": 200, "items_seen": 5001},
    ),
    (
        "announced size over the cap",
        lambda a: a.raw(
            GREENHOUSE_HOST, GH_PATH, b"{}", headers={"content-length": str(11 * 1024 * 1024)}
        ),
        {"error_kind": "too_large", "http_status": 200},
    ),
    (
        "redirect to another host",
        lambda a: a.route(
            GREENHOUSE_HOST,
            GH_PATH,
            lambda _r: httpx.Response(302, headers={"Location": "https://evil.example/jobs"}),
        ),
        {"error_kind": "malformed", "http_status": 302},
    ),
]


@pytest.mark.parametrize(("label", "arrange", "expected"), FAILURES, ids=[f[0] for f in FAILURES])
def test_a_failed_refresh_is_a_stored_run_with_no_snapshot_and_removes_nothing(
    fast_client: TestClient,
    ats: FakeAts,
    clock: FakeClock,
    label: str,
    arrange: Callable[[FakeAts], None],
    expected: dict[str, Any],
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer"), gh_job(2, "Designer")])
    sid = add_source(fast_client)["id"]
    assert run_of(refresh(fast_client, sid))["status"] == "ok"
    before = analysis(fast_client)

    clock.advance(seconds=600)
    arrange(ats)
    run = run_of(refresh(fast_client, sid))  # the *request* succeeds; the run records the failure
    assert run["status"] == "failed", label
    for key, value in expected.items():
        assert run[key] == value, (label, key)
    assert counters(run) == dict.fromkeys(COUNTERS, 0)
    assert "No snapshot was stored" in run["message"]

    # nothing changed: same snapshots, same roles, nothing removed
    clock.advance(seconds=1)
    after = analysis(fast_client, as_of=before["as_of"])
    assert after["stats"]["snapshots"] == before["stats"]["snapshots"] == 1
    assert after["roles"] == before["roles"]
    assert all(role["status"] == "active" for role in analysis(fast_client)["roles"])
    assert not [e for e in analysis(fast_client)["events"] if e["type"] == "removed"]

    # the failure is in the history, the previous success is still there
    runs = fast_client.get(f"/api/sources/{sid}/runs").json()
    assert [r["status"] for r in runs] == ["failed", "ok"]
    summary = fast_client.get("/api/sources").json()[0]
    assert summary["last_run"]["status"] == "failed"
    assert summary["last_ok_at"] == runs[1]["finished_at"]


def test_a_failure_before_any_success_leaves_the_database_empty(
    client: TestClient, ats: FakeAts
) -> None:
    ats.status(GREENHOUSE_HOST, GH_PATH, 404)
    sid = add_source(client)["id"]
    run = run_of(refresh(client, sid))
    assert (run["status"], run["error_kind"]) == ("failed", "not_found")
    data = analysis(client)
    assert data["companies"] == []
    assert data["stats"]["snapshots"] == 0
    assert len(client.get(f"/api/sources/{sid}/runs").json()) == 1


def test_recovery_after_a_failure_continues_from_the_last_good_snapshot(
    fast_client: TestClient, ats: FakeAts, clock: FakeClock
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer"), gh_job(2, "Designer")])
    sid = add_source(fast_client)["id"]
    refresh(fast_client, sid)

    clock.advance(seconds=100)
    ats.status(GREENHOUSE_HOST, GH_PATH, 500)
    assert run_of(refresh(fast_client, sid))["status"] == "failed"

    clock.advance(seconds=100)
    ats.greenhouse("acme", [gh_job(1, "Engineer"), gh_job(3, "Analyst")])
    ok = run_of(refresh(fast_client, sid))
    assert counters(ok) == {"added": 1, "changed": 0, "removed": 1, "reappeared": 0, "unchanged": 1}


def test_some_invalid_jobs_are_dropped_and_counted_in_the_message(
    client: TestClient, ats: FakeAts
) -> None:
    ats.greenhouse(
        "acme",
        [
            gh_job(1, "Engineer", url="javascript:alert(1)"),
            gh_job(None, "No id"),
            {"id": 3, "title": ""},
            gh_job(4, "Designer"),
        ],
    )
    run = run_of(refresh(client, add_source(client)["id"]))
    assert run["status"] == "ok"
    assert run["items_seen"] == 4
    assert "2 jobs dropped" in run["message"]
    assert "missing id" in run["message"]
    assert "optional fields left empty: url x1" in run["message"]
    assert {r["title"] for r in analysis(client)["roles"]} == {"Engineer", "Designer"}


def test_run_message_never_contains_provider_markup(client: TestClient, ats: FakeAts) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    run = run_of(refresh(client, add_source(client)["id"]))
    assert "<" not in run["message"]
    assert "Never stored" not in run["message"]


# -- minimum interval --------------------------------------------------------------------------
def test_refreshing_again_within_a_minute_is_429_too_soon(
    client: TestClient, ats: FakeAts, clock: FakeClock
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    sid = add_source(client)["id"]
    assert run_of(refresh(client, sid))["status"] == "ok"
    requests_after_first = len(ats.requests)

    clock.advance(seconds=25)
    response = refresh(client, sid)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "35"
    error = error_of(response)
    assert error["code"] == "too_soon"
    assert error["details"] == {"retry_after_s": 35, "min_interval_s": 60}
    assert len(ats.requests) == requests_after_first  # no request was made
    assert len(client.get(f"/api/sources/{sid}/runs").json()) == 1  # and no run was stored

    clock.advance(seconds=35)
    assert run_of(refresh(client, sid))["status"] == "ok"


def test_the_interval_also_applies_after_a_failed_run(
    client: TestClient, ats: FakeAts, clock: FakeClock
) -> None:
    ats.status(GREENHOUSE_HOST, GH_PATH, 429, headers={"Retry-After": "3600"})
    sid = add_source(client)["id"]
    assert run_of(refresh(client, sid))["error_kind"] == "rate_limited"
    clock.advance(seconds=10)
    assert refresh(client, sid).status_code == 429
    assert len(ats.requests) == 1


def test_intervals_are_per_source(client: TestClient, ats: FakeAts) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    ats.greenhouse("beta", [gh_job(2, "Analyst")])
    one = add_source(client, token="acme")["id"]
    two = add_source(client, token="beta", company_name="Beta")["id"]
    assert refresh(client, one).status_code == 200
    assert refresh(client, two).status_code == 200  # a different source is not throttled


def test_the_minimum_interval_can_be_disabled_for_tests(
    fast_client: TestClient, ats: FakeAts
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    sid = add_source(fast_client)["id"]
    assert refresh(fast_client, sid).status_code == 200
    assert refresh(fast_client, sid).status_code == 200


# -- providers through the API -----------------------------------------------------------------
def test_lever_refresh_walks_all_pages(fast_client: TestClient, ats: FakeAts) -> None:
    ats.lever("acme", [lever_posting(f"id-{i}", f"Role {i}") for i in range(230)])
    sid = add_source(fast_client, provider="lever")["id"]
    run = run_of(refresh(fast_client, sid))
    assert run["status"] == "ok"
    assert run["items_seen"] == 230
    assert LEVER_HOST in run["message"]
    assert len(analysis(fast_client)["roles"]) == 230
    assert ats.count(LEVER_HOST) == 3


def test_ashby_refresh_skips_unlisted_and_reports_it(client: TestClient, ats: FakeAts) -> None:
    ats.ashby(
        "acme",
        [
            ashby_job("Listed", job_url="https://jobs.ashbyhq.com/acme/aaaaaaaa-1"),
            ashby_job(
                "Hidden", is_listed=False, job_url="https://jobs.ashbyhq.com/acme/bbbbbbbb-2"
            ),
        ],
    )
    sid = add_source(client, provider="ashby")["id"]
    run = run_of(refresh(client, sid))
    assert run["status"] == "ok"
    assert "1 unlisted jobs skipped" in run["message"]
    assert ASHBY_HOST in run["message"]
    assert [r["title"] for r in analysis(client)["roles"]] == ["Listed"]


def test_every_provider_request_is_a_get(client: TestClient, ats: FakeAts) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    ats.lever("acme", [lever_posting("a1", "Engineer")])
    ats.ashby("acme", [ashby_job("Engineer")])
    for provider in ("greenhouse", "lever", "ashby"):
        refresh(client, add_source(client, provider=provider)["id"])
    assert len(ats.requests) == 3
    assert {r.method for r in ats.requests} == {"GET"}
    assert {r.url.scheme for r in ats.requests} == {"https"}
    assert {r.headers["user-agent"] for r in ats.requests} == {"RecruitRadar/0.1.0 (+read-only)"}
    assert all(not r.content for r in ats.requests)
