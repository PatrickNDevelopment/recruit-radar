"""The shared polite HTTP client: error taxonomy, caps, redirects, tokens, read-only guarantee."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from rr_support import (
    ASHBY_HOST,
    GREENHOUSE_HOST,
    LEVER_HOST,
    FakeAts,
    gh_job,
    lever_posting,
)

import recruit_radar.adapters as adapters_package
from recruit_radar import __version__
from recruit_radar.adapters import AdapterError, InvalidToken, PoliteClient, build_adapter
from recruit_radar.adapters.base import (
    MAX_ITEMS,
    MAX_RESPONSE_BYTES,
    TIMEOUT_S,
    quote_token,
    validate_token,
)

URL = f"https://{GREENHOUSE_HOST}/v1/boards/acme/jobs"

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler, **kwargs: Any) -> PoliteClient:
    return PoliteClient(transport=httpx.MockTransport(handler), **kwargs)


def fetch_error(handler: Handler, **kwargs: Any) -> AdapterError:
    with make_client(handler, **kwargs) as client, pytest.raises(AdapterError) as caught:
        client.get_json(URL)
    return caught.value


# -- status mapping ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (404, "not_found"),
        (401, "unauthorized"),
        (403, "unauthorized"),
        (429, "rate_limited"),
        (500, "server_error"),
        (502, "server_error"),
        (503, "server_error"),
        (599, "server_error"),
        # Not in the spec taxonomy: an answer that is not the documented JSON payload.
        (400, "malformed"),
        (410, "malformed"),
        (418, "malformed"),
        (204, "malformed"),  # 2xx with an empty body is not JSON
    ],
)
def test_http_status_maps_to_the_spec_error_kind(status: int, kind: str) -> None:
    error = fetch_error(lambda _r: httpx.Response(status))
    assert error.kind == kind
    assert error.http_status == status


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("30", 30),
        ("0", 0),
        (" 7 ", 7),
        ("120", 120),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
        ("-5", None),
        ("1.5", None),
        ("soon", None),
        ("9999999999", None),
        ("", None),
    ],
)
def test_retry_after_is_recorded_only_when_an_integer(header: str, expected: int | None) -> None:
    error = fetch_error(lambda _r: httpx.Response(429, headers={"Retry-After": header}))
    assert error.kind == "rate_limited"
    assert error.retry_after_s == expected


def test_429_without_retry_after() -> None:
    error = fetch_error(lambda _r: httpx.Response(429))
    assert (error.kind, error.retry_after_s, error.http_status) == ("rate_limited", None, 429)


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("slow"),
        httpx.ConnectTimeout("slow"),
        httpx.WriteTimeout("slow"),
        httpx.PoolTimeout("slow"),
    ],
)
def test_timeouts_map_to_timeout(exc: Exception) -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise exc

    error = fetch_error(boom)
    assert error.kind == "timeout"
    assert error.http_status is None


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("refused"),
        httpx.ReadError("reset"),
        httpx.RemoteProtocolError("bad framing"),
        httpx.NetworkError("down"),
    ],
)
def test_transport_errors_map_to_network(exc: Exception) -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise exc

    error = fetch_error(boom)
    assert error.kind == "network"
    assert error.http_status is None


@pytest.mark.parametrize(
    "body",
    [b"<html>maintenance</html>", b"", b"{not json", b'{"jobs": [', b"\xff\xfe\x00bad"],
)
def test_non_json_body_is_malformed(body: bytes) -> None:
    error = fetch_error(lambda _r: httpx.Response(200, content=body))
    assert error.kind == "malformed"
    assert error.http_status == 200


def test_undecodable_content_encoding_is_malformed() -> None:
    error = fetch_error(
        lambda _r: httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=b"this is not gzip data"
        )
    )
    assert error.kind == "malformed"


def test_deeply_nested_json_is_malformed_not_a_crash() -> None:
    body = b"[" * 100_000 + b"]" * 100_000
    error = fetch_error(lambda _r: httpx.Response(200, content=body))
    assert error.kind == "malformed"


def test_valid_json_of_any_shape_is_returned_untouched() -> None:
    with make_client(lambda _r: httpx.Response(200, json=[1, "a", None])) as client:
        response = client.get_json(URL)
    assert response.data == [1, "a", None]
    assert response.http_status == 200


# -- size cap ----------------------------------------------------------------------------------
def test_declared_oversized_body_is_refused_before_reading() -> None:
    error = fetch_error(
        lambda _r: httpx.Response(200, headers={"content-length": "999999"}, content=b"{}"),
        max_bytes=1000,
    )
    assert error.kind == "too_large"


def test_streamed_oversized_body_is_cut_off_without_a_content_length() -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(100):
            yield b"[" + b"0," * 100 + b"0]"

    error = fetch_error(lambda _r: httpx.Response(200, content=chunks()), max_bytes=1000)
    assert error.kind == "too_large"


def test_body_exactly_at_the_cap_is_accepted() -> None:
    body = b'["' + b"x" * 996 + b'"]'
    assert len(body) == 1000
    with make_client(lambda _r: httpx.Response(200, content=body), max_bytes=1000) as client:
        assert client.get_json(URL).data == ["x" * 996]


def test_default_caps_are_the_spec_values() -> None:
    assert MAX_RESPONSE_BYTES == 10 * 1024 * 1024
    assert MAX_ITEMS == 5000
    assert TIMEOUT_S == 15.0


# -- redirects ---------------------------------------------------------------------------------
def test_redirect_within_the_same_origin_is_followed() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/jobs"):
            return httpx.Response(301, headers={"Location": "/v1/boards/acme/jobs/page2"})
        return httpx.Response(200, json={"ok": True})

    with make_client(handler) as client:
        assert client.get_json(URL).data == {"ok": True}
    assert seen == [URL, f"https://{GREENHOUSE_HOST}/v1/boards/acme/jobs/page2"]


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/v1/boards/acme/jobs",
        f"https://{GREENHOUSE_HOST}.evil.example/x",
        f"http://{GREENHOUSE_HOST}/v1/boards/acme/jobs",  # scheme downgrade
        f"https://{GREENHOUSE_HOST}:8443/v1/boards/acme/jobs",  # other port
        "//evil.example/x",
    ],
)
def test_redirect_to_another_origin_is_refused_and_never_requested(location: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": location})

    error = fetch_error(handler)
    assert error.kind == "malformed"
    assert "redirect" in error.message.lower()
    assert seen == [URL]  # the second origin was never contacted


def test_redirect_loop_and_missing_location_are_malformed() -> None:
    hits = {"n": 0}

    def loop(_request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(302, headers={"Location": URL})

    error = fetch_error(loop)
    assert error.kind == "malformed"
    assert hits["n"] == 4  # the original request plus MAX_REDIRECTS follow-ups
    assert fetch_error(lambda _r: httpx.Response(302)).kind == "malformed"


# -- request shape -----------------------------------------------------------------------------
def test_requests_are_single_get_with_identifying_user_agent_and_query() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    with make_client(handler) as client:
        client.get_json(URL, {"content": "true"})
        assert client.requests == 1
    (request,) = seen
    assert request.method == "GET"
    assert request.url.params["content"] == "true"
    assert request.headers["user-agent"] == f"RecruitRadar/{__version__} (+read-only)"
    assert request.headers["accept"] == "application/json"
    assert "cookie" not in request.headers
    assert "authorization" not in request.headers
    assert request.content == b""


def test_client_ignores_proxy_and_netrc_environment() -> None:
    with make_client(lambda _r: httpx.Response(200, json={})) as client:
        assert client._client.trust_env is False


def test_the_client_offers_no_way_to_send_anything_but_get() -> None:
    forbidden = ("post", "put", "patch", "delete", "request", "send", "stream", "head", "options")
    assert not [name for name in forbidden if hasattr(PoliteClient, name)]

    package_dir = Path(adapters_package.__file__).parent
    sources = {path.name: path.read_text(encoding="utf-8") for path in package_dir.glob("*.py")}
    assert {"base.py", "greenhouse.py", "lever.py", "ashby.py"} <= set(sources)
    needles = (".post(", ".put(", ".patch(", ".delete(", '"POST"', '"PUT"', '"DELETE"', '"PATCH"')
    for name, text in sources.items():
        for needle in needles:
            assert needle not in text, f"{name} contains {needle}"
    assert 'stream("GET"' in sources["base.py"]


# -- tokens ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "token",
    [
        "a",
        "acme",
        "Acme-Corp_2.0",
        "0",
        "a.b",
        "a..b",
        "x" * 100,
        "-",
        "_",
        "ACME",
        ".hidden",
        "a.",
    ],
)
def test_valid_tokens(token: str) -> None:
    assert validate_token(token) == token
    assert quote_token(token) == token  # nothing in the allowed alphabet needs quoting


@pytest.mark.parametrize(
    "token",
    [
        "",
        "x" * 101,
        "../",
        "..",
        ".",
        "...",
        "a/b",
        "../etc/passwd",
        "a%2fb",
        "%2e%2e",
        "a b",
        " acme",
        "acme ",
        "acme\n",
        "acme\x00",
        "a?b=1",
        "a#b",
        "a:b",
        "a@b",
        "a\\b",
        "é",
        "ａｃｍｅ",  # full-width letters
        "１２３",  # full-width digits
        "ac\u200bme",
        "ünicode",
    ],
)
def test_invalid_tokens_are_refused(token: str) -> None:
    with pytest.raises(InvalidToken):
        validate_token(token)
    with pytest.raises(InvalidToken):
        quote_token(token)


@pytest.mark.parametrize("provider", ["greenhouse", "lever", "ashby"])
def test_an_invalid_token_never_reaches_the_network(provider: str) -> None:
    ats = FakeAts()
    adapter = build_adapter(provider, f"https://{GREENHOUSE_HOST}")
    with PoliteClient(transport=ats.transport()) as client:
        for token in ("../", "a%2fb", "é", "x" * 101, ""):
            with pytest.raises(InvalidToken):
                adapter.fetch(client, token, "Acme")
    assert ats.requests == []


def test_valid_tokens_land_in_the_url_path_verbatim() -> None:
    ats = FakeAts()
    token = "Acme-Corp_2.0"
    ats.greenhouse(token, [gh_job(1, "Engineer")])
    ats.lever(token, [lever_posting("a1", "Engineer")])
    ats.ashby(token, [])
    with PoliteClient(transport=ats.transport()) as client:
        build_adapter("greenhouse", f"https://{GREENHOUSE_HOST}").fetch(client, token, "Acme")
        build_adapter("lever", f"https://{LEVER_HOST}").fetch(client, token, "Acme")
        build_adapter("ashby", f"https://{ASHBY_HOST}").fetch(client, token, "Acme")
    paths = [r.url.path for r in ats.requests]
    assert paths == [
        f"/v1/boards/{token}/jobs",
        f"/v0/postings/{token}",
        f"/posting-api/job-board/{token}",
    ]
    assert all(r.method == "GET" for r in ats.requests)
    assert ats.requests[0].url.params["content"] == "true"
    assert dict(ats.requests[1].url.params) == {"mode": "json", "skip": "0", "limit": "100"}
