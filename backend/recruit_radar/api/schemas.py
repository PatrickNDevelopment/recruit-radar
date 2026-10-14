"""Request and response models of the HTTP API (spec 03).

Request bodies are strict and ``extra="forbid"`` (spec 03: "every request body is a Pydantic
model with ``extra="forbid"``"). Response models document the contract in OpenAPI and are
validated on the way out, so a service that returns the wrong shape fails a test instead of
shipping.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..adapters.base import ErrorKind
from ..services.csv_io import MAX_CSV_BYTES

Provider = Literal["greenhouse", "lever", "ashby"]
SourceKind = Literal["greenhouse", "lever", "ashby", "csv", "manual"]
WorkMode = Literal["remote", "hybrid", "onsite", "unknown"]
DecisionKind = Literal["merge", "not_same"]
RoleStatus = Literal["active", "removed"]
EventType = Literal["baseline", "added", "changed", "removed", "reappeared"]
TrackedField = Literal["title", "location", "work_mode", "department", "url", "posted_at"]
ComponentKey = Literal[
    "role_relevance", "volume", "change", "urgency", "source_confidence", "freshness"
]
ReasonCode = Literal[
    "no_active_roles", "no_keywords", "insufficient_history", "no_scope_roles", "no_dated_roles"
]
CandidateReason = Literal["spacing_variant", "token_overlap", "near_typo"]

TOKEN_PATTERN: Final = r"^[A-Za-z0-9_.-]{1,100}$"
MAX_NOTE: Final = 2000


class RequestModel(BaseModel):
    """Base of every request body: no unknown keys, no type coercion."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------------------------
class ErrorBody(ResponseModel):
    code: str = Field(description="Stable snake_case error code.")
    message: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(ResponseModel):
    """Every non-2xx answer: ``{"error": {"code", "message", "details"?}}``."""

    error: ErrorBody


# ---------------------------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------------------------
class ProfileBody(RequestModel):
    include_keywords: list[str] = Field(
        default_factory=list, description="At most 50 keywords of at most 60 characters."
    )
    exclude_keywords: list[str] = Field(
        default_factory=list, description="At most 50 keywords of at most 60 characters."
    )


class SourceBody(RequestModel):
    provider: Provider
    token: str = Field(
        pattern=TOKEN_PATTERN, description="Board token / site / board name (never a URL)."
    )
    company_name: str = Field(description="The company this board belongs to (1-200 characters).")


class CsvImportBody(RequestModel):
    dataset_label: str = Field(description="Becomes the source_ref of the import (1-200).")
    csv_text: str = Field(max_length=MAX_CSV_BYTES, description="UTF-8 CSV text, at most 1 MB.")
    observed_at: str | None = Field(
        default=None, description="YYYY-MM-DDTHH:MM:SSZ; blank means the import time."
    )


class PostingBody(RequestModel):
    dataset_label: str | None = Field(default=None, description="Free label; 1-200 characters.")
    observed_at: str | None = Field(
        default=None, description="YYYY-MM-DDTHH:MM:SSZ; blank means now."
    )
    source_posting_id: str | None = None
    company_name: str
    title: str
    location: str | None = None
    work_mode: str | None = Field(
        default=None, description="remote | hybrid | onsite | unknown (blank means unknown)."
    )
    department: str | None = None
    url: str | None = Field(default=None, description="Only http: and https: URLs.")
    posted_at: str | None = Field(default=None, description="YYYY-MM-DD")


class DecisionBody(RequestModel):
    a_key: str = Field(description="Company key; must sort strictly before b_key.")
    b_key: str
    decision: DecisionKind


class ShortlistBody(RequestModel):
    shortlisted: bool
    note: str | None = Field(
        default=None, max_length=MAX_NOTE, description="Omit to keep the stored note."
    )


# ---------------------------------------------------------------------------------------------
# Plain responses
# ---------------------------------------------------------------------------------------------
class HealthOut(ResponseModel):
    status: Literal["ok", "degraded"]
    app_version: str
    schema_version: int | None
    db_ok: bool


class ProfileOut(ResponseModel):
    include_keywords: list[str]
    exclude_keywords: list[str]


class RefreshRunOut(ResponseModel):
    id: int
    source_id: int
    started_at: str
    finished_at: str
    status: Literal["ok", "failed"]
    error_kind: ErrorKind | None
    http_status: int | None
    retry_after_s: int | None
    items_seen: int
    added: int
    changed: int
    removed: int
    reappeared: int
    unchanged: int
    message: str


