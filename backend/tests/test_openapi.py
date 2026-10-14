"""The committed ``contracts/openapi.json`` must equal the live schema (spec 03)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from recruit_radar.export_openapi import DEFAULT_OUTPUT, build_schema, main, render

EXPECTED_OPERATIONS = {
    ("get", "/api/health"),
    ("get", "/api/profile"),
    ("put", "/api/profile"),
    ("get", "/api/sources"),
    ("post", "/api/sources"),
    ("delete", "/api/sources/{source_id}"),
    ("post", "/api/sources/{source_id}/refresh"),
    ("get", "/api/sources/{source_id}/runs"),
    ("post", "/api/imports/csv"),
    ("post", "/api/postings"),
    ("get", "/api/analysis"),
    ("get", "/api/companies/{company_id}"),
    ("get", "/api/merge-decisions"),
    ("post", "/api/merge-decisions"),
    ("delete", "/api/merge-decisions/{decision_id}"),
    ("get", "/api/shortlist"),
    ("put", "/api/companies/{company_id}/shortlist"),
    ("get", "/api/shortlist/export.csv"),
    ("delete", "/api/data"),
}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return build_schema()


def test_committed_openapi_matches_the_live_schema(schema: dict[str, Any]) -> None:
    assert DEFAULT_OUTPUT.name == "openapi.json"
    assert DEFAULT_OUTPUT.exists(), "run: python -m recruit_radar.export_openapi"
    committed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    assert committed == schema, (
        "contracts/openapi.json is out of date; run python -m recruit_radar.export_openapi"
    )


def test_committed_file_is_byte_identical_to_the_exporter_output(schema: dict[str, Any]) -> None:
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == render(schema)


def test_check_mode_and_export_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "nested" / "openapi.json"
    assert main(["--output", str(target), "--check"]) == 1  # missing file is drift
    assert main(["--output", str(target)]) == 0
    assert main(["--output", str(target), "--check"]) == 0
    target.write_text("{}\n", encoding="utf-8")
    assert main(["--output", str(target), "--check"]) == 1
    capsys.readouterr()


def test_exporter_does_not_touch_the_default_database() -> None:
    from recruit_radar.config import DEFAULT_DB_PATH

    existed = DEFAULT_DB_PATH.exists()
    build_schema()
    assert DEFAULT_DB_PATH.exists() == existed


def test_every_spec_endpoint_is_documented_and_nothing_else(schema: dict[str, Any]) -> None:
    operations = {
        (method, path)
        for path, item in schema["paths"].items()
        for method in item
        if method in {"get", "put", "post", "delete", "patch"}
    }
    assert operations == EXPECTED_OPERATIONS


def test_success_statuses_follow_spec_03(schema: dict[str, Any]) -> None:
    def statuses(method: str, path: str) -> set[str]:
        return {code for code in schema["paths"][path][method]["responses"] if code != "default"}

    assert statuses("post", "/api/sources") == {"201"}
    assert statuses("delete", "/api/sources/{source_id}") == {"204"}
    assert statuses("post", "/api/sources/{source_id}/refresh") == {"200"}
    assert statuses("post", "/api/imports/csv") == {"200", "201"}  # 200: no row was valid
    assert statuses("post", "/api/postings") == {"201"}
    assert statuses("post", "/api/merge-decisions") == {"201"}
    assert statuses("delete", "/api/merge-decisions/{decision_id}") == {"204"}
    assert statuses("delete", "/api/data") == {"204"}
    assert statuses("get", "/api/shortlist/export.csv") == {"200"}
    assert (
        "text/csv"
        in schema["paths"]["/api/shortlist/export.csv"]["get"]["responses"]["200"]["content"]
    )


def test_every_request_body_forbids_extra_properties(schema: dict[str, Any]) -> None:
    bodies = [
        item["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
        for path in schema["paths"].values()
        for item in path.values()
        if "requestBody" in item
    ]
    assert len(bodies) == 6
    for name in bodies:
        assert schema["components"]["schemas"][name]["additionalProperties"] is False, name


def test_errors_are_documented_as_the_envelope_never_as_fastapi_defaults(
    schema: dict[str, Any],
) -> None:
    names = set(schema["components"]["schemas"])
    assert "ErrorEnvelope" in names
    assert "HTTPValidationError" not in names
    assert "ValidationError" not in names
    for path in schema["paths"].values():
        for item in path.values():
            default = item["responses"]["default"]["content"]["application/json"]["schema"]
            assert default == {"$ref": "#/components/schemas/ErrorEnvelope"}
            assert "422" not in item["responses"]


def test_the_token_pattern_is_part_of_the_contract(schema: dict[str, Any]) -> None:
    token = schema["components"]["schemas"]["SourceBody"]["properties"]["token"]
    assert token["pattern"] == "^[A-Za-z0-9_.-]{1,100}$"


def test_refresh_run_schema_has_exactly_the_spec_fields(schema: dict[str, Any]) -> None:
    run = schema["components"]["schemas"]["RefreshRunOut"]
    assert set(run["properties"]) == {
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


def test_rendering_is_deterministic(schema: dict[str, Any]) -> None:
    assert render(schema) == render(build_schema())
    assert json.loads(render(schema)) == schema
