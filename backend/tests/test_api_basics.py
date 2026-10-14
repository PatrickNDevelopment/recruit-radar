"""Health, the error envelope, request validation, CORS and the foreign-origin guard."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rr_support import analysis, csv_of, error_of, import_csv
from sqlalchemy import text

from recruit_radar import __version__
from recruit_radar.config import Settings

ALLOWED = "http://localhost:5173"
OTHER_ALLOWED = "http://localhost:4174"
FOREIGN = "http://evil.example"


# -- health ------------------------------------------------------------------------------------
def test_health_reports_versions_and_database(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app_version": __version__,
        "schema_version": 1,
        "db_ok": True,
    }


def test_health_degrades_instead_of_failing_when_the_database_is_broken(
    client: TestClient, app: FastAPI
) -> None:
    with app.state.recruit_radar.engine.begin() as connection:
        connection.execute(text("DROP TABLE meta"))
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["db_ok"] is False
    assert body["status"] == "degraded"
    assert body["schema_version"] is None
    assert body["app_version"] == __version__


# -- error envelope ----------------------------------------------------------------------------
def test_unknown_path_uses_the_envelope(client: TestClient) -> None:
    for path in ("/api/nope", "/nothing/here", "/api/sources/1/unknown"):
        response = client.get(path)
        assert response.status_code == 404
        assert error_of(response)["code"] == "not_found"


def test_wrong_method_uses_the_envelope(client: TestClient) -> None:
    response = client.post("/api/health")
    assert response.status_code == 405
    assert error_of(response)["code"] == "method_not_allowed"
    assert "GET" in response.headers["allow"]


def test_validation_errors_carry_code_message_and_located_details(client: TestClient) -> None:
    response = client.put("/api/profile", json={"include_keywords": "engineer"})
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "invalid_profile"
    problems = error["details"]["errors"]
    assert problems[0]["loc"] == ["body", "include_keywords"]
    assert set(problems[0]) == {"loc", "message", "type"}
    assert "include_keywords" in error["message"]


@pytest.mark.parametrize(
    ("method", "path", "code"),
    [
        ("PUT", "/api/profile", "invalid_profile"),
        ("POST", "/api/sources", "invalid_source"),
        ("POST", "/api/imports/csv", "invalid_csv"),
        ("POST", "/api/postings", "invalid_posting"),
        ("POST", "/api/merge-decisions", "invalid_decision"),
        ("PUT", "/api/companies/c_000000000000/shortlist", "invalid_shortlist"),
    ],
)
def test_every_body_endpoint_rejects_malformed_json_with_its_own_code(
    client: TestClient, method: str, path: str, code: str
) -> None:
    response = client.request(
        method, path, content="{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert error_of(response)["code"] == code

    empty = client.request(method, path, json={})
    if path == "/api/profile":
        assert empty.status_code == 200  # both lists default to empty: "no keywords"
    else:
        assert empty.status_code == 422
        # a missing board token is reported as the token problem it is
        allowed = {code, "invalid_token"} if path == "/api/sources" else {code}
        assert error_of(empty)["code"] in allowed


@pytest.mark.parametrize("path", ["/api/sources/abc/runs", "/api/merge-decisions/x"])
def test_non_integer_ids_are_a_422_not_a_crash(client: TestClient, path: str) -> None:
    response = client.get(path) if path.endswith("runs") else client.delete(path)
    assert response.status_code == 422
    assert error_of(response)["code"] == "invalid_request"


def test_unexpected_exceptions_become_a_generic_500_envelope(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, client_factory: Callable[..., TestClient]
) -> None:
    def explode(_session: object) -> object:
        raise RuntimeError("secret internal detail /home/user/x.py")

    monkeypatch.setattr("recruit_radar.api.routers.profile.profile_service.get_profile", explode)
    client = client_factory(app, raise_server_exceptions=False)
    response = client.get("/api/profile")
    assert response.status_code == 500
    error = error_of(response)
    assert error["code"] == "internal_error"
    assert "secret" not in response.text
    assert "Traceback" not in response.text


def test_request_bodies_reject_unknown_keys_and_type_coercion(client: TestClient) -> None:
    extra = client.put("/api/profile", json={"include_keywords": [], "surprise": 1})
    assert extra.status_code == 422
    assert error_of(extra)["code"] == "invalid_profile"
    coerced = client.put("/api/profile", json={"include_keywords": [1, 2]})
    assert coerced.status_code == 422


# -- CORS --------------------------------------------------------------------------------------
@pytest.mark.parametrize("origin", [ALLOWED, OTHER_ALLOWED])
def test_preflight_from_a_configured_origin_is_granted(client: TestClient, origin: str) -> None:
    response = client.options(
        "/api/profile",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    methods = response.headers["access-control-allow-methods"]
    assert {"GET", "POST", "PUT", "DELETE"} <= {m.strip() for m in methods.split(",")}
    assert "content-type" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


def test_preflight_from_another_origin_is_refused(client: TestClient) -> None:
    response = client.options(
        "/api/profile",
        headers={"Origin": FOREIGN, "Access-Control-Request-Method": "PUT"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_responses_for_allowed_origins_carry_cors_headers_and_expose_retry_after(
    client: TestClient,
) -> None:
    response = client.get("/api/health", headers={"Origin": ALLOWED})
    assert response.headers["access-control-allow-origin"] == ALLOWED
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "retry-after" in exposed


def test_responses_for_other_origins_have_no_cors_headers(client: TestClient) -> None:
    response = client.get("/api/health", headers={"Origin": FOREIGN})
    assert response.status_code == 200  # same-origin tooling is unaffected...
    assert "access-control-allow-origin" not in response.headers  # ...but a page cannot read it


def test_cors_origins_come_from_the_settings(
    make_app: Callable[..., FastAPI],
    settings: Settings,
    client_factory: Callable[..., TestClient],
) -> None:
    custom = settings.with_overrides(cors_origins=("http://localhost:9999",))
    client = client_factory(make_app(settings=custom))
    granted = client.get("/api/health", headers={"Origin": "http://localhost:9999"})
    assert granted.headers["access-control-allow-origin"] == "http://localhost:9999"
    default = client.get("/api/health", headers={"Origin": ALLOWED})
    assert "access-control-allow-origin" not in default.headers


# -- foreign-origin guard ----------------------------------------------------------------------
def test_a_page_on_another_origin_cannot_change_data_even_with_a_simple_request(
    client: TestClient,
) -> None:
    csv = csv_of(("Acme", "Engineer", "NYC", "remote"))
    blocked = client.post(
        "/api/imports/csv",
        json={"dataset_label": "x", "csv_text": csv},
        headers={"Origin": FOREIGN},
    )
    assert blocked.status_code == 403
    assert error_of(blocked)["code"] == "origin_not_allowed"
    assert analysis(client)["companies"] == []  # nothing was stored

    for method, path in (
        ("DELETE", "/api/data?confirm=erase-all"),
        ("POST", "/api/sources/1/refresh"),
        ("PUT", "/api/profile"),
    ):
        response = client.request(method, path, headers={"Origin": FOREIGN})
        assert response.status_code == 403, (method, path)


def test_allowed_and_absent_origins_can_change_data(client: TestClient) -> None:
    csv = csv_of(("Acme", "Engineer", "NYC", "remote"))
    with_origin = client.post(
        "/api/imports/csv",
        json={"dataset_label": "a", "csv_text": csv},
        headers={"Origin": ALLOWED},
    )
    assert with_origin.status_code == 201
    assert with_origin.headers["access-control-allow-origin"] == ALLOWED
    without_origin = import_csv(client, csv, label="b")
    assert without_origin.status_code == 201


def test_the_guard_ignores_a_trailing_slash_on_the_origin_header(client: TestClient) -> None:
    response = client.put(
        "/api/profile",
        json={"include_keywords": ["a"], "exclude_keywords": []},
        headers={"Origin": ALLOWED + "/"},
    )
    assert response.status_code == 200


def test_bodies_are_not_leaked_back_in_errors_beyond_the_field_message(client: TestClient) -> None:
    secret: dict[str, Any] = {"include_keywords": ["ok"], "exclude_keywords": ["x" * 200]}
    response = client.put("/api/profile", json=secret)
    assert response.status_code == 422
    assert "x" * 200 not in response.text
