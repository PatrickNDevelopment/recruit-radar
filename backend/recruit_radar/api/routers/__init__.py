"""One router per area of spec 03; ``api.app`` mounts them all under ``/api``."""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import Query

from ..schemas import ErrorEnvelope

# Documented on every router so OpenAPI shows the error envelope instead of FastAPI's default
# validation-error schema (which this API never returns).
ERROR_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    "default": {"model": ErrorEnvelope, "description": "Error envelope (spec 03)"}
}

AsOf = Annotated[
    str | None,
    Query(
        description=(
            "UTC instant YYYY-MM-DDTHH:MM:SSZ the analysis is computed as of. "
            "Default: now (whole seconds). Snapshots observed later are ignored."
        )
    ),
]
