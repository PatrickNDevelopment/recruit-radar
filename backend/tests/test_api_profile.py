"""``GET/PUT /api/profile`` and its effect on the analysis."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from rr_support import analysis, company_named, csv_of, error_of, import_csv


def test_default_profile_is_empty(client: TestClient) -> None:
    response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json() == {"include_keywords": [], "exclude_keywords": []}


def test_put_then_get_round_trips_and_trims(client: TestClient) -> None:
    body = {
        "include_keywords": ["  Engineer ", "data scientist", "Ingénieur"],
        "exclude_keywords": ["intern", "intern", "Sénior"],
    }
    put = client.put("/api/profile", json=body)
    assert put.status_code == 200
    expected = {
        "include_keywords": ["Engineer", "data scientist", "Ingénieur"],
        "exclude_keywords": ["intern", "Sénior"],  # exact duplicates collapse
    }
    assert put.json() == expected
    assert client.get("/api/profile").json() == expected


def test_put_replaces_the_whole_profile(client: TestClient) -> None:
    client.put("/api/profile", json={"include_keywords": ["a"], "exclude_keywords": ["b"]})
    client.put("/api/profile", json={"include_keywords": ["c"]})
    assert client.get("/api/profile").json() == {"include_keywords": ["c"], "exclude_keywords": []}


def test_limits_are_50_keywords_of_60_characters(client: TestClient) -> None:
    fifty = [f"kw{i}" for i in range(50)]
    assert client.put("/api/profile", json={"include_keywords": fifty}).status_code == 200
    too_many = client.put("/api/profile", json={"include_keywords": [*fifty, "one more"]})
    assert too_many.status_code == 422
    assert error_of(too_many)["code"] == "invalid_profile"

    sixty = "k" * 60
    assert client.put("/api/profile", json={"exclude_keywords": [sixty]}).status_code == 200
    too_long = client.put("/api/profile", json={"exclude_keywords": [sixty + "k"]})
    assert too_long.status_code == 422
    assert error_of(too_long)["details"] == {"field": "exclude_keywords", "index": 0}
    # counted in characters (code points), not bytes
    assert client.put("/api/profile", json={"include_keywords": ["é" * 60]}).status_code == 200


@pytest.mark.parametrize("keyword", ["", "   ", "!!!", "—", "\t"])
def test_keywords_that_can_never_match_are_refused(client: TestClient, keyword: str) -> None:
    response = client.put("/api/profile", json={"include_keywords": ["fine", keyword]})
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "invalid_profile"
    assert error["details"]["index"] == 1
    assert client.get("/api/profile").json()["include_keywords"] == []  # nothing was stored


def test_a_failed_put_leaves_the_previous_profile(client: TestClient) -> None:
    client.put("/api/profile", json={"include_keywords": ["keep"]})
    client.put("/api/profile", json={"include_keywords": ["new", "!!!"]})
    assert client.get("/api/profile").json()["include_keywords"] == ["keep"]


def test_profile_drives_relevance_in_the_analysis(client: TestClient) -> None:
    csv = csv_of(
        ("Acme", "Backend Engineer", "NYC", "remote"),
        ("Acme", "Engineering Intern", "NYC", "remote"),
        ("Acme", "Office Manager", "NYC", "onsite"),
    )
    assert import_csv(client, csv).status_code == 201

    before = company_named(analysis(client), "Acme")
    assert before["relevant_roles"] is None  # no keywords: relevance is missing, not zero
    reasons = {c["key"]: c["reason_code"] for c in before["components"]}
    assert reasons["role_relevance"] == "no_keywords"

    client.put(
        "/api/profile", json={"include_keywords": ["engineer"], "exclude_keywords": ["intern"]}
    )
    after = analysis(client)
    acme = company_named(after, "Acme")
    assert acme["relevant_roles"] == 1
    assert acme["active_roles"] == 3
    relevance = {c["key"]: c for c in acme["components"]}["role_relevance"]
    assert relevance["inputs"] == {"relevant": 1, "active": 3}
    assert relevance["value"] == 333  # rhu(1000 * 1 / 3)
    flags: dict[str, Any] = {r["title"]: r["relevant"] for r in after["roles"]}
    assert flags == {
        "Backend Engineer": True,
        "Engineering Intern": False,
        "Office Manager": False,
    }
