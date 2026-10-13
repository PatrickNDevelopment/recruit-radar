"""Exceptions raised by the analysis engine."""

from __future__ import annotations


class EngineInputError(ValueError):
    """The input handed to :func:`recruit_radar.engine.analyze` is invalid.

    The engine validates its whole input at the boundary (see ``models.py``) and raises this
    single, clearly named error instead of producing a partially meaningful analysis.
    """
