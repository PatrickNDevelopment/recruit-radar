"""Shared, deliberately conservative HTTP client and types for the ATS adapters (spec 04).

Policy enforced here, not left to each provider module:

* only ``GET``; one request per page, sequential; a fixed read-only ``User-Agent``;
* 15 s timeout; a hard cap on decoded body size (10 MB) and on item count (5,000);
* redirects are followed only within the original scheme + host + port;
* no environment proxies, ``.netrc`` credentials or cookies leak into a request;
* the HTTP/JSON failure taxonomy of spec 04 is the only way an error leaves this module.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Final, Literal, Self
from urllib.parse import quote, urlsplit

import httpx

from .. import __version__
from ..normalization import CleanPosting

ErrorKind = Literal[
    "not_found",
    "unauthorized",
    "rate_limited",
    "server_error",
    "network",
    "timeout",
    "malformed",
    "too_large",
]

USER_AGENT: Final = f"RecruitRadar/{__version__} (+read-only)"
TIMEOUT_S: Final = 15.0
MAX_RESPONSE_BYTES: Final = 10 * 1024 * 1024
MAX_ITEMS: Final = 5000
MAX_REDIRECTS: Final = 3

_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9_.\-]{1,100}")
_RETRY_AFTER_RE: Final = re.compile(r"[0-9]{1,9}")


class InvalidToken(ValueError):
    """A board token / site / board name is not acceptable."""


def validate_token(token: str) -> str:
    """Spec 03/04: ``^[A-Za-z0-9_.-]{1,100}$`` (matched in full, ASCII only).

    A token made only of dots (``.``, ``..``) also satisfies that pattern but is a path
    traversal segment once placed in a URL, so it is refused as well.
    """
    if _TOKEN_RE.fullmatch(token) is None:
        raise InvalidToken("token must be 1-100 characters from A-Z a-z 0-9 _ . -")
    if token.strip(".") == "":
        raise InvalidToken("token must not consist only of dots")
    return token


def quote_token(token: str) -> str:
    """The only way a token is put into a URL path."""
    return quote(validate_token(token), safe="")


def host_of(base_url: str) -> str:
    """``host[:port]`` of an origin, for run messages and the UI."""
    return urlsplit(base_url).netloc


class AdapterError(Exception):
    """A provider call failed. ``kind`` is the spec 04 error taxonomy."""

    def __init__(
        self,
        kind: ErrorKind,
        message: str,
        *,
        http_status: int | None = None,
        retry_after_s: int | None = None,
        items_seen: int = 0,
    ) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message
        self.http_status = http_status
        self.retry_after_s = retry_after_s
        self.items_seen = items_seen


@dataclass(frozen=True, slots=True)
class JsonResponse:
    data: object
    http_status: int


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return (url.scheme, url.host, url.port)


class PoliteClient:
    """One short-lived, sequential, GET-only JSON client."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = TIMEOUT_S,
        max_bytes: int = MAX_RESPONSE_BYTES,
        max_redirects: int = MAX_REDIRECTS,
    ) -> None:
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self.requests = 0
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonResponse:
        target = httpx.URL(url, params=dict(params)) if params else httpx.URL(url)
        origin = _origin(target)
        for _ in range(self._max_redirects + 1):
            try:
                self.requests += 1
                with self._client.stream("GET", target) as response:
                    outcome = self._interpret(response, target, origin)
            except httpx.TimeoutException as exc:
                raise AdapterError(
                    "timeout", f"{target.host} did not answer within {self._timeout_s:g} s"
                ) from exc
            except httpx.DecodingError as exc:
                raise AdapterError(
                    "malformed", f"{target.host} sent a body that could not be decoded"
                ) from exc
            except httpx.RequestError as exc:
                raise AdapterError(
                    "network", f"Could not reach {target.host} ({type(exc).__name__})"
                ) from exc
            if isinstance(outcome, JsonResponse):
                return outcome
            target = outcome
        raise AdapterError(
            "malformed", f"{origin[1]} redirected more than {self._max_redirects} times"
        )

    def _interpret(
        self, response: httpx.Response, target: httpx.URL, origin: tuple[str, str, int | None]
    ) -> JsonResponse | httpx.URL:
        status = response.status_code
        host = target.host
        if status in (301, 302, 303, 307, 308):
            location = response.headers.get("location")
            if not location:
                raise AdapterError(
                    "malformed", f"{host} redirected without a location", http_status=status
                )
            try:
                destination = target.join(location)
            except httpx.InvalidURL as exc:
                raise AdapterError(
                    "malformed", f"{host} sent an invalid redirect location", http_status=status
                ) from exc
            if _origin(destination) != origin:
                raise AdapterError(
                    "malformed",
                    f"Refused a redirect from {host} to another host ({destination.host})",
                    http_status=status,
                )
            return destination
        if status == 404:
            raise AdapterError("not_found", f"{host} answered HTTP 404", http_status=status)
        if status in (401, 403):
            raise AdapterError("unauthorized", f"{host} answered HTTP {status}", http_status=status)
        if status == 429:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            suffix = f"; retry after {retry_after} s" if retry_after is not None else ""
            raise AdapterError(
                "rate_limited",
                f"{host} answered HTTP 429{suffix}",
                http_status=status,
                retry_after_s=retry_after,
            )
        if 500 <= status <= 599:
            raise AdapterError("server_error", f"{host} answered HTTP {status}", http_status=status)
        if not 200 <= status <= 299:
            raise AdapterError(
                "malformed", f"{host} answered an unexpected HTTP {status}", http_status=status
            )
        return JsonResponse(self._read_json(response, host), status)

    def _read_json(self, response: httpx.Response, host: str) -> object:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_bytes:
            raise AdapterError(
                "too_large",
                f"{host} announced a {int(declared)} byte response (limit {self._max_bytes})",
                http_status=response.status_code,
            )
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > self._max_bytes:
                raise AdapterError(
                    "too_large",
                    f"{host} response is larger than {self._max_bytes} bytes",
                    http_status=response.status_code,
                )
        try:
            return json.loads(bytes(body))
        except (ValueError, RecursionError) as exc:
            raise AdapterError(
                "malformed", f"{host} did not return valid JSON", http_status=response.status_code
            ) from exc


def _parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    return int(text) if _RETRY_AFTER_RE.fullmatch(text) else None


# ---------------------------------------------------------------------------------------------
# Adapter result types
# ---------------------------------------------------------------------------------------------
@dataclass(slots=True)
class Tally:
    """What was skipped or repaired while mapping provider jobs (reported in the run message)."""

    items_seen: int = 0
    unlisted: int = 0
    dropped: Counter[str] = field(default_factory=Counter)
    omitted: Counter[str] = field(default_factory=Counter)

    @property
    def dropped_total(self) -> int:
        return sum(self.dropped.values())


@dataclass(frozen=True, slots=True)
class FetchOutcome:
    postings: tuple[CleanPosting, ...]
    tally: Tally
    requests: int
    host: str


def require_some_valid(tally: Tally, valid: int, http_status: int) -> None:
    """Spec 04: when every (listed) job is invalid the payload is ``malformed``."""
    if valid == 0 and tally.dropped_total > 0:
        reasons = ", ".join(f"{count} {reason}" for reason, count in tally.dropped.most_common(3))
        raise AdapterError(
            "malformed",
            f"All {tally.dropped_total} jobs were invalid ({reasons})",
            http_status=http_status,
            items_seen=tally.items_seen,
        )
