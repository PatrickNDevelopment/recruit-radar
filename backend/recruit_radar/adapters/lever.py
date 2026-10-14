"""Lever Postings API: ``GET {base}/v0/postings/{site}?mode=json&skip=n&limit=100`` (spec 04)."""

from __future__ import annotations

from ..normalization import CleanPosting
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
from .mapping import as_identifier, as_text, dict_of, epoch_ms_to_date, finish_job

PROVIDER = "lever"
PAGE_SIZE = 100

_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}


def map_job(job: object, company_name: str, tally: Tally) -> CleanPosting | None:
    if not isinstance(job, dict):
        tally.dropped["job is not an object"] += 1
        return None
    posting_id = as_identifier(job.get("id"))
    if posting_id is None:
        tally.dropped["missing id"] += 1
        return None

    categories = dict_of(job.get("categories"))
    workplace = as_text(job.get("workplaceType"))
    return finish_job(
        {
            "source_posting_id": posting_id,
            "company_name": company_name,
            "title": job.get("text"),
            "location": as_text(categories.get("location")),
            "work_mode": _WORKPLACE.get(workplace.strip().lower(), "unknown")
            if workplace
            else None,
            "department": as_text(categories.get("department")) or as_text(categories.get("team")),
            "url": as_text(job.get("hostedUrl")),
            # createdAt is not in the documentation page; it is optional by design.
            "posted_at": epoch_ms_to_date(job.get("createdAt"), tally),
        },
        tally,
    )


class LeverAdapter:
    provider = PROVIDER

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def fetch(self, client: PoliteClient, token: str, company_name: str) -> FetchOutcome:
        url = f"{self._base_url}/v0/postings/{quote_token(token)}"
        tally = Tally()
        postings: list[CleanPosting] = []
        skip = 0
        last_status = 200
        while True:
            response = client.get_json(
                url, {"mode": "json", "skip": str(skip), "limit": str(PAGE_SIZE)}
            )
            last_status = response.http_status
            page = response.data
            if not isinstance(page, list):
                raise AdapterError(
                    "malformed",
                    "Lever payload is not a JSON array of postings",
                    http_status=last_status,
                    items_seen=tally.items_seen,
                )
            tally.items_seen += len(page)
            if tally.items_seen > MAX_ITEMS:
                raise AdapterError(
                    "too_large",
                    f"Lever returned more than {MAX_ITEMS} postings",
                    http_status=last_status,
                    items_seen=tally.items_seen,
                )
            for job in page:
                posting = map_job(job, company_name, tally)
                if posting is not None:
                    postings.append(posting)
            if len(page) < PAGE_SIZE:
                break
            skip += PAGE_SIZE
        require_some_valid(tally, len(postings), last_status)
        return FetchOutcome(tuple(postings), tally, client.requests, host_of(self._base_url))
