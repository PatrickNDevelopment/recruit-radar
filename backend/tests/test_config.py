"""Settings: defaults, environment overrides and the refusal of unsafe values."""

from __future__ import annotations

from pathlib import Path

import pytest

from recruit_radar.config import (
    DEFAULT_BASE_URLS,
    DEFAULT_DB_PATH,
    ConfigError,
    Settings,
    normalize_base_url,
)


def test_defaults_match_the_spec() -> None:
    settings = Settings.from_env({})
    assert settings.db_path == DEFAULT_DB_PATH
    assert settings.db_path.parts[-3:] == ("backend", "data", "recruit_radar.sqlite3")
    assert settings.cors_origins == ("http://localhost:5173", "http://localhost:4174")
    assert settings.min_refresh_interval_s == 60
    assert settings.host == "127.0.0.1"
    assert settings.port == 8787
    assert dict(settings.base_urls) == dict(DEFAULT_BASE_URLS)
    assert settings.base_url_is_default("greenhouse")
    assert settings.base_host("lever") == "api.lever.co"


def test_environment_overrides(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "RECRUIT_RADAR_DB_PATH": str(tmp_path / "x.sqlite3"),
            "RECRUIT_RADAR_CORS_ORIGINS": "http://localhost:3000/, https://example.org",
            "RECRUIT_RADAR_MIN_REFRESH_INTERVAL_S": "0",
            "RECRUIT_RADAR_HOST": "localhost",
            "RECRUIT_RADAR_PORT": "9000",
            "RECRUIT_RADAR_GREENHOUSE_BASE_URL": "http://127.0.0.1:8788",
            "RECRUIT_RADAR_LEVER_BASE_URL": "https://api.eu.lever.co",
            "RECRUIT_RADAR_ASHBY_BASE_URL": "http://localhost:8788/",
        }
    )
    assert settings.db_path == (tmp_path / "x.sqlite3").resolve()
    assert settings.cors_origins == ("http://localhost:3000", "https://example.org")
    assert settings.min_refresh_interval_s == 0
    assert (settings.host, settings.port) == ("localhost", 9000)
    assert settings.base_urls["greenhouse"] == "http://127.0.0.1:8788"
    assert settings.base_urls["lever"] == "https://api.eu.lever.co"
    assert settings.base_urls["ashby"] == "http://localhost:8788"
    assert settings.base_host("greenhouse") == "127.0.0.1:8788"
    assert not settings.base_url_is_default("greenhouse")
    assert settings.base_url_is_default("ashby") is False


def test_the_empty_cors_variable_means_no_origin_at_all() -> None:
    assert Settings.from_env({"RECRUIT_RADAR_CORS_ORIGINS": ""}).cors_origins == ()


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("RECRUIT_RADAR_CORS_ORIGINS", "*"),
        ("RECRUIT_RADAR_CORS_ORIGINS", "localhost:5173"),
        ("RECRUIT_RADAR_CORS_ORIGINS", "http://localhost:5173/app"),
        ("RECRUIT_RADAR_MIN_REFRESH_INTERVAL_S", "soon"),
        ("RECRUIT_RADAR_MIN_REFRESH_INTERVAL_S", "-1"),
        ("RECRUIT_RADAR_MIN_REFRESH_INTERVAL_S", "100000"),
        ("RECRUIT_RADAR_PORT", "0"),
        ("RECRUIT_RADAR_PORT", "70000"),
        ("RECRUIT_RADAR_PORT", "http"),
    ],
)
def test_bad_values_are_refused_at_start_up(variable: str, value: str) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({variable: value})


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example",
        "http://boards-api.greenhouse.io",  # real host over plain http
        "https://boards-api.greenhouse.io.evil.example",  # look-alike suffix
        "https://boards-api.greenhouse.io" + "@evil.example",  # userinfo trick
        "https://user:pw" + "@boards-api.greenhouse.io",
        "https://boards-api.greenhouse.io/v1",  # path
        "https://boards-api.greenhouse.io?x=1",
        "ftp://localhost",
        "boards-api.greenhouse.io",
        "http://localhost:notaport",
        "https://api.lever.co",  # a Lever host is not a Greenhouse host
    ],
)
def test_greenhouse_base_url_must_be_the_real_host_or_loopback(url: str) -> None:
    with pytest.raises(ConfigError):
        normalize_base_url("greenhouse", url)


def test_each_provider_accepts_only_its_own_hosts() -> None:
    assert normalize_base_url("lever", "https://API.lever.co/") == "https://api.lever.co"
    assert normalize_base_url("lever", "https://api.eu.lever.co") == "https://api.eu.lever.co"
    assert normalize_base_url("ashby", "http://[::1]:8788") == "http://[::1]:8788"
    with pytest.raises(ConfigError):
        normalize_base_url("ashby", "https://api.lever.co")


def test_settings_object_validates_itself() -> None:
    with pytest.raises(ConfigError):
        Settings(min_refresh_interval_s=-5)
    with pytest.raises(ConfigError):
        Settings(base_urls={"greenhouse": "https://evil.example"})
    overridden = Settings().with_overrides(port=1234)
    assert overridden.port == 1234
