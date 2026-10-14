"""``GET /api/analysis``, ``GET /api/companies/{id}`` and ``/api/merge-decisions``."""

from __future__ import annotations

from typing import Any

import pytest
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

from recruit_radar.engine import analyze


# -- analysis ----------------------------------------------------------------------------------
def test_empty_database_gives_an_empty_analysis(client: TestClient) -> None:
    data = analysis(client)
    assert data == {
        "as_of": "2026-10-13T12:00:00Z",
        "companies": [],
        "roles": [],
        "events": [],
        "merge_candidates": [],
        "stats": {"snapshots": 0, "postings_observed": 0, "companies": 0, "active_roles": 0},
    }


def test_default_as_of_is_now_in_whole_seconds(client: TestClient, clock: FakeClock) -> None:
    clock.advance(seconds=5)
    assert analysis(client)["as_of"] == "2026-10-13T12:00:05Z"


@pytest.mark.parametrize(
    "value",
    [
        "yesterday",
        "2026-10-13",
        "2026-10-13T12:00:00",
        "2026-10-13T12:00:00+00:00",
        "2026-10-13T12:00:00.5Z",
        "2026-10-13 12:00:00Z",
        "2026-13-01T00:00:00Z",
        "2026-02-30T00:00:00Z",
        "２０２６-10-13T12:00:00Z",
        "",
    ],
)
def test_malformed_as_of_is_422(client: TestClient, value: str) -> None:
    response = client.get("/api/analysis", params={"as_of": value})
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "invalid_as_of"
    assert error["details"] == {"as_of": value}


def test_as_of_controls_which_snapshots_count_and_the_derived_numbers(
    client: TestClient,
) -> None:
    import_csv(
        client,
        csv_of(("Acme", "Engineer", "NYC", "")),
        label="early",
        observed_at="2026-08-01T00:00:00Z",
    )
    import_csv(
        client,
        csv_of(("Acme", "Designer", "NYC", "")),
        label="late",
        observed_at="2026-10-01T00:00:00Z",
    )
    early = analysis(client, as_of="2026-08-15T00:00:00Z")
    assert early["stats"]["snapshots"] == 1
    assert [r["title"] for r in early["roles"]] == ["Engineer"]
    freshness = {c["key"]: c for c in early["companies"][0]["components"]}["freshness"]
    assert freshness["inputs"] == {"days_since_last_seen": 14}

    late = analysis(client, as_of="2026-10-02T00:00:00Z")
    assert late["stats"]["snapshots"] == 2
    assert {r["title"] for r in late["roles"]} == {"Engineer", "Designer"}


def test_the_api_returns_exactly_what_the_engine_computes_from_the_stored_snapshots(
    client: TestClient, ats: FakeAts, clock: FakeClock
) -> None:
    """Replay equivalence: the endpoint is the engine applied to what was stored."""
    client.put(
        "/api/profile", json={"include_keywords": ["engineer"], "exclude_keywords": ["intern"]}
    )
    ats.greenhouse("acme", [gh_job(1, "Engineer"), gh_job(2, "Engineering Intern")])
    sid = add_source(client)["id"]
    refresh(client, sid)
    clock.advance(seconds=3600)
    import_csv(client, csv_of(("Acme", "Engineer", "New York, NY", "remote")), label="leads")
    clock.advance(seconds=3600)

    expected = analyze(
        {
            "as_of": "2026-10-13T14:00:00Z",
            "profile": {"include_keywords": ["engineer"], "exclude_keywords": ["intern"]},
            "decisions": [],
            "snapshots": [
                {
                    "snapshot_id": "s1",
                    "source_kind": "greenhouse",
                    "source_ref": "acme",
                    "observed_at": "2026-10-13T12:00:00Z",
                    "mode": "full",
                    "postings": [
                        {
                            "source_posting_id": "1",
                            "company_name": "Acme Inc.",
                            "title": "Engineer",
                            "location": "New York, NY",
                            "work_mode": "unknown",
                            "department": "Engineering",
                            "url": "https://boards.greenhouse.io/acme/jobs/1",
                            "posted_at": "2026-09-20",
                        },
                        {
                            "source_posting_id": "2",
                            "company_name": "Acme Inc.",
                            "title": "Engineering Intern",
                            "location": "New York, NY",
                            "work_mode": "unknown",
                            "department": "Engineering",
                            "url": "https://boards.greenhouse.io/acme/jobs/2",
                            "posted_at": "2026-09-20",
                        },
                    ],
                },
                {
                    "snapshot_id": "s2",
                    "source_kind": "csv",
                    "source_ref": "leads",
                    "observed_at": "2026-10-13T13:00:00Z",
                    "mode": "additive",
                    "postings": [
                        {
                            "company_name": "Acme",
                            "title": "Engineer",
                            "location": "New York, NY",
                            "work_mode": "remote",
                        }
                    ],
                },
            ],
        }
    )
    assert analysis(client) == expected


