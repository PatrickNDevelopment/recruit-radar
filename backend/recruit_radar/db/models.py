"""SQLAlchemy 2 typed models (spec 03, "Persistence").

Everything the engine needs is stored as plain observations; the Analysis is always derived by
replaying them (no derived tables). Timestamps are the fixed ``YYYY-MM-DDTHH:MM:SSZ`` text of
the spec so that they sort correctly as strings.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_VERSION = 1

SOURCE_KINDS = ("greenhouse", "lever", "ashby", "csv", "manual")
SNAPSHOT_MODES = ("full", "additive")
RUN_STATUSES = ("ok", "failed")
ERROR_KINDS = (
    "not_found",
    "unauthorized",
    "rate_limited",
    "server_error",
    "network",
    "timeout",
    "malformed",
    "too_large",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    """Declarative base; ``Base.metadata`` is what the Alembic migration is checked against."""


class Meta(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class Source(Base):
    """A watched ATS board: one (provider, token) pair with the user's company name."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("provider", "token", name="uq_sources_provider_token"),
        CheckConstraint(
            _in("provider", ("greenhouse", "lever", "ashby")), name="ck_sources_provider"
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    token: Mapped[str] = mapped_column(String(100), nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[str] = mapped_column(String(20), nullable=False)


class Snapshot(Base):
    """One observation event of one source: an ATS refresh, a CSV import or a manual entry."""

    __tablename__ = "snapshots"
    __table_args__ = (
        CheckConstraint(_in("source_kind", SOURCE_KINDS), name="ck_snapshots_source_kind"),
        CheckConstraint(_in("mode", SNAPSHOT_MODES), name="ck_snapshots_mode"),
        Index("ix_snapshots_source", "source_kind", "source_ref"),
        Index("ix_snapshots_observed_at", "observed_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    observed_at: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    dataset_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[str] = mapped_column(String(20), nullable=False)

    @property
    def snapshot_id(self) -> str:
        """The id the engine sees. Zero padded so that string order is creation order."""
        return snapshot_id_for(self.id)


def snapshot_id_for(row_id: int) -> str:
    return f"s_{row_id:08d}"


class PostingObservation(Base):
    """One posting inside one snapshot, in listed order (``position``)."""

    __tablename__ = "posting_observations"
    __table_args__ = (
        Index("ix_posting_observations_snapshot", "snapshot_id", "position"),
        CheckConstraint(
            _in("work_mode", ("remote", "hybrid", "onsite", "unknown")), name="ck_work_mode"
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_posting_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    work_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    company_key: Mapped[str] = mapped_column(Text, nullable=False)
    title_key: Mapped[str] = mapped_column(Text, nullable=False)
    location_key: Mapped[str] = mapped_column(Text, nullable=False)


class RefreshRun(Base):
    """One attempt to refresh a source; stored whether it succeeded or failed."""

    __tablename__ = "refresh_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_refresh_runs_status"),
        CheckConstraint(
            "error_kind IS NULL OR " + _in("error_kind", ERROR_KINDS),
            name="ck_refresh_runs_error_kind",
        ),
        Index("ix_refresh_runs_source", "source_id", "id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[str] = mapped_column(String(20), nullable=False)
    finished_at: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    error_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_after_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reappeared: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL"), nullable=True
    )


class MergeDecision(Base):
    __tablename__ = "merge_decisions"
    __table_args__ = (
        UniqueConstraint("a_key", "b_key", name="uq_merge_decisions_pair"),
        CheckConstraint(_in("decision", ("merge", "not_same")), name="ck_merge_decisions_decision"),
        CheckConstraint("a_key < b_key", name="ck_merge_decisions_order"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    a_key: Mapped[str] = mapped_column(Text, nullable=False)
    b_key: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[str] = mapped_column(String(20), nullable=False)


class ShortlistEntry(Base):
    """A company the user shortlisted and/or wrote a qualification note for."""

    __tablename__ = "shortlist"
    __table_args__ = (CheckConstraint("length(note) <= 2000", name="ck_shortlist_note_length"),)

    company_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    # Canonical company key when the entry was written; lets an entry follow its company when a
    # merge decision changes which key (and therefore which company_id) is canonical.
    company_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    shortlisted: Mapped[bool] = mapped_column(nullable=False, default=False)
    added_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(20), nullable=False)


class Profile(Base):
    """The single role-keyword profile (row id is always 1)."""

    __tablename__ = "profile"
    __table_args__ = (CheckConstraint("id = 1", name="ck_profile_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    include_keywords: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    exclude_keywords: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    updated_at: Mapped[str] = mapped_column(String(20), nullable=False)
