"""Shortlist, qualification notes, the shortlist CSV and ``DELETE /api/data``."""

from __future__ import annotations

import csv
import io
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

from recruit_radar.services.shortlist import EXPORT_HEADER


def seed(client: TestClient) -> dict[str, dict[str, Any]]:
    """Three companies, keyword profile; returns ``{name: company}``."""
    client.put("/api/profile", json={"include_keywords": ["engineer"], "exclude_keywords": []})
    import_csv(
        client,
        csv_of(
            ("Acme", "Backend Engineer", "NYC", "remote"),
            ("Acme", "Platform Engineer", "NYC", "remote"),
            ("Beta Corp", "Staff Engineer", "SF", "hybrid"),
            ("Beta Corp", "Office Manager", "SF", "onsite"),
            ("Gamma", "Receptionist", "LA", "onsite"),
        ),
    )
    return {c["name"]: c for c in analysis(client)["companies"]}


def put_shortlist(client: TestClient, company_id: str, body: dict[str, Any]) -> Any:
    return client.put(f"/api/companies/{company_id}/shortlist", json=body)


def parse_export(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


# -- shortlist ---------------------------------------------------------------------------------
def test_shortlist_starts_empty(client: TestClient) -> None:
    response = client.get("/api/shortlist")
    assert response.status_code == 200
    assert response.json() == []


def test_shortlisting_a_company_with_a_note(client: TestClient, clock: FakeClock) -> None:
    companies = seed(client)
    acme = companies["Acme"]
    clock.advance(seconds=30)
    response = put_shortlist(
        client, acme["company_id"], {"shortlisted": True, "note": "  Strong backend hiring  "}
    )
    assert response.status_code == 200
    assert response.json() == {
        "company_id": acme["company_id"],
        "shortlisted": True,
        "name": "Acme",
        "note": "Strong backend hiring",
        "added_at": "2026-10-13T12:00:30Z",
    }
    assert client.get("/api/shortlist").json() == [
        {
            "company_id": acme["company_id"],
            "name": "Acme",
            "note": "Strong backend hiring",
            "added_at": "2026-10-13T12:00:30Z",
        }
    ]
    detail = client.get(f"/api/companies/{acme['company_id']}").json()
    assert detail["shortlist"]["shortlisted"] is True
    assert detail["shortlist"]["note"] == "Strong backend hiring"


def test_added_at_keeps_the_original_time_when_the_note_changes(
    client: TestClient, clock: FakeClock
) -> None:
    acme = seed(client)["Acme"]["company_id"]
    put_shortlist(client, acme, {"shortlisted": True, "note": "first"})
    clock.advance(seconds=600)
    again = put_shortlist(client, acme, {"shortlisted": True, "note": "second"}).json()
    assert again["added_at"] == "2026-10-13T12:00:00Z"
    assert again["note"] == "second"


def test_note_semantics_omit_keeps_empty_clears(client: TestClient) -> None:
    acme = seed(client)["Acme"]["company_id"]
    put_shortlist(client, acme, {"shortlisted": True, "note": "keep me"})
    assert put_shortlist(client, acme, {"shortlisted": True}).json()["note"] == "keep me"
    assert put_shortlist(client, acme, {"shortlisted": True, "note": ""}).json()["note"] == ""
    assert put_shortlist(client, acme, {"shortlisted": True, "note": None}).json()["note"] == ""


def test_removing_from_the_shortlist_keeps_the_note_for_the_company_page(
    client: TestClient,
) -> None:
    acme = seed(client)["Acme"]["company_id"]
    put_shortlist(client, acme, {"shortlisted": True, "note": "talked to HR"})
    result = put_shortlist(client, acme, {"shortlisted": False}).json()
    assert result["shortlisted"] is False
    assert result["note"] == "talked to HR"
    assert client.get("/api/shortlist").json() == []
    detail = client.get(f"/api/companies/{acme}").json()
    assert detail["shortlist"]["note"] == "talked to HR"
    assert detail["shortlist"]["shortlisted"] is False
    # clearing the note as well leaves nothing behind
    put_shortlist(client, acme, {"shortlisted": False, "note": ""})
    assert client.get(f"/api/companies/{acme}").json()["shortlist"]["note"] == ""


def test_a_note_can_be_written_for_a_company_that_is_not_shortlisted(client: TestClient) -> None:
    gamma = seed(client)["Gamma"]["company_id"]
    result = put_shortlist(client, gamma, {"shortlisted": False, "note": "not a fit"}).json()
    assert (result["shortlisted"], result["note"], result["added_at"]) == (False, "not a fit", None)
    assert client.get("/api/shortlist").json() == []


def test_unshortlisting_an_untouched_company_is_a_no_op(client: TestClient) -> None:
    gamma = seed(client)["Gamma"]["company_id"]
    result = put_shortlist(client, gamma, {"shortlisted": False})
    assert result.status_code == 200
    assert result.json()["shortlisted"] is False
    assert result.json()["note"] == ""


def test_shortlist_order_is_by_when_it_was_added(client: TestClient, clock: FakeClock) -> None:
    companies = seed(client)
    for name in ("Gamma", "Acme", "Beta Corp"):
        clock.advance(seconds=10)
        put_shortlist(client, companies[name]["company_id"], {"shortlisted": True})
    assert [e["name"] for e in client.get("/api/shortlist").json()] == [
        "Gamma",
        "Acme",
        "Beta Corp",
    ]


def test_unknown_company_is_404_unknown_company(client: TestClient) -> None:
    seed(client)
    for company_id in ("c_000000000000", "nope", "a%2Fb"):
        response = put_shortlist(client, company_id, {"shortlisted": True})
        assert response.status_code == 404, company_id
        assert error_of(response)["code"] in {"unknown_company", "not_found"}
    named = put_shortlist(client, "c_000000000000", {"shortlisted": True})
    assert error_of(named)["code"] == "unknown_company"
    assert error_of(named)["details"] == {"company_id": "c_000000000000"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"note": "no flag"},
        {"shortlisted": "yes"},
        {"shortlisted": 1},
        {"shortlisted": True, "note": 5},
        {"shortlisted": True, "note": "n" * 2001},
        {"shortlisted": True, "extra": 1},
    ],
)
def test_invalid_shortlist_bodies_are_422(client: TestClient, body: dict[str, Any]) -> None:
    acme = seed(client)["Acme"]["company_id"]
    response = put_shortlist(client, acme, body)
    assert response.status_code == 422
    assert error_of(response)["code"] == "invalid_shortlist"
    assert client.get("/api/shortlist").json() == []


