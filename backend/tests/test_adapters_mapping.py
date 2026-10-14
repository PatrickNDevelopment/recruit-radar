"""Provider payload -> RawPosting mapping, with realistic synthetic payloads (spec 04)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from rr_support import (
    ASHBY_HOST,
    GREENHOUSE_HOST,
    LEVER_HOST,
    FakeAts,
    ashby_job,
    gh_job,
    lever_posting,
)

from recruit_radar.adapters import AdapterError, FetchOutcome, PoliteClient, build_adapter
from recruit_radar.normalization import sha12


def fetch(
    provider: str, ats: FakeAts, token: str = "acme", name: str = "Acme Inc."
) -> FetchOutcome:
    host = {"greenhouse": GREENHOUSE_HOST, "lever": LEVER_HOST, "ashby": ASHBY_HOST}[provider]
    adapter = build_adapter(provider, f"https://{host}")
    with PoliteClient(transport=ats.transport()) as client:
        return adapter.fetch(client, token, name)


def fetch_error(provider: str, ats: FakeAts) -> AdapterError:
    with pytest.raises(AdapterError) as caught:
        fetch(provider, ats)
    return caught.value


# ==============================================================================================
# Greenhouse
# ==============================================================================================
def test_greenhouse_maps_every_field() -> None:
    ats = FakeAts()
    ats.greenhouse(
        "acme",
        [
            gh_job(
                127817,
                "Senior Backend Engineer",
                location="Remote - US",
                department="Platform",
                first_published="2026-09-20T09:15:00-04:00",
                url="https://boards.greenhouse.io/acme/jobs/127817",
                company_name="Provider Says Other Inc.",  # never trusted
            )
        ],
    )
    outcome = fetch("greenhouse", ats)
    (posting,) = outcome.postings
    assert posting.source_posting_id == "127817"
    assert posting.company_name == "Acme Inc."  # the user's name, not the provider's
    assert posting.title == "Senior Backend Engineer"
    assert posting.location == "Remote - US"
    assert posting.department == "Platform"
    assert posting.url == "https://boards.greenhouse.io/acme/jobs/127817"
    assert posting.posted_at == "2026-09-20"
    assert posting.work_mode == "remote"
    assert outcome.tally.items_seen == 1
    assert outcome.requests == 1
    assert outcome.host == GREENHOUSE_HOST


def test_greenhouse_missing_optional_fields_become_null_not_errors() -> None:
    ats = FakeAts()
    # No location key, an explicit null location, a null name inside it, and a bare minimum job.
    jobs = [
        gh_job(1, "No location", location=None, department=None, first_published=None),
        {**gh_job(2, "Null location"), "location": None},
        {**gh_job(4, "Null name"), "location": {"name": None}},
        {"id": 3, "title": "Bare minimum"},
    ]
    ats.greenhouse("acme", jobs)
    postings = fetch("greenhouse", ats).postings
    assert [p.source_posting_id for p in postings] == ["1", "2", "4", "3"]
    for posting in postings:
        assert posting.location is None
        assert posting.work_mode == "unknown"
        assert posting.url is None or posting.url.startswith("https://")
    assert postings[0].department is None
    assert postings[0].posted_at is None
    assert postings[3].url is None


@pytest.mark.parametrize(
    ("location", "work_mode"),
    [
        ("Remote", "remote"),
        ("Remote - US", "remote"),
        ("US (Remote)", "remote"),
        ("remote-friendly", "remote"),
        ("Anywhere, Remote", "remote"),
        ("New York, NY", "unknown"),
        ("Hybrid - London", "unknown"),  # only the word "remote" is read from this provider
        ("Telecommute", "unknown"),
        ("Remotely located", "unknown"),  # token is "remotely", not "remote"
    ],
)
def test_greenhouse_work_mode_comes_from_location_tokens(location: str, work_mode: str) -> None:
    ats = FakeAts()
    ats.greenhouse("acme", [gh_job(1, "Engineer", location=location)])
    assert fetch("greenhouse", ats).postings[0].work_mode == work_mode


def test_greenhouse_posted_at_is_first_published_in_utc_never_updated_at() -> None:
    ats = FakeAts()
    ats.greenhouse(
        "acme",
        [
            gh_job(1, "A", first_published="2026-09-20T22:15:00-04:00"),  # 02:15Z next day
            gh_job(2, "B", first_published="2026-09-20T00:00:00Z"),
            gh_job(3, "C", first_published="2026-09-20"),
            gh_job(4, "D", first_published=None, updated_at="2026-10-01T00:00:00Z"),
            gh_job(5, "E", first_published="not a date"),
            gh_job(6, "F", first_published=""),
        ],
    )
    outcome = fetch("greenhouse", ats)
    assert [p.posted_at for p in outcome.postings] == [
        "2026-09-21",
        "2026-09-20",
        "2026-09-20",
        None,
        None,
        None,
    ]
    assert outcome.tally.omitted == {"posted_at": 1}  # only the unparsable one is reported


def test_greenhouse_accepts_string_ids_and_drops_jobs_missing_required_fields() -> None:
    ats = FakeAts()
    ats.greenhouse(
        "acme",
        [
            gh_job("abc-9", "String id"),
            gh_job(None, "No id"),
            {"id": 7},  # no title
            {"id": 8, "title": "   "},
            {"id": 9, "title": "x" * 301},
            "not an object",
            gh_job(10, "Fine"),
        ],
    )
    outcome = fetch("greenhouse", ats)
    assert [p.source_posting_id for p in outcome.postings] == ["abc-9", "10"]
    assert outcome.tally.items_seen == 7
    assert outcome.tally.dropped_total == 5
    assert outcome.tally.dropped["missing id"] == 1
    assert outcome.tally.dropped["invalid title"] == 3
    assert outcome.tally.dropped["job is not an object"] == 1


def test_greenhouse_invalid_optional_values_are_nulled_and_counted() -> None:
    ats = FakeAts()
    ats.greenhouse(
        "acme",
        [gh_job(1, "Engineer", url="javascript:alert(1)", location="L" * 301)],
    )
    outcome = fetch("greenhouse", ats)
    (posting,) = outcome.postings
    assert posting.url is None
    assert posting.location is None
    assert outcome.tally.omitted == {"url": 1, "location": 1}


def test_greenhouse_empty_board_is_a_valid_empty_result() -> None:
    ats = FakeAts()
    ats.greenhouse("acme", [])
    outcome = fetch("greenhouse", ats)
    assert outcome.postings == ()
    assert outcome.tally.items_seen == 0


@pytest.mark.parametrize(
    "payload",
    [[], "text", 7, None, {"jobs": "nope"}, {"jobs": {"a": 1}}, {"meta": {"total": 1}}, {}],
)
def test_greenhouse_wrong_payload_shape_is_malformed(payload: Any) -> None:
    ats = FakeAts()
    ats.json(GREENHOUSE_HOST, "/v1/boards/acme/jobs", payload)
    assert fetch_error("greenhouse", ats).kind == "malformed"


def test_greenhouse_all_jobs_invalid_is_malformed_with_a_reason() -> None:
    ats = FakeAts()
    ats.greenhouse("acme", [{"id": 1}, {"title": "no id"}, {"id": 3, "title": ""}])
    error = fetch_error("greenhouse", ats)
    assert error.kind == "malformed"
    assert "All 3 jobs were invalid" in error.message
    assert error.items_seen == 3
    assert error.http_status == 200


def test_greenhouse_over_the_item_cap_is_too_large() -> None:
    ats = FakeAts()
    ats.greenhouse("acme", [{"id": i, "title": "T"} for i in range(5001)])
    error = fetch_error("greenhouse", ats)
    assert error.kind == "too_large"
    assert error.items_seen == 5001


def test_greenhouse_exactly_at_the_item_cap_is_accepted() -> None:
    ats = FakeAts()
    ats.greenhouse("acme", [{"id": i, "title": f"T{i}"} for i in range(5000)])
    assert len(fetch("greenhouse", ats).postings) == 5000


# ==============================================================================================
# Lever
# ==============================================================================================
def test_lever_maps_every_field() -> None:
    ats = FakeAts()
    ats.lever(
        "acme",
        [
            lever_posting(
                "7f0c1d52-1111-4a2b-8c9d-aaaaaaaaaaaa",
                "Product Designer",
                location="Berlin",
                department="Design",
                workplace="hybrid",
                created_at=1_758_000_000_000,
                url="https://jobs.lever.co/acme/7f0c1d52-1111-4a2b-8c9d-aaaaaaaaaaaa",
            )
        ],
    )
    outcome = fetch("lever", ats)
    (posting,) = outcome.postings
    assert posting.source_posting_id == "7f0c1d52-1111-4a2b-8c9d-aaaaaaaaaaaa"
    assert posting.title == "Product Designer"
    assert posting.location == "Berlin"
    assert posting.department == "Design"
    assert posting.work_mode == "hybrid"
    assert posting.url == "https://jobs.lever.co/acme/7f0c1d52-1111-4a2b-8c9d-aaaaaaaaaaaa"
    assert posting.posted_at == datetime.fromtimestamp(1_758_000_000, UTC).date().isoformat()
    assert outcome.host == LEVER_HOST


def test_lever_without_created_at_has_no_posting_date() -> None:
    ats = FakeAts()
    ats.lever(
        "acme",
        [
            lever_posting("a1", "No createdAt", created_at=None),
            lever_posting("a2", "String createdAt", created_at="1758000000000"),
            lever_posting("a3", "Boolean createdAt", created_at=True),
            lever_posting("a4", "Float createdAt", created_at=1_758_000_000_000.0),
        ],
    )
    outcome = fetch("lever", ats)
    assert [p.posted_at for p in outcome.postings][:3] == [None, None, None]
    assert (
        outcome.postings[3].posted_at
        == datetime.fromtimestamp(1_758_000_000, UTC).date().isoformat()
    )
    assert outcome.tally.omitted == {"posted_at": 2}  # the string and the boolean


def test_lever_department_falls_back_to_team_and_location_may_be_missing() -> None:
    ats = FakeAts()
    ats.lever(
        "acme",
        [
            lever_posting("a1", "Team only", department=None, team="Payments"),
            lever_posting("a2", "Both", department="Eng", team="Payments"),
            lever_posting("a3", "Neither", department=None, team=None, location=None),
            {
                "id": "a4",
                "text": "No categories at all",
                "hostedUrl": "https://jobs.lever.co/acme/a4",
            },
            {"id": "a5", "text": "Null categories", "categories": None},
        ],
    )
    postings = fetch("lever", ats).postings
    assert [p.department for p in postings] == ["Payments", "Eng", None, None, None]
    assert [p.location for p in postings] == ["Berlin", "Berlin", None, None, None]
    assert postings[4].url is None


@pytest.mark.parametrize(
    ("workplace", "expected"),
    [
        ("remote", "remote"),
        ("Remote", "remote"),
        ("hybrid", "hybrid"),
        ("on-site", "onsite"),
        ("onsite", "onsite"),
        ("ON-SITE", "onsite"),
        ("unspecified", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_lever_workplace_type_mapping(workplace: str | None, expected: str) -> None:
    ats = FakeAts()
    ats.lever("acme", [lever_posting("a1", "Engineer", workplace=workplace)])
    assert fetch("lever", ats).postings[0].work_mode == expected


def test_lever_drops_postings_without_id_or_text() -> None:
    ats = FakeAts()
    ats.lever(
        "acme",
        [
            lever_posting(None, "No id"),
            {"id": "x1"},
            {"id": "x2", "text": ""},
            lever_posting("ok-1", "Fine"),
            42,
        ],
    )
    outcome = fetch("lever", ats)
    assert [p.source_posting_id for p in outcome.postings] == ["ok-1"]
    assert outcome.tally.dropped_total == 4


def test_lever_follows_skip_until_a_short_page() -> None:
    ats = FakeAts()
    ats.lever("acme", [lever_posting(f"id-{i}", f"Role {i}") for i in range(250)])
    outcome = fetch("lever", ats)
    assert len(outcome.postings) == 250
    assert outcome.requests == 3
    queries = [dict(r.url.params) for r in ats.requests]
    assert queries == [
        {"mode": "json", "skip": "0", "limit": "100"},
        {"mode": "json", "skip": "100", "limit": "100"},
        {"mode": "json", "skip": "200", "limit": "100"},
    ]
    assert all(r.method == "GET" for r in ats.requests)


def test_lever_a_full_last_page_needs_one_more_request() -> None:
    ats = FakeAts()
    ats.lever("acme", [lever_posting(f"id-{i}", f"Role {i}") for i in range(100)])
    outcome = fetch("lever", ats)
    assert len(outcome.postings) == 100
    assert outcome.requests == 2  # page 2 is empty and ends the walk


def test_lever_empty_board() -> None:
    ats = FakeAts()
    ats.lever("acme", [])
    outcome = fetch("lever", ats)
    assert outcome.postings == ()
    assert outcome.requests == 1


def test_lever_item_cap_is_5000_in_total() -> None:
    ats = FakeAts()
    ats.lever("acme", [{"id": f"i{i}", "text": f"T{i}"} for i in range(5000)])
    outcome = fetch("lever", ats)
    assert len(outcome.postings) == 5000
    assert outcome.requests == 51

    over = FakeAts()
    over.lever("acme", [{"id": f"i{i}", "text": f"T{i}"} for i in range(5001)])
    error = fetch_error("lever", over)
    assert error.kind == "too_large"
    assert over.count() == 51  # stops at the page that crosses the cap


@pytest.mark.parametrize("payload", [{"jobs": []}, "text", 5, None, {"postings": []}])
def test_lever_non_array_payload_is_malformed(payload: Any) -> None:
    ats = FakeAts()
    ats.json(LEVER_HOST, "/v0/postings/acme", payload)
    assert fetch_error("lever", ats).kind == "malformed"


def test_lever_error_on_a_later_page_fails_the_whole_fetch() -> None:
    ats = FakeAts()
    page = [lever_posting(f"id-{i}", f"Role {i}") for i in range(100)]

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params["skip"] == "0":
            return httpx.Response(200, json=page)
        return httpx.Response(503)

    ats.route(LEVER_HOST, "/v0/postings/acme", respond)
    error = fetch_error("lever", ats)
    assert error.kind == "server_error"
    assert ats.count() == 2


# ==============================================================================================
# Ashby
# ==============================================================================================
def test_ashby_maps_every_field() -> None:
    ats = FakeAts()
    uuid = "3f2a0c1e-5b7d-4e8a-9c11-0a1b2c3d4e5f"
    ats.ashby(
        "acme",
        [
            ashby_job(
                "Staff Data Engineer",
                job_url=f"https://jobs.ashbyhq.com/acme/{uuid}",
                location="London",
                department="Data",
                workplace="Hybrid",
                published_at="2026-09-25T10:30:00.000+00:00",
            )
        ],
    )
    outcome = fetch("ashby", ats)
    (posting,) = outcome.postings
    assert posting.source_posting_id == uuid
    assert posting.title == "Staff Data Engineer"
    assert posting.location == "London"
    assert posting.department == "Data"
    assert posting.url == f"https://jobs.ashbyhq.com/acme/{uuid}"
    assert posting.work_mode == "hybrid"
    assert posting.posted_at == "2026-09-25"
    assert outcome.host == ASHBY_HOST


def test_ashby_has_no_job_id_so_identity_comes_from_the_url() -> None:
    ats = FakeAts()
    slug_url = "https://jobs.ashbyhq.com/acme/senior-platform-engineer"
    short_url = "https://jobs.ashbyhq.com/acme/eng"  # 3 characters: not slug-like
    trailing_slash = "https://jobs.ashbyhq.com/acme/3f2a0c1e-5b7d-4e8a-9c11-0a1b2c3d4e5f/"
    no_path = "https://jobs.ashbyhq.com"
    ats.ashby(
        "acme",
        [
            ashby_job("Slug", job_url=slug_url),
            ashby_job("Short", job_url=short_url),
            ashby_job("Trailing", job_url=trailing_slash),
            ashby_job("No path", job_url=no_path),
            ashby_job(
                "Apply only", job_url=None, apply_url="https://jobs.ashbyhq.com/acme/9/apply"
            ),
        ],
    )
    outcome = fetch("ashby", ats)
    ids = [p.source_posting_id for p in outcome.postings]
    assert ids == [
        "senior-platform-engineer",
        "u_" + sha12(short_url),
        "3f2a0c1e-5b7d-4e8a-9c11-0a1b2c3d4e5f",
        "u_" + sha12(no_path),
        "u_" + sha12("https://jobs.ashbyhq.com/acme/9/apply"),
    ]
    assert outcome.postings[4].url is None  # url is jobUrl only
    assert len(set(ids)) == 5  # distinct jobs get distinct ids


def test_ashby_job_with_neither_url_is_dropped_and_counted() -> None:
    ats = FakeAts()
    ats.ashby("acme", [ashby_job("Orphan", job_url=None, apply_url=None), ashby_job("Fine")])
    outcome = fetch("ashby", ats)
    assert [p.title for p in outcome.postings] == ["Fine"]
    assert outcome.tally.dropped == {"neither jobUrl nor applyUrl": 1}


def test_ashby_unlisted_jobs_are_skipped_not_dropped() -> None:
    ats = FakeAts()
    ats.ashby(
        "acme",
        [
            ashby_job("Public", job_url="https://jobs.ashbyhq.com/acme/aaaaaaaa-1"),
            ashby_job(
                "Hidden", is_listed=False, job_url="https://jobs.ashbyhq.com/acme/bbbbbbbb-2"
            ),
            ashby_job(
                "Unknown listing",
                is_listed=None,
                job_url="https://jobs.ashbyhq.com/acme/cccccccc-3",
            ),
        ],
    )
    outcome = fetch("ashby", ats)
    assert [p.title for p in outcome.postings] == ["Public", "Unknown listing"]
    assert outcome.tally.unlisted == 1
    assert outcome.tally.dropped_total == 0
    assert outcome.tally.items_seen == 3


def test_ashby_all_jobs_unlisted_is_an_empty_success_not_malformed() -> None:
    ats = FakeAts()
    ats.ashby("acme", [ashby_job("Hidden", is_listed=False)])
    outcome = fetch("ashby", ats)
    assert outcome.postings == ()
    assert outcome.tally.unlisted == 1


@pytest.mark.parametrize(
    ("workplace", "is_remote", "expected"),
    [
        ("Remote", None, "remote"),
        ("Hybrid", None, "hybrid"),
        ("OnSite", None, "onsite"),
        ("Onsite", None, "onsite"),
        (None, True, "remote"),
        (None, False, "unknown"),
        (None, None, "unknown"),
        ("Hybrid", True, "hybrid"),  # workplaceType wins over isRemote
        ("Something else", True, "remote"),
        ("Something else", None, "unknown"),
    ],
)
def test_ashby_work_mode(workplace: str | None, is_remote: bool | None, expected: str) -> None:
    ats = FakeAts()
    ats.ashby("acme", [ashby_job("Engineer", workplace=workplace, is_remote=is_remote)])
    assert fetch("ashby", ats).postings[0].work_mode == expected


def test_ashby_department_falls_back_to_team_and_nulls_are_tolerated() -> None:
    ats = FakeAts()
    ats.ashby(
        "acme",
        [
            ashby_job(
                "Team only", department=None, team="Growth", job_url="https://x.example/aaaaaaaa-1"
            ),
            ashby_job(
                "Nothing",
                department=None,
                location=None,
                published_at=None,
                workplace=None,
                job_url="https://x.example/bbbbbbbb-2",
            ),
        ],
    )
    postings = fetch("ashby", ats).postings
    assert postings[0].department == "Growth"
    assert (postings[1].department, postings[1].location, postings[1].posted_at) == (
        None,
        None,
        None,
    )


@pytest.mark.parametrize("payload", [[], "x", None, {"jobs": "no"}, {"apiVersion": "1"}])
def test_ashby_wrong_payload_shape_is_malformed(payload: Any) -> None:
    ats = FakeAts()
    ats.json(ASHBY_HOST, "/posting-api/job-board/acme", payload)
    assert fetch_error("ashby", ats).kind == "malformed"


def test_ashby_over_the_item_cap_is_too_large() -> None:
    ats = FakeAts()
    jobs = [
        {"title": f"T{i}", "jobUrl": f"https://jobs.ashbyhq.com/acme/j{i:08d}"} for i in range(5001)
    ]
    ats.ashby("acme", jobs)
    assert fetch_error("ashby", ats).kind == "too_large"


# ==============================================================================================
# Cross-provider
# ==============================================================================================
@pytest.mark.parametrize("provider", ["greenhouse", "lever", "ashby"])
def test_description_html_is_never_part_of_the_result(provider: str) -> None:
    ats = FakeAts()
    if provider == "greenhouse":
        ats.greenhouse("acme", [gh_job(1, "Engineer")])
    elif provider == "lever":
        ats.lever("acme", [lever_posting("a1", "Engineer")])
    else:
        ats.ashby("acme", [ashby_job("Engineer")])
    postings = fetch(provider, ats).postings
    assert postings
    stored = repr(postings)
    assert "Never stored" not in stored
    assert "<p>" not in stored
    assert set(postings[0].__slots__) == {  # type: ignore[attr-defined]
        "source_posting_id",
        "company_name",
        "title",
        "location",
        "work_mode",
        "department",
        "url",
        "posted_at",
    }
