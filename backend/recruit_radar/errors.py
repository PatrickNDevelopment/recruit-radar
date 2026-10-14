"""Application errors that the API layer renders as the spec 03 error envelope."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """An error with an HTTP status and a stable snake_case ``code`` (spec 03).

    Services raise it; ``recruit_radar.api.errors`` turns it into
    ``{"error": {"code", "message", "details"?}}`` with ``status_code``.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}