class SourceOut(ResponseModel):
    id: int
    provider: Provider
    token: str
    company_name: str
    created_at: str
    base_host: str = Field(description="The host a refresh of this source contacts.")
    last_run: RefreshRunOut | None
    last_ok_at: str | None = Field(description="finished_at of the newest successful run.")
    runs_total: int


class RowErrorOut(ResponseModel):
    line: int = Field(description="1-based CSV line on which the record starts.")
    field: str | None
    message: str


class RowWarningOut(ResponseModel):
    line: int
    message: str


class ImportResultOut(ResponseModel):
    snapshot_id: str | None = Field(
        description="Id of the stored snapshot (the latest when rows carry several observed_at); "
        "null when no row was accepted."
    )
    dataset_label: str
    accepted: int
    rejected: int
    errors: list[RowErrorOut]
    warnings: list[RowWarningOut]


class StoredPostingOut(ResponseModel):
    source_posting_id: str | None
    company_name: str
    title: str
    location: str | None
    work_mode: WorkMode
    department: str | None
    url: str | None
    posted_at: str | None


class ManualPostingOut(ResponseModel):
    snapshot_id: str
    source_kind: Literal["manual"]
    source_ref: str
    dataset_label: str | None
    observed_at: str
    posting: StoredPostingOut


class MergeDecisionOut(ResponseModel):
    id: int
    a_key: str
    b_key: str
    decision: DecisionKind
    created_at: str


class ShortlistEntryOut(ResponseModel):
    company_id: str
    name: str
    note: str
    added_at: str


class ShortlistStateOut(ResponseModel):
    company_id: str
    shortlisted: bool
    name: str
    note: str
    added_at: str | None


# ---------------------------------------------------------------------------------------------
# Analysis (spec 02 section 5)
# ---------------------------------------------------------------------------------------------
class ComponentOut(ResponseModel):
    key: ComponentKey
    weight: int
    value: int | None
    reason_code: ReasonCode | None
    inputs: dict[str, int | None]


class CompanyOut(ResponseModel):
    company_id: str
    key: str
    name: str
    aliases: list[str]
    first_seen: str
    last_seen: str | None
    active_roles: int
    relevant_roles: int | None
    removed_roles: int
    score: int | None
    coverage: int
    rank: int | None
    components: list[ComponentOut]


class ObservationOut(ResponseModel):
    source_kind: SourceKind
    source_ref: str
    source_posting_id: str | None
    url: str | None
    status: RoleStatus
    first_seen: str
    last_seen: str


class RoleOut(ResponseModel):
    role_id: str
    company_id: str
    title: str
    location: str | None
    work_mode: WorkMode
    department: str | None
    posted_at: str | None
    status: RoleStatus
    first_seen: str
    last_seen: str
    removed_at: str | None
    relevant: bool | None
    age_days: int
    observations: list[ObservationOut]


class EventOut(ResponseModel):
    at: str
    type: EventType
    company_id: str
    role_id: str
    source_kind: SourceKind
    source_ref: str
    title: str
    fields: list[TrackedField] | None


class MergeCandidateOut(ResponseModel):
    candidate_id: str
    a_key: str
    b_key: str
    a_name: str
    b_name: str
    reason: CandidateReason


class StatsOut(ResponseModel):
    snapshots: int
    postings_observed: int
    companies: int
    active_roles: int


class AnalysisOut(ResponseModel):
    as_of: str
    companies: list[CompanyOut]
    roles: list[RoleOut]
    events: list[EventOut]
    merge_candidates: list[MergeCandidateOut]
    stats: StatsOut


class SourceFreshnessOut(ResponseModel):
    source_kind: SourceKind
    source_ref: str
    source_id: int | None = Field(description="The watched ATS source, when there is one.")
    active_roles: int
    removed_roles: int
    first_seen: str
    last_seen: str
    last_observed_at: str | None = Field(description="Newest snapshot of this source at as_of.")


class CompanyDetailOut(ResponseModel):
    as_of: str
    company: CompanyOut
    roles: list[RoleOut]
    events: list[EventOut]
    source_freshness: list[SourceFreshnessOut]
    shortlist: ShortlistStateOut