def test_the_same_company_spelled_three_ways_is_one_company(client: TestClient) -> None:
    import_csv(
        client,
        csv_of(
            ("Acme", "Engineer", "NYC", ""),
            ("ACME Inc.", "Designer", "NYC", ""),
            ("acme, inc", "Analyst", "NYC", ""),
        ),
    )
    data = analysis(client)
    assert len(data["companies"]) == 1
    company = data["companies"][0]
    assert company["aliases"] == ["ACME Inc.", "Acme", "acme, inc"]
    assert company["active_roles"] == 3


def test_identical_titles_in_one_source_with_different_ids_are_two_roles(
    client: TestClient, ats: FakeAts
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer"), gh_job(2, "Engineer")])
    refresh(client, add_source(client)["id"])
    data = analysis(client)
    assert len(data["roles"]) == 2
    assert data["companies"][0]["active_roles"] == 2


def test_greenhouse_and_csv_corroborate_one_canonical_role(
    client: TestClient, ats: FakeAts
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Platform Engineer", location="Austin, TX")])
    refresh(client, add_source(client, company_name="Acme")["id"])
    import_csv(client, csv_of(("Acme", "Platform Engineer", "TX Austin", "")), label="partner-list")
    data = analysis(client)
    assert len(data["roles"]) == 1
    sources = {(o["source_kind"], o["source_ref"]) for o in data["roles"][0]["observations"]}
    assert sources == {("greenhouse", "acme"), ("csv", "partner-list")}
    confidence = {c["key"]: c for c in data["companies"][0]["components"]}["source_confidence"]
    assert confidence["value"] == 1000  # greenhouse 1000 + 100 corroboration, capped at 1000
    assert confidence["inputs"]["corroborated"] == 1


# -- merge decisions ---------------------------------------------------------------------------
def doordash_data(client: TestClient) -> None:
    import_csv(
        client,
        csv_of(
            ("DoorDash", "Engineer", "SF", ""),
            ("Door Dash", "Designer", "SF", ""),
            ("Acme Robotics", "Engineer", "SF", ""),
            ("Acme Robotic", "Analyst", "SF", ""),
        ),
    )


def candidate(data: dict[str, Any], reason: str) -> dict[str, Any]:
    matches = [c for c in data["merge_candidates"] if c["reason"] == reason]
    assert len(matches) == 1, data["merge_candidates"]
    return dict(matches[0])


def test_similar_names_are_candidates_never_auto_merged(client: TestClient) -> None:
    doordash_data(client)
    data = analysis(client)
    assert len(data["companies"]) == 4
    spacing = candidate(data, "spacing_variant")
    assert (spacing["a_key"], spacing["b_key"]) == ("door dash", "doordash")
    typo = candidate(data, "near_typo")
    assert (typo["a_key"], typo["b_key"]) == ("acme robotic", "acme robotics")


def test_a_merge_decision_changes_the_analysis_and_can_be_undone(client: TestClient) -> None:
    doordash_data(client)
    before = analysis(client)
    created = client.post(
        "/api/merge-decisions",
        json={"a_key": "door dash", "b_key": "doordash", "decision": "merge"},
    )
    assert created.status_code == 201
    row = created.json()
    assert set(row) == {"id", "a_key", "b_key", "decision", "created_at"}
    assert row["decision"] == "merge"

    merged = analysis(client)
    assert len(merged["companies"]) == 3
    door = next(c for c in merged["companies"] if c["key"] == "door dash")
    assert door["active_roles"] == 2
    assert sorted(door["aliases"]) == ["Door Dash", "DoorDash"]
    assert all(c["reason"] != "spacing_variant" for c in merged["merge_candidates"])
    # roles of both spellings now belong to the same company
    assert {r["company_id"] for r in merged["roles"] if r["title"] in ("Engineer", "Designer")} >= {
        door["company_id"]
    }

    assert client.delete(f"/api/merge-decisions/{row['id']}").status_code == 204
    restored = analysis(client)
    assert len(restored["companies"]) == 4
    assert restored["companies"] == before["companies"]
    assert candidate(restored, "spacing_variant")["a_key"] == "door dash"


def test_not_same_hides_the_candidate_without_merging(client: TestClient) -> None:
    doordash_data(client)
    response = client.post(
        "/api/merge-decisions",
        json={"a_key": "acme robotic", "b_key": "acme robotics", "decision": "not_same"},
    )
    assert response.status_code == 201
    data = analysis(client)
    assert len(data["companies"]) == 4
    assert all(c["reason"] != "near_typo" for c in data["merge_candidates"])


def test_decisions_are_listed_in_creation_order(client: TestClient) -> None:
    doordash_data(client)
    assert client.get("/api/merge-decisions").json() == []
    first = client.post(
        "/api/merge-decisions",
        json={"a_key": "door dash", "b_key": "doordash", "decision": "merge"},
    ).json()
    second = client.post(
        "/api/merge-decisions",
        json={"a_key": "acme robotic", "b_key": "acme robotics", "decision": "not_same"},
    ).json()
    listed = client.get("/api/merge-decisions").json()
    assert [d["id"] for d in listed] == [first["id"], second["id"]]


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"a_key": "doordash", "b_key": "door dash", "decision": "merge"}, 422, "invalid_decision"),
        (
            {"a_key": "door dash", "b_key": "door dash", "decision": "merge"},
            422,
            "invalid_decision",
        ),
        (
            {"a_key": "door dash", "b_key": "nonexistent co", "decision": "merge"},
            422,
            "invalid_decision",
        ),
        ({"a_key": "door dash", "b_key": "doordash", "decision": "maybe"}, 422, "invalid_decision"),
        ({"a_key": "door dash", "b_key": "doordash"}, 422, "invalid_decision"),
        (
            {"a_key": "door dash", "b_key": "doordash", "decision": "merge", "x": 1},
            422,
            "invalid_decision",
        ),
    ],
)
def test_invalid_decisions_are_422(
    client: TestClient, body: dict[str, Any], status: int, code: str
) -> None:
    doordash_data(client)
    response = client.post("/api/merge-decisions", json=body)
    assert response.status_code == status
    assert error_of(response)["code"] == code
    assert client.get("/api/merge-decisions").json() == []


