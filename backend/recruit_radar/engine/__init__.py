"""RecruitRadar's pure analysis engine.

``analyze(input)`` turns snapshots of public job postings into companies, canonical roles,
lifecycle events, merge candidates and an explainable priority score. It is a deterministic
function of its argument: no clock, no randomness, no I/O. The TypeScript engine in
``src/engine`` implements the same contract independently.
"""

from .analyze import analyze
from .errors import EngineInputError

__all__ = ["EngineInputError", "analyze"]
