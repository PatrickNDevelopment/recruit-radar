"""Read-only adapters for the three public ATS JSON APIs (spec 04)."""

from __future__ import annotations

from typing import Protocol

from .ashby import AshbyAdapter
from .base import (
    AdapterError,
    ErrorKind,
    FetchOutcome,
    InvalidToken,
    PoliteClient,
    Tally,
    validate_token,
)
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter


class Adapter(Protocol):
    provider: str

    def fetch(self, client: PoliteClient, token: str, company_name: str) -> FetchOutcome: ...


def build_adapter(provider: str, base_url: str) -> Adapter:
    """The adapter for ``provider`` reading from ``base_url`` (an origin, no path)."""
    if provider == "greenhouse":
        return GreenhouseAdapter(base_url)
    if provider == "lever":
        return LeverAdapter(base_url)
    if provider == "ashby":
        return AshbyAdapter(base_url)
    raise ValueError(f"unknown provider {provider!r}")


__all__ = [
    "Adapter",
    "AdapterError",
    "ErrorKind",
    "FetchOutcome",
    "InvalidToken",
    "PoliteClient",
    "Tally",
    "build_adapter",
    "validate_token",
]