def test_a_second_decision_for_the_same_pair_is_409(client: TestClient) -> None:
    doordash_data(client)
    body = {"a_key": "door dash", "b_key": "doordash", "decision": "merge"}
    first = client.post("/api/merge-decisions", json=body)
    assert first.status_code == 201
    for decision in ("merge", "not_same"):
        again = client.post("/api/merge-decisions", json={**body, "decision": decision})
        assert again.status_code == 409
        error = error_of(again)
        assert error["code"] == "decision_exists"
        assert error["details"]["id"] == first.json()["id"]


def test_delete_unknown_decision_is_404(client: TestClient) -> None:
    response = client.delete("/api/merge-decisions/777")
    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


# -- company detail ----------------------------------------------------------------------------
def test_company_detail_has_roles_events_and_per_source_freshness(
    client: TestClient, ats: FakeAts, clock: FakeClock
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer"), gh_job(2, "Designer")])
    ats.greenhouse("beta", [gh_job(9, "Analyst")])
    sid = add_source(client, company_name="Acme")["id"]
    beta = add_source(client, token="beta", company_name="Beta")["id"]
    refresh(client, sid)
    refresh(client, beta)
    clock.advance(seconds=7200)
    import_csv(client, csv_of(("Acme", "Writer", "", "")), label="leads")

    data = analysis(client)
    acme = company_named(data, "Acme")
    response = client.get(f"/api/companies/{acme['company_id']}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["as_of"] == data["as_of"]
    assert detail["company"] == acme
    assert {r["title"] for r in detail["roles"]} == {"Engineer", "Designer", "Writer"}
    assert all(r["company_id"] == acme["company_id"] for r in detail["roles"])
    assert all(e["company_id"] == acme["company_id"] for e in detail["events"])
    assert {e["title"] for e in detail["events"]} == {"Engineer", "Designer", "Writer"}
    assert detail["shortlist"] == {
        "company_id": acme["company_id"],
        "shortlisted": False,
        "name": "Acme",
        "note": "",
        "added_at": None,
    }

    freshness = {(f["source_kind"], f["source_ref"]): f for f in detail["source_freshness"]}
    assert set(freshness) == {("greenhouse", "acme"), ("csv", "leads")}
    gh = freshness[("greenhouse", "acme")]
    assert gh["source_id"] == sid
    assert gh["active_roles"] == 2
    assert gh["last_observed_at"] == "2026-10-13T12:00:00Z"
    csv_entry = freshness[("csv", "leads")]
    assert csv_entry["source_id"] is None
    assert csv_entry["last_observed_at"] == "2026-10-13T14:00:00Z"


def test_company_detail_unknown_company_is_404(client: TestClient) -> None:
    for company_id in ("c_000000000000", "nope", "..", "%2e%2e", "a%2Fb"):
        response = client.get(f"/api/companies/{company_id}")
        assert response.status_code == 404, company_id
        assert error_of(response)["code"] == "not_found"


def test_company_detail_honours_as_of(client: TestClient) -> None:
    import_csv(client, csv_of(("Acme", "Engineer", "", "")), observed_at="2026-09-01T00:00:00Z")
    company_id = analysis(client)["companies"][0]["company_id"]
    early = client.get(f"/api/companies/{company_id}", params={"as_of": "2026-08-01T00:00:00Z"})
    assert early.status_code == 404  # the company did not exist yet
    bad = client.get(f"/api/companies/{company_id}", params={"as_of": "soon"})
    assert error_of(bad)["code"] == "invalid_as_of"
