"""No adapter, on any path, ever sends anything but an empty-bodied GET (spec 04)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from rr_support import (
    ASHBY_HOST,
    GREENHOUSE_HOST,
    LEVER_HOST,
    ashby_job,
    gh_job,
    lever_posting,
)

from recruit_radar.adapters import AdapterError, PoliteClient, build_adapter

PROVIDERS = {
    "greenhouse": (GREENHOUSE_HOST, "/v1/boards/acme/jobs"),
    "lever": (LEVER_HOST, "/v0/postings/acme"),
    "ashby": (ASHBY_HOST, "/posting-api/job-board/acme"),
}

OK_PAYLOADS: dict[str, object] = {
    "greenhouse": {"jobs": [gh_job(1, "Engineer")]},
    "lever": [lever_posting("a1", "Engineer")],
    "ashby": {"jobs": [ashby_job("Engineer")]},
}

Scenario = Callable[[str, httpx.Request], httpx.Response]


def ok(provider: str, _request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=OK_PAYLOADS[provider])


def status(code: int) -> Scenario:
    return lambda _p, _r: httpx.Response(code, headers={"Retry-After": "5"})


def redirect_then_ok(provider: str, request: httpx.Request) -> httpx.Response:
    if "moved" not in request.url.path:
        return httpx.Response(307, headers={"Location": request.url.path + "/moved"})
    return httpx.Response(200, json=OK_PAYLOADS[provider])


def junk(_provider: str, _request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"<html/>")


SCENARIOS: dict[str, Scenario] = {
    "ok": ok,
    "404": status(404),
    "401": status(401),
    "429": status(429),
    "500": status(500),
    "same-origin redirect": redirect_then_ok,
    "junk": junk,
}


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_adapter_traffic_is_get_only_with_no_body(provider: str, scenario: str) -> None:
    host, _path = PROVIDERS[provider]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "GET", f"{provider}/{scenario}: {request.method} {request.url}"
        return SCENARIOS[scenario](provider, request)

    adapter = build_adapter(provider, f"https://{host}")
    with PoliteClient(transport=httpx.MockTransport(handler)) as client:
        try:
            adapter.fetch(client, "acme", "Acme")
        except AdapterError:
            pass  # failures are fine; what matters is what was sent

    assert seen, "the scenario never reached the transport"
    for request in seen:
        assert request.method == "GET"
        assert request.content == b""
        assert request.url.host == host
        assert request.url.scheme == "https"
        assert "content-type" not in request.headers  # nothing is being submitted
