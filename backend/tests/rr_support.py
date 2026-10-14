"""Shared fakes and builders for the backend tests (no network, no real clock)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

GREENHOUSE_HOST = "boards-api.greenhouse.io"
LEVER_HOST = "api.lever.co"
ASHBY_HOST = "api.ashbyhq.com"

Responder = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """A controllable ``Clock``: whole-second UTC instants that only move when told to."""

    def __init__(self, start: str = "2026-10-13T12:00:00Z") -> None:
        self.now = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, *, seconds: int = 0, days: int = 0) -> None:
        self.now += timedelta(seconds=seconds, days=days)

    def stamp(self) -> str:
        return self.now.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeAts:
    """A programmable stand-in for the three provider hosts behind ``httpx.MockTransport``.

    Every request is recorded. A non-GET request raises, so any test that goes through this
    fake also proves the adapters stay read-only.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._routes: dict[tuple[str, str], Responder] = {}

    # -- plumbing ---------------------------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method != "GET":  # pragma: no cover - would be a product bug
            raise AssertionError(
                f"adapter issued a non-GET request: {request.method} {request.url}"
            )
        responder = self._routes.get((request.url.host, request.url.path))
        if responder is None:
            return httpx.Response(404, json={"error": "no such board"})
        return responder(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def route(self, host: str, path: str, responder: Responder) -> None:
        self._routes[(host, path)] = responder

    def clear(self) -> None:
        self.requests.clear()

    def count(self, host: str | None = None) -> int:
        return sum(1 for r in self.requests if host is None or r.url.host == host)

    # -- providers --------------------------------------------------------------------------
    def json(self, host: str, path: str, payload: object, *, status: int = 200) -> None:
        """Answer ``host``/``path`` with an arbitrary JSON document."""
        self.route(host, path, lambda _r: httpx.Response(status, json=payload))

    def greenhouse(self, token: str, jobs: Sequence[object]) -> None:
        """A Greenhouse board listing ``jobs``."""
        payload = {"jobs": list(jobs), "meta": {"total": len(jobs)}}
        self.json(GREENHOUSE_HOST, f"/v1/boards/{token}/jobs", payload)

    def ashby(self, token: str, jobs: Sequence[object]) -> None:
        """An Ashby job board listing ``jobs``."""
        self.json(
            ASHBY_HOST, f"/posting-api/job-board/{token}", {"apiVersion": "1", "jobs": list(jobs)}
        )

    def lever(self, site: str, postings: Sequence[object]) -> None:
        """A Lever site that honours ``skip`` and ``limit`` like the real API."""
        items = list(postings)

        def respond(request: httpx.Request) -> httpx.Response:
            skip = int(request.url.params.get("skip", "0"))
            limit = int(request.url.params.get("limit", "100"))
            return httpx.Response(200, json=items[skip : skip + limit])

        self.route(LEVER_HOST, f"/v0/postings/{site}", respond)

    def status(
        self, host: str, path: str, status: int, *, headers: dict[str, str] | None = None
    ) -> None:
        self.route(host, path, lambda _r: httpx.Response(status, headers=headers, text="nope"))

    def raw(
        self, host: str, path: str, content: bytes, *, headers: dict[str, str] | None = None
    ) -> None:
        self.route(host, path, lambda _r: httpx.Response(200, content=content, headers=headers))

    def fail(self, host: str, path: str, error: Exception) -> None:
        def boom(_r: httpx.Request) -> httpx.Response:
            raise error

        self.route(host, path, boom)


# ---------------------------------------------------------------------------------------------
# Helpers that drive the HTTP API (``client`` is a Starlette/FastAPI TestClient)
# ---------------------------------------------------------------------------------------------
def error_of(response: Any) -> dict[str, Any]:
    """The ``error`` object of an error response, asserting the envelope shape."""
    body = response.json()
    assert set(body) == {"error"}, body
    error = body["error"]
    assert set(error) <= {"code", "message", "details"}, error
    assert isinstance(error["code"], str)
    assert error["code"] == error["code"].lower()
    assert isinstance(error["message"], str)
    return dict(error)


def add_source(
    client: Any,
    *,
    provider: str = "greenhouse",
    token: str = "acme",
    company_name: str = "Acme Inc.",
) -> dict[str, Any]:
    response = client.post(
        "/api/sources",
        json={"provider": provider, "token": token, "company_name": company_name},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def refresh(client: Any, source_id: int) -> Any:
    return client.post(f"/api/sources/{source_id}/refresh")


def import_csv(client: Any, csv_text: str, label: str = "leads", **extra: Any) -> Any:
    return client.post(
        "/api/imports/csv", json={"dataset_label": label, "csv_text": csv_text, **extra}
    )


def _cell(value: str) -> str:
    if any(ch in value for ch in ',"\r\n'):
        return '"' + value.replace('"', '""') + '"'
    return value


def csv_of(*rows: tuple[str, ...], header: str = "company_name,title,location,work_mode") -> str:
    """CSV text for ``rows`` (cells are quoted when they need it)."""
    lines = [header, *(",".join(_cell(cell) for cell in row) for row in rows)]
    return "\r\n".join(lines) + "\r\n"


def analysis(client: Any, **params: str) -> dict[str, Any]:
    response = client.get("/api/analysis", params=params)
    assert response.status_code == 200, response.text
    return dict(response.json())


def company_named(data: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [c for c in data["companies"] if c["name"] == name]
    assert len(matches) == 1, [c["name"] for c in data["companies"]]
    return dict(matches[0])


# ---------------------------------------------------------------------------------------------
# Realistic provider payload builders
# ---------------------------------------------------------------------------------------------
def gh_job(
    job_id: int | str | None,
    title: str,
    *,
    location: str | None = "New York, NY",
    department: str | None = "Engineering",
    first_published: str | None = "2026-09-20T09:15:00-04:00",
    url: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    job: dict[str, Any] = {
        "title": title,
        "updated_at": "2026-10-01T10:00:00-04:00",
        "requisition_id": "REQ-1",
        "content": "&lt;p&gt;Never stored&lt;/p&gt;",
        "internal_job_id": 4000000,
    }
    if job_id is not None:
        job["id"] = job_id
    if location is not None:
        job["location"] = {"name": location}
    if department is not None:
        job["departments"] = [{"id": 1, "name": department, "child_ids": [], "parent_id": None}]
    if first_published is not None:
        job["first_published"] = first_published
    job["absolute_url"] = url or f"https://boards.greenhouse.io/acme/jobs/{job_id}"
    job.update(extra)
    return job


def lever_posting(
    posting_id: str | None,
    text: str,
    *,
    location: str | None = "Berlin",
    department: str | None = "Product",
    team: str | None = None,
    workplace: str | None = None,
    created_at: Any = 1_758_000_000_000,
    url: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    categories: dict[str, Any] = {"commitment": "Full-time"}
    if location is not None:
        categories["location"] = location
    if department is not None:
        categories["department"] = department
    if team is not None:
        categories["team"] = team
    posting: dict[str, Any] = {
        "text": text,
        "categories": categories,
        "country": "DE",
        "descriptionPlain": "Never stored",
        "applyUrl": f"https://jobs.lever.co/acme/{posting_id}/apply",
    }
    if posting_id is not None:
        posting["id"] = posting_id
        posting["hostedUrl"] = url or f"https://jobs.lever.co/acme/{posting_id}"
    if workplace is not None:
        posting["workplaceType"] = workplace
    if created_at is not None:
        posting["createdAt"] = created_at
    posting.update(extra)
    return posting


def ashby_job(
    title: str,
    *,
    job_url: str | None = "https://jobs.ashbyhq.com/acme/3f2a0c1e-5b7d-4e8a-9c11-0a1b2c3d4e5f",
    apply_url: str | None = None,
    location: str | None = "Remote - Europe",
    department: str | None = "Engineering",
    team: str | None = None,
    workplace: str | None = "Remote",
    is_remote: bool | None = None,
    is_listed: bool | None = True,
    published_at: str | None = "2026-09-25T00:00:00.000+00:00",
    **extra: Any,
) -> dict[str, Any]:
    job: dict[str, Any] = {"title": title, "descriptionHtml": "<p>Never stored</p>"}
    if job_url is not None:
        job["jobUrl"] = job_url
    if apply_url is not None:
        job["applyUrl"] = apply_url
    if location is not None:
        job["location"] = location
    if department is not None:
        job["department"] = department
    if team is not None:
        job["team"] = team
    if workplace is not None:
        job["workplaceType"] = workplace
    if is_remote is not None:
        job["isRemote"] = is_remote
    if is_listed is not None:
        job["isListed"] = is_listed
    if published_at is not None:
        job["publishedAt"] = published_at
    job.update(extra)
    return job
