"""Initial schema: sources, snapshots, observations, runs, decisions, shortlist, profile, meta.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_SOURCE_KINDS = "'greenhouse', 'lever', 'ashby', 'csv', 'manual'"
_ERROR_KINDS = (
    "'not_found', 'unauthorized', 'rate_limited', 'server_error', "
    "'network', 'timeout', 'malformed', 'too_large'"
)


def upgrade() -> None:
    op.create_table(
        "meta",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("token", sa.String(100), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.String(20), nullable=False),
        sa.UniqueConstraint("provider", "token", name="uq_sources_provider_token"),
        sa.CheckConstraint(
            "provider IN ('greenhouse', 'lever', 'ashby')", name="ck_sources_provider"
        ),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_ref", sa.String(200), nullable=False),
        sa.Column("observed_at", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("dataset_label", sa.String(200), nullable=True),
        sa.Column("created_at", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"source_kind IN ({_SOURCE_KINDS})", name="ck_snapshots_source_kind"),
        sa.CheckConstraint("mode IN ('full', 'additive')", name="ck_snapshots_mode"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_snapshots_source", "snapshots", ["source_kind", "source_ref"])
    op.create_index("ix_snapshots_observed_at", "snapshots", ["observed_at"])

    op.create_table(
        "posting_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_posting_id", sa.Text(), nullable=True),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("location", sa.String(300), nullable=True),
        sa.Column("work_mode", sa.String(16), nullable=False),
        sa.Column("department", sa.String(200), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.String(10), nullable=True),
        sa.Column("company_key", sa.Text(), nullable=False),
        sa.Column("title_key", sa.Text(), nullable=False),
        sa.Column("location_key", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["snapshots.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "work_mode IN ('remote', 'hybrid', 'onsite', 'unknown')", name="ck_work_mode"
        ),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_posting_observations_snapshot", "posting_observations", ["snapshot_id", "position"]
    )

    op.create_table(
        "refresh_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.String(20), nullable=False),
        sa.Column("finished_at", sa.String(20), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("error_kind", sa.String(16), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("retry_after_s", sa.Integer(), nullable=True),
        sa.Column("items_seen", sa.Integer(), nullable=False),
        sa.Column("added", sa.Integer(), nullable=False),
        sa.Column("changed", sa.Integer(), nullable=False),
        sa.Column("removed", sa.Integer(), nullable=False),
        sa.Column("reappeared", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["snapshots.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('ok', 'failed')", name="ck_refresh_runs_status"),
        sa.CheckConstraint(
            f"error_kind IS NULL OR error_kind IN ({_ERROR_KINDS})",
            name="ck_refresh_runs_error_kind",
        ),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_refresh_runs_source", "refresh_runs", ["source_id", "id"])

    op.create_table(
        "merge_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("a_key", sa.Text(), nullable=False),
        sa.Column("b_key", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(20), nullable=False),
        sa.UniqueConstraint("a_key", "b_key", name="uq_merge_decisions_pair"),
        sa.CheckConstraint("decision IN ('merge', 'not_same')", name="ck_merge_decisions_decision"),
        sa.CheckConstraint("a_key < b_key", name="ck_merge_decisions_order"),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "shortlist",
        sa.Column("company_id", sa.String(16), primary_key=True),
        sa.Column("company_key", sa.Text(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("shortlisted", sa.Boolean(), nullable=False),
        sa.Column("added_at", sa.String(20), nullable=True),
        sa.Column("updated_at", sa.String(20), nullable=False),
        sa.CheckConstraint("length(note) <= 2000", name="ck_shortlist_note_length"),
    )

    op.create_table(
        "profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("include_keywords", sa.Text(), nullable=False),
        sa.Column("exclude_keywords", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(20), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_profile_singleton"),
    )

    op.execute(sa.text("INSERT INTO meta (key, value) VALUES ('schema_version', '1')"))


def downgrade() -> None:
    op.drop_table("profile")
    op.drop_table("shortlist")
    op.drop_table("merge_decisions")
    op.drop_index("ix_refresh_runs_source", table_name="refresh_runs")
    op.drop_table("refresh_runs")
    op.drop_index("ix_posting_observations_snapshot", table_name="posting_observations")
    op.drop_table("posting_observations")
    op.drop_index("ix_snapshots_observed_at", table_name="snapshots")
    op.drop_index("ix_snapshots_source", table_name="snapshots")
    op.drop_table("snapshots")
    op.drop_table("sources")
    op.drop_table("meta")
