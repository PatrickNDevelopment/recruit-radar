"""``POST /api/imports/csv`` and ``POST /api/postings``."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from rr_support import FakeClock, analysis, company_named, csv_of, error_of, import_csv


# -- csv ---------------------------------------------------------------------------------------
def test_import_stores_valid_rows_and_reports_invalid_ones_with_line_numbers(
    client: TestClient,
) -> None:
    rows = [
        "company_name,title,location,work_mode,url,posted_at",
        "Acme,Backend Engineer,NYC,remote,https://acme.example/1,2026-10-01",  # line 2
        ",No company,,,,",  # line 3
        "Acme,Designer,Berlin,office,,",  # line 4
        "Acme,Analyst,,,ftp://acme.example/3,",  # line 5
        "Acme,Writer,,,,2026-02-30",  # line 6
        "Beta,Operations Lead,,hybrid,,",  # line 7
    ]
    text = "\r\n".join(rows)
    response = import_csv(client, text, label="  Q4 leads ")
    assert response.status_code == 201
    result = response.json()
    assert result["dataset_label"] == "Q4 leads"
    assert result["accepted"] == 2
    assert result["rejected"] == 4
    assert result["snapshot_id"].startswith("s_")
    assert {(e["line"], e["field"]) for e in result["errors"]} == {
        (3, "company_name"),
        (4, "work_mode"),
        (5, "url"),
        (6, "posted_at"),
    }
    assert all(set(e) == {"line", "field", "message"} for e in result["errors"])
    assert result["warnings"] == []

    data = analysis(client)
    assert {c["name"] for c in data["companies"]} == {"Acme", "Beta"}
    assert {r["title"] for r in data["roles"]} == {"Backend Engineer", "Operations Lead"}
    assert data["stats"]["postings_observed"] == 2
    observation = data["roles"][0]["observations"][0]
    assert observation["source_kind"] == "csv"
    assert observation["source_ref"] == "Q4 leads"


def test_import_with_no_valid_row_is_200_and_stores_nothing(client: TestClient) -> None:
    response = import_csv(client, csv_of(("", "x", "", ""), ("Acme", "", "", "")))
    assert response.status_code == 200
    result = response.json()
    assert (result["accepted"], result["rejected"], result["snapshot_id"]) == (0, 2, None)
    assert len(result["errors"]) == 2
    assert analysis(client)["stats"]["snapshots"] == 0


def test_header_only_file_is_accepted_and_empty(client: TestClient) -> None:
    response = import_csv(client, "company_name,title\n")
    assert response.status_code == 200
    assert response.json()["accepted"] == 0


@pytest.mark.parametrize(
    ("text", "needle", "reason"),
    [
        pytest.param("", "empty", "empty_file", id="empty"),
        pytest.param("title\nEngineer\n", "company_name", "missing_required_column", id="missing"),
        pytest.param(
            "company_name,title,Title\nA,B,C\n", "Duplicate column", "duplicate_header", id="dup"
        ),
        pytest.param(
            'company_name,title\nAcme,"Eng\nineer\n',
            "Unterminated",
            "unterminated_quote",
            id="quote",
        ),
        pytest.param(
            "company_name,title\r\n" + "A,B\r\n" * 5001, "5000", "too_many_rows", id="too-many-rows"
        ),
        pytest.param("company_name,title\nA,B\x00\n", "NUL", "contains_nul", id="nul"),
        pytest.param('"company_name"x,title\nA,B\n', "malformed", "malformed_header", id="header"),
    ],
)
def test_file_level_problems_are_422_invalid_csv(
    client: TestClient, text: str, needle: str, reason: str
) -> None:
    response = import_csv(client, text)
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "invalid_csv"
    assert needle in error["message"]
    assert error["details"]["reason"] == reason  # the same vocabulary the TypeScript importer uses
    assert analysis(client)["stats"]["snapshots"] == 0


def test_unterminated_quote_reports_the_line_it_started_on(client: TestClient) -> None:
    response = import_csv(client, 'company_name,title\nAcme,Engineer\n"oops,row\n')
    assert error_of(response)["details"] == {"line": 3, "reason": "unterminated_quote"}


def test_oversized_csv_is_invalid_csv(client: TestClient) -> None:
    big = "company_name,title\nAcme," + "x" * (1024 * 1024) + "\n"
    response = import_csv(client, big)
    assert response.status_code == 422
    assert error_of(response)["code"] == "invalid_csv"


@pytest.mark.parametrize(
    "label",
    ["", "   ", "x" * 201],
)
def test_dataset_label_is_required_and_bounded(client: TestClient, label: str) -> None:
    response = import_csv(client, csv_of(("Acme", "Engineer", "", "")), label=label)
    assert response.status_code == 422
    assert error_of(response)["code"] == "invalid_csv"
    assert error_of(response)["details"] == {"field": "dataset_label"}


def test_missing_or_extra_body_fields_are_invalid_csv(client: TestClient) -> None:
    for body in (
        {"csv_text": "a,b"},
        {"dataset_label": "x"},
        {"dataset_label": "x", "csv_text": 5},
    ):
        response = client.post("/api/imports/csv", json=body)
        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid_csv"
    extra = client.post(
        "/api/imports/csv",
        json={"dataset_label": "x", "csv_text": "company_name,title\n", "mode": "full"},
    )
    assert extra.status_code == 422


def test_observed_at_in_the_request_is_validated_and_used(
    client: TestClient, clock: FakeClock
) -> None:
    csv = csv_of(("Acme", "Engineer", "NYC", "remote"))
    bad = import_csv(client, csv, observed_at="2026-10-01")
    assert bad.status_code == 422
    assert error_of(bad)["code"] == "invalid_csv"

    ok = import_csv(client, csv, observed_at="2026-09-01T08:00:00Z")
    assert ok.status_code == 201
    early = analysis(client, as_of="2026-09-01T08:00:00Z")
    assert early["companies"][0]["first_seen"] == "2026-09-01T08:00:00Z"
    before = analysis(client, as_of="2026-08-31T23:59:59Z")
    assert before["companies"] == []  # snapshots observed later are ignored


def test_rows_with_their_own_observed_at_become_one_snapshot_per_instant(
    client: TestClient,
) -> None:
    text = (
        "company_name,title,observed_at\r\n"
        "Acme,Engineer,2026-09-01T08:00:00Z\r\n"
        "Acme,Designer,2026-09-01T08:00:00Z\r\n"
        "Acme,Analyst,2026-09-15T08:00:00Z\r\n"
        "Acme,Writer,\r\n"
        "Acme,Bad,not-a-time\r\n"
    )
    result = import_csv(client, text).json()
    assert (result["accepted"], result["rejected"]) == (4, 1)
    assert result["errors"][0]["field"] == "observed_at"
    data = analysis(client)
    assert data["stats"]["snapshots"] == 3
    first_seen = {r["title"]: r["first_seen"] for r in data["roles"]}
    assert first_seen["Engineer"] == first_seen["Designer"] == "2026-09-01T08:00:00Z"
    assert first_seen["Analyst"] == "2026-09-15T08:00:00Z"
    assert first_seen["Writer"] == "2026-10-13T12:00:00Z"  # blank -> import time


def test_a_future_observed_at_warns_and_is_ignored_until_then(client: TestClient) -> None:
    text = "company_name,title,observed_at\r\nAcme,Engineer,2027-01-01T00:00:00Z\r\n"
    result = import_csv(client, text).json()
    assert result["accepted"] == 1
    assert [w["line"] for w in result["warnings"]] == [2]
    assert "after the import time" in result["warnings"][0]["message"]
    assert analysis(client)["companies"] == []
    assert analysis(client, as_of="2027-01-02T00:00:00Z")["companies"][0]["name"] == "Acme"


def test_unknown_columns_and_repeated_rows_are_warnings(client: TestClient) -> None:
    text = "company_name,title,salary\r\nAcme,Engineer,100\r\nAcme,Engineer,120\r\n"
    result = import_csv(client, text).json()
    assert result["accepted"] == 2
    lines = sorted(w["line"] for w in result["warnings"])
    assert lines == [1, 3]
    assert any("salary" in w["message"] for w in result["warnings"])


def test_imports_are_additive_and_never_remove_roles(client: TestClient) -> None:
    import_csv(client, csv_of(("Acme", "Engineer", "NYC", "remote"), ("Acme", "Designer", "", "")))
    import_csv(client, csv_of(("Acme", "Analyst", "", "")))  # same dataset, different rows
    data = analysis(client)
    assert {r["title"]: r["status"] for r in data["roles"]} == {
        "Engineer": "active",
        "Designer": "active",
        "Analyst": "active",
    }
    assert not [e for e in data["events"] if e["type"] == "removed"]


def test_quoted_fields_and_multiline_notes_survive(client: TestClient) -> None:
    text = 'company_name,title,location\r\n"Acme, Inc.","Staff ""Platform"" Engineer","New York,\nNY"\r\n'
    result = import_csv(client, text).json()
    assert result["accepted"] == 1
    data = analysis(client)
    assert data["companies"][0]["name"] == "Acme, Inc."
    assert data["roles"][0]["title"] == 'Staff "Platform" Engineer'
    assert data["roles"][0]["location"] == "New York,\nNY"


def test_same_role_in_two_datasets_is_one_role_with_two_observations(client: TestClient) -> None:
    row = ("Acme", "Backend Engineer", "New York, NY", "remote")
    import_csv(client, csv_of(row), label="list-a")
    import_csv(
        client,
        csv_of(("ACME Inc.", "Backend Engineer (Remote)", "NY - New York", "")),
        label="list-b",
    )
    data = analysis(client)
    assert len(data["companies"]) == 1
    assert len(data["roles"]) == 1
    role = data["roles"][0]
    assert [(o["source_kind"], o["source_ref"]) for o in role["observations"]] == [
        ("csv", "list-a"),
        ("csv", "list-b"),
    ]
    confidence = {c["key"]: c for c in data["companies"][0]["components"]}["source_confidence"]
    assert confidence["inputs"] == {"scope_roles": 1, "corroborated": 1}
    assert confidence["value"] == 700  # csv weight 600 + 100 corroboration


def test_formula_like_cells_are_unguarded_on_import(client: TestClient) -> None:
    text = "company_name,title\r\n'=HYPERLINK(1),'+Lead\r\n"
    import_csv(client, text)
    data = analysis(client)
    assert data["companies"][0]["name"] == "=HYPERLINK(1)"
    assert data["roles"][0]["title"] == "+Lead"


# -- manual postings ---------------------------------------------------------------------------
def post_posting(client: TestClient, **fields: Any) -> Any:
    return client.post("/api/postings", json=fields)


def test_manual_posting_is_stored_as_the_manual_source(client: TestClient) -> None:
    response = post_posting(
        client,
        dataset_label="manual",
        company_name="  Initech  ",
        title="Recruiting Coordinator",
        location="Austin, TX",
        work_mode="onsite",
        department="People",
        url="https://initech.example/jobs/9",
        posted_at="2026-10-02",
        source_posting_id="REQ-9",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["source_kind"] == "manual"
    assert body["source_ref"] == "manual"
    assert body["dataset_label"] == "manual"
    assert body["observed_at"] == "2026-10-13T12:00:00Z"
    assert body["posting"] == {
        "source_posting_id": "REQ-9",
        "company_name": "Initech",
        "title": "Recruiting Coordinator",
        "location": "Austin, TX",
        "work_mode": "onsite",
        "department": "People",
        "url": "https://initech.example/jobs/9",
        "posted_at": "2026-10-02",
    }
    data = analysis(client)
    role = data["roles"][0]
    assert (role["title"], role["work_mode"], role["posted_at"]) == (
        "Recruiting Coordinator",
        "onsite",
        "2026-10-02",
    )
    assert (role["observations"][0]["source_kind"], role["observations"][0]["source_ref"]) == (
        "manual",
        "manual",
    )
    assert role["observations"][0]["source_posting_id"] == "REQ-9"


def test_manual_posting_minimum_and_blank_optionals(client: TestClient) -> None:
    response = post_posting(
        client,
        company_name="Acme",
        title="Engineer",
        location="",
        work_mode="",
        url="",
        posted_at="",
    )
    assert response.status_code == 201
    posting = response.json()["posting"]
    assert posting["location"] is None
    assert posting["work_mode"] == "unknown"
    assert posting["url"] is None
    assert posting["posted_at"] is None
    assert response.json()["dataset_label"] is None


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"company_name": "", "title": "Engineer"}, "company_name"),
        ({"company_name": "Acme", "title": "  "}, "title"),
        ({"company_name": "Acme", "title": "T" * 301}, "title"),
        ({"company_name": "Acme", "title": "Eng", "work_mode": "Remote"}, "work_mode"),
        ({"company_name": "Acme", "title": "Eng", "url": "javascript:alert(1)"}, "url"),
        ({"company_name": "Acme", "title": "Eng", "posted_at": "2026-13-01"}, "posted_at"),
        ({"company_name": "Acme", "title": "Eng", "location": "L" * 301}, "location"),
    ],
)
def test_invalid_manual_postings_are_422_with_field_details(
    client: TestClient, fields: dict[str, Any], field: str
) -> None:
    response = post_posting(client, **fields)
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "invalid_posting"
    assert field in {p["field"] for p in error["details"]["errors"]}
    assert analysis(client)["stats"]["snapshots"] == 0


def test_manual_posting_rejects_unknown_and_engine_owned_fields(client: TestClient) -> None:
    for extra in ({"source_kind": "csv"}, {"source_ref": "x"}, {"salary": "1"}):
        response = post_posting(client, company_name="Acme", title="Engineer", **extra)
        assert response.status_code == 422
        assert error_of(response)["code"] == "invalid_posting"


def test_manual_posting_label_and_observed_at_rules(client: TestClient) -> None:
    assert post_posting(client, company_name="A", title="T", dataset_label="").status_code == 422
    assert post_posting(client, company_name="A", title="T", observed_at="nope").status_code == 422
    ok = post_posting(client, company_name="A", title="T", observed_at="2026-09-01T00:00:00Z")
    assert ok.status_code == 201
    assert ok.json()["observed_at"] == "2026-09-01T00:00:00Z"


def test_manual_postings_merge_with_imported_rows_by_identity(client: TestClient) -> None:
    import_csv(client, csv_of(("Acme", "Engineer", "NYC", "")))
    post_posting(client, company_name="ACME, Inc.", title="Engineer (US)", location="NYC")
    data = analysis(client)
    acme = company_named(data, "ACME, Inc.")  # earliest/ties -> lexicographic smallest raw name
    assert acme["aliases"] == ["ACME, Inc.", "Acme"]
    assert len(data["roles"]) == 1
    assert len(data["roles"][0]["observations"]) == 2