def test_a_2000_character_note_is_accepted(client: TestClient) -> None:
    acme = seed(client)["Acme"]["company_id"]
    response = put_shortlist(client, acme, {"shortlisted": True, "note": "n" * 2000})
    assert response.status_code == 200
    assert len(response.json()["note"]) == 2000


def test_the_shortlist_follows_a_company_through_a_merge(client: TestClient) -> None:
    import_csv(
        client, csv_of(("DoorDash", "Engineer", "SF", ""), ("Door Dash", "Analyst", "SF", ""))
    )
    before = analysis(client)
    doordash = company_named(before, "DoorDash")
    put_shortlist(client, doordash["company_id"], {"shortlisted": True, "note": "my note"})

    merged = client.post(
        "/api/merge-decisions",
        json={"a_key": "door dash", "b_key": "doordash", "decision": "merge"},
    )
    assert merged.status_code == 201
    after = analysis(client)
    assert len(after["companies"]) == 1
    new_id = after["companies"][0]["company_id"]
    assert new_id != doordash["company_id"]  # canonical key changed, so did the id

    entries = client.get("/api/shortlist").json()
    assert [(e["company_id"], e["note"]) for e in entries] == [(new_id, "my note")]
    detail = client.get(f"/api/companies/{new_id}").json()
    assert detail["shortlist"]["shortlisted"] is True
    assert detail["shortlist"]["note"] == "my note"

    # undoing the merge puts the entry back on a company that exists
    client.delete(f"/api/merge-decisions/{merged.json()['id']}")
    names = {e["name"] for e in client.get("/api/shortlist").json()}
    assert len(names) == 1


