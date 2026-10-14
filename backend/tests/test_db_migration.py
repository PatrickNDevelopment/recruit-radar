"""Alembic migration 0001 and the SQLite connection policy."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from recruit_radar.db import Base, create_db_engine
from recruit_radar.db.migrate import downgrade, upgrade
from recruit_radar.db.models import Meta, RefreshRun, Snapshot, Source

EXPECTED_TABLES = {
    "meta",
    "sources",
    "snapshots",
    "posting_observations",
    "refresh_runs",
    "merge_decisions",
    "shortlist",
    "profile",
}


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(tmp_path / "migration.sqlite3")
    yield engine
    engine.dispose()


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_from_an_empty_database_creates_the_schema(engine: Engine) -> None:
    assert _tables(engine) == set()
    upgrade(engine)
    assert _tables(engine) == EXPECTED_TABLES | {"alembic_version"}
    with Session(engine) as session:
        assert session.get(Meta, "schema_version") is not None
        assert session.get(Meta, "schema_version").value == "1"  # type: ignore[union-attr]
        version = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0001_initial"


def test_migration_and_orm_metadata_describe_the_same_schema(engine: Engine) -> None:
    upgrade(engine)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    assert differences == []


def test_downgrade_removes_every_table_and_upgrade_works_again(engine: Engine) -> None:
    upgrade(engine)
    downgrade(engine, "base")
    assert _tables(engine) <= {"alembic_version"}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 0
    upgrade(engine)
    assert _tables(engine) == EXPECTED_TABLES | {"alembic_version"}


def test_upgrade_is_idempotent(engine: Engine) -> None:
    upgrade(engine)
    upgrade(engine)  # a second start-up must be a no-op
    assert _tables(engine) == EXPECTED_TABLES | {"alembic_version"}


def test_indexes_exist(engine: Engine) -> None:
    upgrade(engine)
    inspector = inspect(engine)
    assert {i["name"] for i in inspector.get_indexes("snapshots")} >= {
        "ix_snapshots_source",
        "ix_snapshots_observed_at",
    }
    assert "ix_posting_observations_snapshot" in {
        i["name"] for i in inspector.get_indexes("posting_observations")
    }


def test_every_connection_gets_the_four_pragmas(engine: Engine) -> None:
    upgrade(engine)
    # Several checkouts, including a second connection held open at the same time.
    with engine.connect() as first, engine.connect() as second:
        for connection in (first, second):
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
            assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000
            assert connection.execute(text("PRAGMA synchronous")).scalar_one() == 1  # NORMAL


def test_foreign_keys_are_enforced(engine: Engine) -> None:
    upgrade(engine)
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO posting_observations (snapshot_id, position, company_name, title, "
                "work_mode, company_key, title_key, location_key) "
                "VALUES (999, 0, 'A', 'T', 'unknown', 'a', 't', '')"
            )
        )


def test_check_constraints_reject_impossible_values(engine: Engine) -> None:
    upgrade(engine)
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO snapshots (source_kind, source_ref, observed_at, mode, created_at) "
                "VALUES ('linkedin', 'x', '2026-01-01T00:00:00Z', 'full', '2026-01-01T00:00:00Z')"
            )
        )
    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO merge_decisions (a_key, b_key, decision, created_at) "
                "VALUES ('b', 'a', 'merge', '2026-01-01T00:00:00Z')"
            )
        )


def test_deleting_a_source_cascades_to_runs_snapshots_and_observations(engine: Engine) -> None:
    upgrade(engine)
    with Session(engine) as session:
        source = Source(
            provider="greenhouse",
            token="acme",
            company_name="Acme",
            created_at="2026-01-01T00:00:00Z",
        )
        session.add(source)
        session.flush()
        snapshot = Snapshot(
            source_id=source.id,
            source_kind="greenhouse",
            source_ref="acme",
            observed_at="2026-01-01T00:00:00Z",
            mode="full",
            created_at="2026-01-01T00:00:00Z",
        )
        session.add(snapshot)
        session.flush()
        session.execute(
            text(
                "INSERT INTO posting_observations (snapshot_id, position, company_name, title, "
                "work_mode, company_key, title_key, location_key) "
                "VALUES (:s, 0, 'Acme', 'Engineer', 'unknown', 'acme', 'engineer', '')"
            ),
            {"s": snapshot.id},
        )
        session.add(
            RefreshRun(
                source_id=source.id,
                started_at="2026-01-01T00:00:00Z",
                finished_at="2026-01-01T00:00:01Z",
                status="ok",
                snapshot_id=snapshot.id,
            )
        )
        session.commit()

        session.delete(source)
        session.commit()

        for table in ("sources", "snapshots", "posting_observations", "refresh_runs"):
            count = session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            assert count == 0, table
