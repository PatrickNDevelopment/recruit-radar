"""Boundary validation for ``analyze`` input and the normalized records the engine works on.

Two layers:

* ``*In`` Pydantic models describe the JSON-compatible input of spec 02 section 1 and the
  ``RawPosting`` rules of spec 01 section 1. They ignore unknown keys and refuse type coercion.
* ``Parsed*`` frozen dataclasses are what the rest of the engine consumes: trimmed values, empty
  strings mapped to ``None`` and the derived ``company_key`` / ``title_key`` / ``location_key``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .errors import EngineInputError
from .normalize import company_key, location_key, title_key, trim
from .timeutil import date_to_epoch, timestamp_to_epoch

SourceKind = Literal["greenhouse", "lever", "ashby", "csv", "manual"]
WorkMode = Literal["remote", "hybrid", "onsite", "unknown"]
SnapshotMode = Literal["full", "additive"]
DecisionKind = Literal["merge", "not_same"]

# Only the scheme is checked (spec 01 section 1: "only http:/https: schemes"). ASCII-only
# case-insensitivity so that e.g. U+017F (long s) cannot pose as the "s" of "https".
_HTTP_SCHEME: Final = re.compile(r"https?:", re.IGNORECASE | re.ASCII)


# ---------------------------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------------------------
class _StrictModel(BaseModel):
    """No type coercion and immutable, but unknown keys are ignored.

    ``analyze`` input is not an API request body (spec 03's ``extra="forbid"`` is about those):
    spec 02 section 1 forbids nothing, and the TypeScript engine ignores unknown properties, so
    this does too (``docs/spec/ambiguities/differential.md`` D-5). Typed callers cannot misspell
    a key; the API layer keeps its own ``extra="forbid"`` bodies.
    """

    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


def _trimmed(value: object) -> object:
    return trim(value) if isinstance(value, str) else value


def _trimmed_or_none(value: object) -> object:
    """Trim; an empty string for an optional field means null (spec 01 section 1)."""
    if isinstance(value, str):
        return trim(value) or None
    return value


KEYWORD_MAX_COUNT: Final = 50
KEYWORD_MAX_CODE_POINTS: Final = 60


class ProfileIn(_StrictModel):
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)

    @field_validator("include_keywords", "exclude_keywords")
    @classmethod
    def _keyword_limits(cls, value: list[str]) -> list[str]:
        """Spec 03 profile limits (at most 50 keywords of at most 60 characters each).

        The same limits the TypeScript engine enforces, applied after trimming and counted in
        code points. Blank keywords are allowed (they never match). Spec 03 words these as the
        limits of ``PUT /api/profile`` but "profile" is one concept and the browser-only mode has
        no API, so both engines apply them (``docs/spec/ambiguities/differential.md`` D-9).
        """
        if len(value) > KEYWORD_MAX_COUNT:
            raise ValueError(f"at most {KEYWORD_MAX_COUNT} keywords are allowed")
        trimmed = [trim(keyword) for keyword in value]
        for keyword in trimmed:
            if len(keyword) > KEYWORD_MAX_CODE_POINTS:
                raise ValueError(f"a keyword may have at most {KEYWORD_MAX_CODE_POINTS} characters")
        return trimmed


class DecisionIn(_StrictModel):
    a_key: str
    b_key: str
    decision: DecisionKind

    @model_validator(mode="after")
    def _ordered_pair(self) -> DecisionIn:
        if not self.a_key < self.b_key:
            raise ValueError("a_key must sort strictly before b_key (code point order)")
        return self


class PostingIn(_StrictModel):
    """``RawPosting`` as it appears inside a snapshot (spec 01 section 1)."""

    # Redundant with the snapshot's own source; accepted when present, and must then agree.
    source_kind: SourceKind | None = None
    source_ref: str | None = None
    source_posting_id: str | None = None
    company_name: str
    title: str
    location: str | None = None
    work_mode: WorkMode | None = None
    department: str | None = None
    url: str | None = None
    posted_at: str | None = None

    @field_validator("company_name", "title", mode="before")
    @classmethod
    def _trim_required(cls, value: object) -> object:
        return _trimmed(value)

    @field_validator(
        "source_posting_id",
        "location",
        "department",
        "url",
        "posted_at",
        "work_mode",
        mode="before",
    )
    @classmethod
    def _trim_optional(cls, value: object) -> object:
        return _trimmed_or_none(value)

    @field_validator("source_ref", mode="before")
    @classmethod
    def _trim_source_ref(cls, value: object) -> object:
        # Trimmed but NOT mapped to null when empty: a posting-level source_ref that is present
        # is a RawPosting.source_ref ("1..200 after trim"), so "" is invalid, not "absent"
        # (docs/spec/ambiguities/differential.md D-10).
        return _trimmed(value)

    @field_validator("source_ref")
    @classmethod
    def _source_ref_length(cls, value: str | None) -> str | None:
        if value is not None and not 1 <= len(value) <= 200:
            raise ValueError("source_ref must be 1..200 characters after trimming")
        return value

    @field_validator("company_name")
    @classmethod
    def _company_name_length(cls, value: str) -> str:
        if not 1 <= len(value) <= 200:
            raise ValueError("company_name must be 1..200 characters after trimming")
        return value

    @field_validator("title")
    @classmethod
    def _title_length(cls, value: str) -> str:
        if not 1 <= len(value) <= 300:
            raise ValueError("title must be 1..300 characters after trimming")
        return value

    @field_validator("location")
    @classmethod
    def _location_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 300:
            raise ValueError("location must be at most 300 characters")
        return value

    @field_validator("department")
    @classmethod
    def _department_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 200:
            raise ValueError("department must be at most 200 characters")
        return value

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, value: str | None) -> str | None:
        if value is not None and _HTTP_SCHEME.match(value) is None:
            raise ValueError("url must use the http: or https: scheme")
        return value

    @field_validator("posted_at")
    @classmethod
    def _posted_at_is_a_date(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                date_to_epoch(value)
            except ValueError as exc:
                raise ValueError("posted_at must be a real YYYY-MM-DD date") from exc
        return value


class SnapshotIn(_StrictModel):
    snapshot_id: str
    source_kind: SourceKind
    source_ref: str
    observed_at: str
    mode: SnapshotMode
    postings: list[PostingIn] = Field(default_factory=list)

    @field_validator("snapshot_id")
    @classmethod
    def _snapshot_id_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("snapshot_id must not be empty")
        return value

    @field_validator("source_ref", mode="before")
    @classmethod
    def _trim_source_ref(cls, value: object) -> object:
        return _trimmed(value)

    @field_validator("source_ref")
    @classmethod
    def _source_ref_length(cls, value: str) -> str:
        if not 1 <= len(value) <= 200:
            raise ValueError("source_ref must be 1..200 characters after trimming")
        return value

    @field_validator("observed_at")
    @classmethod
    def _observed_at_is_a_timestamp(cls, value: str) -> str:
        try:
            timestamp_to_epoch(value)
        except ValueError as exc:
            raise ValueError("observed_at must be a real YYYY-MM-DDTHH:MM:SSZ instant") from exc
        return value

    @model_validator(mode="after")
    def _postings_agree_with_snapshot_source(self) -> SnapshotIn:
        for index, posting in enumerate(self.postings):
            if posting.source_kind is not None and posting.source_kind != self.source_kind:
                raise ValueError(
                    f"postings[{index}].source_kind {posting.source_kind!r} differs from the "
                    f"snapshot's source_kind {self.source_kind!r}"
                )
            if posting.source_ref is not None and posting.source_ref != self.source_ref:
                raise ValueError(
                    f"postings[{index}].source_ref {posting.source_ref!r} differs from the "
                    f"snapshot's source_ref {self.source_ref!r}"
                )
        return self


class AnalysisInput(_StrictModel):
    as_of: str
    profile: ProfileIn = Field(default_factory=ProfileIn)
    decisions: list[DecisionIn] = Field(default_factory=list)
    snapshots: list[SnapshotIn] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def _as_of_is_a_timestamp(cls, value: str) -> str:
        try:
            timestamp_to_epoch(value)
        except ValueError as exc:
            raise ValueError("as_of must be a real YYYY-MM-DDTHH:MM:SSZ instant") from exc
        return value

    @model_validator(mode="after")
    def _unique_snapshot_ids(self) -> AnalysisInput:
        seen: set[str] = set()
        for snapshot in self.snapshots:
            if snapshot.snapshot_id in seen:
                raise ValueError(f"duplicate snapshot_id {snapshot.snapshot_id!r}")
            seen.add(snapshot.snapshot_id)
        return self


# ---------------------------------------------------------------------------------------------
# Parsed (engine-facing) records
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ParsedPosting:
    source_posting_id: str | None
    company_name: str
    title: str
    location: str | None
    work_mode: str
    department: str | None
    url: str | None
    posted_at: str | None
    company_key: str
    title_key: str
    location_key: str


@dataclass(frozen=True, slots=True)
class ParsedSnapshot:
    snapshot_id: str
    source_kind: str
    source_ref: str
    observed_at: str
    observed_epoch: int
    mode: str
    postings: tuple[ParsedPosting, ...]


@dataclass(frozen=True, slots=True)
class ParsedDecision:
    a_key: str
    b_key: str
    decision: str


@dataclass(frozen=True, slots=True)
class ParsedInput:
    as_of: str
    as_of_epoch: int
    include_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...]
    decisions: tuple[ParsedDecision, ...]
    snapshots: tuple[ParsedSnapshot, ...]


def _parse_posting(posting: PostingIn) -> ParsedPosting:
    return ParsedPosting(
        source_posting_id=posting.source_posting_id,
        company_name=posting.company_name,
        title=posting.title,
        location=posting.location,
        work_mode=posting.work_mode or "unknown",
        department=posting.department,
        url=posting.url,
        posted_at=posting.posted_at,
        company_key=company_key(posting.company_name),
        title_key=title_key(posting.title),
        location_key=location_key(posting.location),
    )


def _describe(error: ValidationError) -> str:
    parts: list[str] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"]) or "<input>"
        parts.append(f"{location}: {item['msg']}")
    return "; ".join(parts)


def parse_input(raw: Mapping[str, Any]) -> ParsedInput:
    """Validate ``raw`` and return the normalized engine input.

    Raises :class:`EngineInputError` listing every violation found by the schema layer.
    """
    if not isinstance(raw, Mapping):
        raise EngineInputError(f"analyze input must be an object, got {type(raw).__name__}")
    try:
        model = AnalysisInput.model_validate(dict(raw))
    except ValidationError as exc:
        raise EngineInputError(f"invalid analyze input: {_describe(exc)}") from exc

    snapshots = tuple(
        ParsedSnapshot(
            snapshot_id=snapshot.snapshot_id,
            source_kind=snapshot.source_kind,
            source_ref=snapshot.source_ref,
            observed_at=snapshot.observed_at,
            observed_epoch=timestamp_to_epoch(snapshot.observed_at),
            mode=snapshot.mode,
            postings=tuple(_parse_posting(p) for p in snapshot.postings),
        )
        for snapshot in model.snapshots
    )
    return ParsedInput(
        as_of=model.as_of,
        as_of_epoch=timestamp_to_epoch(model.as_of),
        include_keywords=tuple(model.profile.include_keywords),
        exclude_keywords=tuple(model.profile.exclude_keywords),
        decisions=tuple(
            ParsedDecision(a_key=d.a_key, b_key=d.b_key, decision=d.decision)
            for d in model.decisions
        ),
        snapshots=snapshots,
    )