# -- export ------------------------------------------------------------------------------------
def test_export_has_the_spec_columns_and_one_row_per_shortlisted_company(
    client: TestClient,
) -> None:
    companies = seed(client)
    put_shortlist(
        client, companies["Beta Corp"]["company_id"], {"shortlisted": True, "note": "call, soon"}
    )
    put_shortlist(client, companies["Acme"]["company_id"], {"shortlisted": True})

    response = client.get("/api/shortlist/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.splitlines()[0] == ",".join(EXPORT_HEADER)
    assert response.text.endswith("\r\n")

    rows = parse_export(response.text)
    assert [r["company"] for r in rows] == ["Acme", "Beta Corp"]  # by rank
    acme, beta = rows
    assert tuple(acme) == EXPORT_HEADER
    assert acme["rank"] == str(companies["Acme"]["rank"])
    assert acme["score"] == f"{companies['Acme']['score'] // 10}.{companies['Acme']['score'] % 10}"
    assert acme["coverage_percent"] == str(companies["Acme"]["coverage"])
    assert acme["active_roles"] == "2"
    assert acme["relevant_roles"] == "2"
    assert acme["last_seen"] == "2026-10-13T12:00:00Z"
    assert acme["as_of"] == "2026-10-13T12:00:00Z"
    assert acme["strongest_evidence"]
    assert "Change (30 days)" in acme["missing_information"]
    assert beta["note"] == "call, soon"
    assert beta["relevant_roles"] == "1"
    assert beta["active_roles"] == "2"


def test_export_never_states_a_missing_component_as_zero(client: TestClient) -> None:
    companies = seed(client)
    put_shortlist(client, companies["Gamma"]["company_id"], {"shortlisted": True})
    (row,) = parse_export(client.get("/api/shortlist/export.csv").text)
    assert row["relevant_roles"] == "0"
    # Gamma has no relevant roles: scope is empty, so these are *missing*, with the reason
    assert "no active role matches the configured keywords" in row["missing_information"]
    assert "fewer than two full snapshots" in row["missing_information"]


def test_export_of_a_company_no_longer_in_the_data_says_so_and_has_no_score(
    client: TestClient, ats: FakeAts
) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    sid = add_source(client)["id"]
    refresh(client, sid)
    company_id = analysis(client)["companies"][0]["company_id"]
    put_shortlist(client, company_id, {"shortlisted": True})
    client.delete(f"/api/sources/{sid}")  # the company disappears from the loaded data
    (row,) = parse_export(client.get("/api/shortlist/export.csv").text)
    assert row["company"] == "Acme Inc."
    assert row["rank"] == ""
    assert row["score"] == ""
    assert "not present in the loaded data" in row["missing_information"]


def test_export_guards_formula_cells(client: TestClient) -> None:
    import_csv(client, "company_name,title\r\n'=Evil Corp,Engineer\r\n")
    company = analysis(client)["companies"][0]
    assert company["name"] == "=Evil Corp"
    put_shortlist(client, company["company_id"], {"shortlisted": True, "note": "@mention, -dash"})
    text = client.get("/api/shortlist/export.csv").text
    (row,) = parse_export(text)
    assert row["company"] == "'=Evil Corp"
    assert row["note"] == "'@mention, -dash"
    # the guard is exactly one apostrophe and importing removes exactly that one
    back = import_csv(
        client, "company_name,title\r\n" + f'"{row["company"]}",Engineer\r\n', label="round-trip"
    )
    assert back.status_code == 201
    assert company_named(analysis(client), "=Evil Corp")


def test_export_with_nothing_shortlisted_is_just_the_header(client: TestClient) -> None:
    seed(client)
    response = client.get("/api/shortlist/export.csv")
    assert response.text == ",".join(EXPORT_HEADER) + "\r\n"


def test_export_as_of_is_validated(client: TestClient) -> None:
    response = client.get("/api/shortlist/export.csv", params={"as_of": "later"})
    assert response.status_code == 422
    assert error_of(response)["code"] == "invalid_as_of"


# -- erase -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "query", ["", "?confirm=yes", "?confirm=", "?confirm=ERASE-ALL", "?x=erase-all"]
)
def test_erase_requires_the_exact_confirmation(client: TestClient, query: str) -> None:
    seed(client)
    response = client.delete("/api/data" + query)
    assert response.status_code == 400
    error = error_of(response)
    assert error["code"] == "confirmation_required"
    assert "erase-all" in error["message"]
    assert len(analysis(client)["companies"]) == 3  # nothing was erased


def test_erase_removes_everything_the_user_stored(client: TestClient, ats: FakeAts) -> None:
    ats.greenhouse("acme", [gh_job(1, "Engineer")])
    companies = seed(client)
    sid = add_source(client)["id"]
    refresh(client, sid)
    client.post("/api/postings", json={"company_name": "Solo", "title": "Engineer"})
    client.post(
        "/api/merge-decisions",
        json={"a_key": "acme", "b_key": "beta", "decision": "not_same"},
    )
    put_shortlist(client, companies["Acme"]["company_id"], {"shortlisted": True, "note": "x"})

    response = client.delete("/api/data", params={"confirm": "erase-all"})
    assert response.status_code == 204
    assert response.content == b""

    assert analysis(client)["companies"] == []
    assert analysis(client)["stats"]["snapshots"] == 0
    assert client.get("/api/sources").json() == []
    assert client.get(f"/api/sources/{sid}/runs").status_code == 404
    assert client.get("/api/merge-decisions").json() == []
    assert client.get("/api/shortlist").json() == []
    assert client.get("/api/profile").json() == {"include_keywords": [], "exclude_keywords": []}
    health = client.get("/api/health").json()
    assert (health["db_ok"], health["schema_version"]) == (True, 1)  # the schema survives


def test_the_app_is_fully_usable_after_an_erase(client: TestClient) -> None:
    seed(client)
    client.delete("/api/data", params={"confirm": "erase-all"})
    assert import_csv(client, csv_of(("Fresh", "Engineer", "", ""))).status_code == 201
    assert [c["name"] for c in analysis(client)["companies"]] == ["Fresh"]
    assert add_source(client)["id"] >= 1
