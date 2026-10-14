"""Ashby Public Job Posting API: ``GET {base}/posting-api/job-board/{name}`` (spec 04).

The documentation lists no job id, so identity is derived from the posting URL.
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import urlsplit

from ..normalization import CleanPosting, sha12
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
from .mapping import as_text, finish_job, iso_to_date

PROVIDER = "ashby"

_SLUG: Final = re.compile(r"[A-Za-z0-9\-]{8,}")
_WORKPLACE: Final = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


def posting_id_from_url(job_url: str) -> str:
    """Last non-empty path segment if it looks like a UUID/slug, else ``u_`` + sha12(url)."""
    try:
        segments = [part for part in urlsplit(job_url).path.split("/") if part]
    except ValueError:
        segments = []
    if segments and _SLUG.fullmatch(segments[-1]) is not None:
        return segments[-1]
    return "u_" + sha12(job_url)


def map_job(job: object, company_name: str, tally: Tally) -> CleanPosting | None:
    if not isinstance(job, dict):
        tally.dropped["job is not an object"] += 1
        return None
    if job.get("isListed") is False:
        tally.unlisted += 1
        return None

    job_url = as_text(job.get("jobUrl"))
    job_url = job_url.strip() if job_url else None
    apply_url = as_text(job.get("applyUrl"))
    apply_url = apply_url.strip() if apply_url else None
    if job_url:
        posting_id = posting_id_from_url(job_url)
    elif apply_url:
        # An apply URL ends in a generic segment shared by every job; hash the whole URL.
        posting_id = "u_" + sha12(apply_url)
    else:
        tally.dropped["neither jobUrl nor applyUrl"] += 1
        return None

    workplace = as_text(job.get("workplaceType"))
    work_mode = _WORKPLACE.get(workplace.strip().lower()) if workplace else None
    if work_mode is None and job.get("isRemote") is True:
        work_mode = "remote"

    return finish_job(
        {
            "source_posting_id": posting_id,
            "company_name": company_name,
            "title": job.get("title"),
            "location": as_text(job.get("location")),
            "work_mode": work_mode,
            "department": as_text(job.get("department")) or as_text(job.get("team")),
            "url": job_url,
            "posted_at": iso_to_date(job.get("publishedAt"), tally),
        },
        tally,
    )


class AshbyAdapter:
    provider = PROVIDER

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def fetch(self, client: PoliteClient, token: str, company_name: str) -> FetchOutcome:
        url = f"{self._base_url}/posting-api/job-board/{quote_token(token)}"
        response = client.get_json(url)
        payload = response.data
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise AdapterError(
                "malformed",
                "Ashby payload is not an object with a 'jobs' list",
                http_status=response.http_status,
            )
        tally = Tally(items_seen=len(jobs))
        if len(jobs) > MAX_ITEMS:
            raise AdapterError(
                "too_large",
                f"Ashby returned {len(jobs)} jobs (limit {MAX_ITEMS})",
                http_status=response.http_status,
                items_seen=len(jobs),
            )
        postings = [
            posting for job in jobs if (posting := map_job(job, company_name, tally)) is not None
        ]
        require_some_valid(tally, len(postings), response.http_status)
        return FetchOutcome(tuple(postings), tally, client.requests, host_of(self._base_url))
