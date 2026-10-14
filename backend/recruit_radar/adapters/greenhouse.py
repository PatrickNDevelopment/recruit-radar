"""Greenhouse Job Board API: ``GET {base}/v1/boards/{token}/jobs?content=true`` (spec 04)."""

from __future__ import annotations

from ..normalization import CleanPosting, norm_text
from .base import (
    MAX_ITEMS,
    AdapterError,
    FetchOutcome,
    PoliteClient,
    Tally,
    host_of,
    quote_token,
    require_some_valid,
)
from .mapping import as_identifier, as_text, dict_of, finish_job, iso_to_date

PROVIDER = "greenhouse"


def map_job(job: object, company_name: str, tally: Tally) -> CleanPosting | None:
    if not isinstance(job, dict):
        tally.dropped["job is not an object"] += 1
        return None
    posting_id = as_identifier(job.get("id"))
    if posting_id is None:
        tally.dropped["missing id"] += 1
        return None

    location = as_text(dict_of(job.get("location")).get("name"))
    department: str | None = None
    departments = job.get("departments")
    if isinstance(departments, list) and departments:
        department = as_text(dict_of(departments[0]).get("name"))
    # `updated_at` is deliberately NOT a posting date (spec 04).
    posted_at = iso_to_date(job.get("first_published"), tally)
    work_mode = "remote" if location and "remote" in norm_text(location).split(" ") else "unknown"

    return finish_job(
        {
            "source_posting_id": posting_id,
            "company_name": company_name,
            "title": job.get("title"),
            "location": location,
            "work_mode": work_mode,
            "department": department,
            "url": as_text(job.get("absolute_url")),
            "posted_at": posted_at,
        },
        tally,
    )


class GreenhouseAdapter:
    provider = PROVIDER

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def fetch(self, client: PoliteClient, token: str, company_name: str) -> FetchOutcome:
        url = f"{self._base_url}/v1/boards/{quote_token(token)}/jobs"
        response = client.get_json(url, {"content": "true"})
        payload = response.data
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise AdapterError(
                "malformed",
                "Greenhouse payload is not an object with a 'jobs' list",
                http_status=response.http_status,
            )
        tally = Tally(items_seen=len(jobs))
        if len(jobs) > MAX_ITEMS:
            raise AdapterError(
                "too_large",
                f"Greenhouse returned {len(jobs)} jobs (limit {MAX_ITEMS})",
                http_status=response.http_status,
                items_seen=len(jobs),
            )
        postings = [
            posting for job in jobs if (posting := map_job(job, company_name, tally)) is not None
        ]
        require_some_valid(tally, len(postings), response.http_status)
        return FetchOutcome(tuple(postings), tally, client.requests, host_of(self._base_url))
