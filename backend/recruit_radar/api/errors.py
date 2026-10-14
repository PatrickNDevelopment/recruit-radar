"""The spec 03 error envelope and the handlers that produce it.

Every non-2xx answer is ``{"error": {"code", "message", "details"?}}``. Nothing else leaves the
API: validation failures, unknown routes, wrong methods and unexpected exceptions all use it.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..errors import AppError

log = logging.getLogger("recruit_radar.api")

# Route function name -> the 422 code spec 03 names for that endpoint.
_VALIDATION_CODES: Final = {
    "put_profile": "invalid_profile",
    "create_source": "invalid_source",
    "import_csv": "invalid_csv",
    "create_posting": "invalid_posting",
    "create_merge_decision": "invalid_decision",
    "put_company_shortlist": "invalid_shortlist",
}

_HTTP_CODES: Final = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
}


def envelope(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def _app_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(exc.code, exc.message, exc.details),
        headers=exc.headers or None,
    )


def _validation_code(request: Request, locs: list[tuple[Any, ...]]) -> str:
    route = request.scope.get("route")
    name = getattr(route, "name", "")
    code = _VALIDATION_CODES.get(name, "invalid_request")
    if name == "create_source" and any(loc and loc[-1] == "token" for loc in locs):
        return "invalid_token"
    return code


def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    problems: list[dict[str, Any]] = []
    locs: list[tuple[Any, ...]] = []
    for error in exc.errors():
        loc = tuple(error.get("loc", ()))
        locs.append(loc)
        problems.append(
            {
                "loc": [part for part in loc if isinstance(part, str | int)],
                "message": str(error.get("msg", "invalid value")),
                "type": str(error.get("type", "value_error")),
            }
        )
    first = problems[0] if problems else None
    where = ".".join(str(part) for part in first["loc"]) if first else ""
    message = "The request is invalid"
    if first is not None:
        message += f": {where}: {first['message']}" if where else f": {first['message']}"
    code = _validation_code(request, locs)
    return JSONResponse(status_code=422, content=envelope(code, message, {"errors": problems}))


def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    message = str(exc.detail) if exc.detail else code.replace("_", " ")
    headers = dict(exc.headers) if exc.headers else None
    return JSONResponse(
        status_code=exc.status_code, content=envelope(code, message), headers=headers
    )


def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error in %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=envelope("internal_error", "The server hit an unexpected error; see its log"),
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected)
