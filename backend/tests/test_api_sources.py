"""``/api/sources``: create, list, delete and the token rules at the API boundary."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rr_support import (
    FakeAts,
    add_source,
    analysis,
    error_of,
    gh_job,
    refresh,
)
from sqlalchemy import text

from recruit_radar.config import Settings


def test_create_source_returns_the_row_with_the_host_it_will_contact(client: TestClient) -> None:
    created = add_source(client, provider="lever", token="Acme-Corp.1", company_name="  Acme Inc. ")
    assert created["provider"] == "lever"
    assert created["token"] == "Acme-Corp.1"
    assert created["company_name"] == "Acme Inc."
    assert created["base_host"] == "api.lever.co"
    assert created["last_run"] is None
    assert created["last_ok_at"] is None
    assert created["runs_total"] == 0
    assert created["created_at"] == "2026-10-13T12:00:00Z"
    assert isinstance(created["id"], int)


def test_list_sources_is_ordered_and_carries_the_last_run(client: TestClient, ats: FakeAts) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    first = add_source(client, token="acme")
    second = add_source(client, provider="ashby", token="beta", company_name="Beta")
    assert refresh(client, first["id"]).json()["status"] == "ok"

    listed = client.get("/api/sources").json()
    assert [s["id"] for s in listed] == [first["id"], second["id"]]
    assert listed[0]["runs_total"] == 1
    assert listed[0]["last_run"]["status"] == "ok"
    assert listed[0]["last_run"]["items_seen"] == 1
    assert listed[0]["last_ok_at"] == listed[0]["last_run"]["finished_at"]
    assert listed[1]["last_run"] is None


def test_empty_source_list(client: TestClient) -> None:
    response = client.get("/api/sources")
    assert response.status_code == 200
    assert response.json() == []


def test_the_same_board_cannot_be_watched_twice(client: TestClient) -> None:
    original = add_source(client, token="Acme")
    for token in ("Acme", "acme", "ACME"):
        response = client.post(
            "/api/sources", json={"provider": "greenhouse", "token": token, "company_name": "X"}
        )
        assert response.status_code == 409
        error = error_of(response)
        assert error["code"] == "source_exists"
        assert error["details"]["source_id"] == original["id"]
    # the same token on another provider is a different board
    assert add_source(client, provider="lever", token="Acme")["id"] != original["id"]


@pytest.mark.parametrize(
    "token",
    ["", "..", "../", "a/b", "a%2fb", "%2e%2e", "a b", "é", "ｅｘ", "x" * 101, "a?b", "a#b", "\n"],
)
def test_invalid_tokens_are_422_invalid_token(client: TestClient, token: str) -> None:
    response = client.post(
        "/api/sources", json={"provider": "greenhouse", "token": token, "company_name": "Acme"}
    )
    assert response.status_code == 422
    assert error_of(response)["code"] == "invalid_token"
    assert client.get("/api/sources").json() == []


def test_the_maximum_length_token_is_accepted(client: TestClient) -> None:
    assert add_source(client, token="t" * 100)["token"] == "t" * 100


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "workday", "token": "acme", "company_name": "Acme"},
        {"provider": "greenhouse", "token": "acme", "company_name": "   "},
        {"provider": "greenhouse", "token": "acme", "company_name": "n" * 201},
        {"provider": "greenhouse", "token": "acme"},
        {"provider": "greenhouse", "token": "acme", "company_name": "Acme", "url": "https://x"},
        {"provider": "lever", "token": 12345, "company_name": "Acme"},
    ],
)
def test_other_invalid_source_bodies_are_422(client: TestClient, body: dict[str, object]) -> None:
    response = client.post("/api/sources", json=body)
    assert response.status_code == 422
    assert error_of(response)["code"] in {"invalid_source", "invalid_token"}


def test_a_url_can_never_be_supplied_in_place_of_a_token(client: TestClient) -> None:
    for token in (
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        "http://127.0.0.1:8788",
        "//evil.example",
    ):
        response = client.post(
            "/api/sources", json={"provider": "greenhouse", "token": token, "company_name": "A"}
        )
        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid_token"


def test_delete_removes_the_source_its_runs_and_its_data(client: TestClient, ats: FakeAts) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer"), gh_job(2, "Designer")])
    source = add_source(client)
    assert refresh(client, source["id"]).json()["status"] == "ok"
    assert len(analysis(client)["roles"]) == 2

    response = client.delete(f"/api/sources/{source['id']}")
    assert response.status_code == 204
    assert response.content == b""

    assert client.get("/api/sources").json() == []
    assert client.get(f"/api/sources/{source['id']}/runs").status_code == 404
    data = analysis(client)
    assert data["roles"] == []
    assert data["stats"]["snapshots"] == 0


def test_delete_unknown_source_is_404(client: TestClient) -> None:
    response = client.delete("/api/sources/999")
    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


def test_deleting_one_source_keeps_the_others(client: TestClient, ats: FakeAts) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    ats.greenhouse("beta", [gh_job(5, "Analyst")])
    keep = add_source(client, token="acme", company_name="Acme")
    drop = add_source(client, token="beta", company_name="Beta")
    refresh(client, keep["id"])
    refresh(client, drop["id"])
    assert client.delete(f"/api/sources/{drop['id']}").status_code == 204
    names = [c["name"] for c in analysis(client)["companies"]]
    assert names == ["Acme"]


def test_base_host_reflects_a_test_override(
    make_app: Callable[..., FastAPI],
    settings: Settings,
    client_factory: Callable[..., TestClient],
) -> None:
    custom = settings.with_overrides(
        base_urls={**settings.base_urls, "greenhouse": "http://127.0.0.1:8788"}
    )
    client = client_factory(make_app(settings=custom))
    created = add_source(client)
    assert created["base_host"] == "127.0.0.1:8788"


def test_tampered_rows_cannot_smuggle_a_path_into_a_request(
    client: TestClient, app: FastAPI, ats: FakeAts
) -> None:
    """Even a token written straight into the database never becomes part of a URL."""
    source = add_source(client)
    with app.state.recruit_radar.engine.begin() as connection:
        connection.execute(
            text("UPDATE sources SET token = :t WHERE id = :i"),
            {"t": "../../admin", "i": source["id"]},
        )
    response = refresh(client, source["id"])
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "failed"
    assert run["error_kind"] == "malformed"
    assert ats.requests == []  # nothing was sent
