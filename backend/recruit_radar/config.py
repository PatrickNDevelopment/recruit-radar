"""Environment-driven settings (spec 03/04).

Nothing here reads a secret: the three ATS endpoints need no key. The adapter base URLs can
be overridden from the environment *only* so tests and the Playwright journey can point a
refresh at a local fake ATS server; a base URL that is neither the provider's real host nor a
loopback address is refused at start-up.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final
from urllib.parse import SplitResult, urlsplit

BACKEND_DIR: Final = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH: Final = BACKEND_DIR / "data" / "recruit_radar.sqlite3"
DEFAULT_CORS_ORIGINS: Final = ("http://localhost:5173", "http://localhost:4174")
DEFAULT_MIN_REFRESH_INTERVAL_S: Final = 60
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8787

PROVIDERS: Final = ("greenhouse", "lever", "ashby")

DEFAULT_BASE_URLS: Final[Mapping[str, str]] = {
    "greenhouse": "https://boards-api.greenhouse.io",
    "lever": "https://api.lever.co",
    "ashby": "https://api.ashbyhq.com",
}
# Hosts a provider may legitimately be reached on without the loopback test override.
PRODUCTION_HOSTS: Final[Mapping[str, frozenset[str]]] = {
    "greenhouse": frozenset({"boards-api.greenhouse.io"}),
    "lever": frozenset({"api.lever.co", "api.eu.lever.co"}),
    "ashby": frozenset({"api.ashbyhq.com"}),
}
LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
# Bind addresses that name "every interface", not a host a browser would put in a Host header.
_WILDCARD_BINDS: Final = frozenset({"", "0.0.0.0", "::", "*"})
_HOSTNAME_RE: Final = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")

_ENV_BASE_URL: Final[Mapping[str, str]] = {
    "greenhouse": "RECRUIT_RADAR_GREENHOUSE_BASE_URL",
    "lever": "RECRUIT_RADAR_LEVER_BASE_URL",
    "ashby": "RECRUIT_RADAR_ASHBY_BASE_URL",
}


class ConfigError(ValueError):
    """A setting has an unusable value."""


def _origin(parts: SplitResult) -> str:
    host = parts.hostname or ""
    rendered = f"[{host}]" if ":" in host else host
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{parts.scheme}://{rendered}{port}"


def normalize_base_url(provider: str, value: str) -> str:
    """Validate an adapter base URL (an origin) and return its canonical ``scheme://host[:port]``.

    Allowed: ``https`` on one of the provider's real hosts, or ``http``/``https`` on a loopback
    host (``localhost``, ``127.0.0.1``, ``::1``) for a local fake server.
    """
    text = value.strip()
    try:
        parts = urlsplit(text)
        _ = parts.port  # reading it raises ValueError for a malformed port
    except ValueError as exc:
        raise ConfigError(f"{provider} base URL is not a valid URL: {value!r}") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError(f"{provider} base URL must be an http(s) origin, got {value!r}")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError(f"{provider} base URL must not carry credentials, query or fragment")
    if parts.path not in ("", "/"):
        raise ConfigError(f"{provider} base URL must be an origin without a path, got {value!r}")
    host = parts.hostname.lower()
    if host in LOOPBACK_HOSTS:
        return _origin(parts._replace(netloc=parts.netloc.lower()))
    if parts.scheme != "https" or host not in PRODUCTION_HOSTS[provider]:
        allowed = ", ".join(sorted(PRODUCTION_HOSTS[provider]))
        raise ConfigError(
            f"{provider} base URL {value!r} refused: only https on {allowed} "
            "or a loopback host (localhost, 127.0.0.1) is allowed"
        )
    return _origin(parts._replace(netloc=parts.netloc.lower()))


def _parse_origins(raw: str) -> tuple[str, ...]:
    origins: list[str] = []
    for item in raw.split(","):
        origin = item.strip()
        if not origin:
            continue
        if origin == "*":
            raise ConfigError("RECRUIT_RADAR_CORS_ORIGINS must list explicit origins, not '*'")
        try:
            parts = urlsplit(origin)
        except ValueError as exc:
            raise ConfigError(f"CORS origin is not a valid URL: {origin!r}") from exc
        if (
            parts.scheme not in ("http", "https")
            or not parts.netloc
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ConfigError(f"CORS origin must look like http(s)://host[:port], got {origin!r}")
        origins.append(origin.rstrip("/"))
    return tuple(origins)


def _parse_hosts(raw: str) -> tuple[str, ...]:
    hosts: list[str] = []
    for item in raw.split(","):
        host = item.strip().lower()
        if not host:
            continue
        if host == "*":
            raise ConfigError("RECRUIT_RADAR_ALLOWED_HOSTS must list explicit host names, not '*'")
        if host not in LOOPBACK_HOSTS and _HOSTNAME_RE.fullmatch(host) is None:
            raise ConfigError(
                f"RECRUIT_RADAR_ALLOWED_HOSTS entries are bare host names (no scheme, port or "
                f"path), got {item.strip()!r}"
            )
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _parse_int(name: str, raw: str, *, minimum: int, maximum: int) -> int:
    try:
        number = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if not minimum <= number <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {number}")
    return number


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings. Build with :meth:`from_env` or construct directly in tests."""

    db_path: Path = DEFAULT_DB_PATH
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    min_refresh_interval_s: int = DEFAULT_MIN_REFRESH_INTERVAL_S
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    base_urls: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_BASE_URLS))
    # Host names the API answers to besides loopback and the bind address. A request whose Host
    # header names anything else is refused: that is what a DNS-rebinding page sends.
    allowed_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.min_refresh_interval_s < 0:
            raise ConfigError("min_refresh_interval_s must not be negative")
        checked: dict[str, str] = {}
        for provider in PROVIDERS:
            checked[provider] = normalize_base_url(
                provider, self.base_urls.get(provider, DEFAULT_BASE_URLS[provider])
            )
        object.__setattr__(self, "base_urls", checked)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        db_path = DEFAULT_DB_PATH
        if env.get("RECRUIT_RADAR_DB_PATH"):
            db_path = Path(env["RECRUIT_RADAR_DB_PATH"]).expanduser().resolve()
        cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
        if "RECRUIT_RADAR_CORS_ORIGINS" in env:
            cors_origins = _parse_origins(env["RECRUIT_RADAR_CORS_ORIGINS"])
        interval = DEFAULT_MIN_REFRESH_INTERVAL_S
        if env.get("RECRUIT_RADAR_MIN_REFRESH_INTERVAL_S"):
            interval = _parse_int(
                "RECRUIT_RADAR_MIN_REFRESH_INTERVAL_S",
                env["RECRUIT_RADAR_MIN_REFRESH_INTERVAL_S"],
                minimum=0,
                maximum=86_400,
            )
        allowed_hosts: tuple[str, ...] = ()
        if env.get("RECRUIT_RADAR_ALLOWED_HOSTS"):
            allowed_hosts = _parse_hosts(env["RECRUIT_RADAR_ALLOWED_HOSTS"])
        host = DEFAULT_HOST
        if env.get("RECRUIT_RADAR_HOST"):
            host = env["RECRUIT_RADAR_HOST"].strip()
        port = DEFAULT_PORT
        if env.get("RECRUIT_RADAR_PORT"):
            port = _parse_int(
                "RECRUIT_RADAR_PORT", env["RECRUIT_RADAR_PORT"], minimum=1, maximum=65_535
            )
        base_urls = dict(DEFAULT_BASE_URLS)
        for provider, variable in _ENV_BASE_URL.items():
            if env.get(variable):
                base_urls[provider] = env[variable]
        return cls(
            db_path=db_path,
            cors_origins=cors_origins,
            min_refresh_interval_s=interval,
            host=host,
            port=port,
            base_urls=base_urls,
            allowed_hosts=allowed_hosts,
        )

    def with_overrides(self, **changes: Any) -> Settings:
        return replace(self, **changes)

    def served_hosts(self) -> frozenset[str]:
        """Every host name a request may carry in its ``Host`` header (lower case, no port)."""
        hosts = set(LOOPBACK_HOSTS) | set(self.allowed_hosts)
        bind = self.host.strip().lower().strip("[]")
        if bind not in _WILDCARD_BINDS:
            hosts.add(bind)
        return frozenset(hosts)

    def base_url_is_default(self, provider: str) -> bool:
        return self.base_urls[provider] == DEFAULT_BASE_URLS[provider]

    def base_host(self, provider: str) -> str:
        parts = urlsplit(self.base_urls[provider])
        host = parts.hostname or ""
        return f"{host}:{parts.port}" if parts.port is not None else host
