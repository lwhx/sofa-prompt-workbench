from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import create_database_engine
from app.enums import JobStatus, RowStatus
from app.models import Base, Job, PromptRow

EXPECTED_TABLES = {
    "admin_users",
    "ai_capability_profiles",
    "app_settings",
    "assets",
    "audit_events",
    "auto_run_intents",
    "job_attempts",
    "job_dispatch_outbox",
    "jobs",
    "prompt_results",
    "prompt_rows",
    "prompt_templates",
}


def make_engine(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = create_database_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return engine


def test_sqlite_connections_apply_required_pragmas(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA synchronous")).scalar_one() == 1
        assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 30_000
        assert connection.execute(text("PRAGMA temp_store")).scalar_one() == 2


def test_schema_contains_all_durable_tables(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)

    assert set(inspect(engine).get_table_names()) >= EXPECTED_TABLES


def test_row_defaults_and_spaced_sort_key_are_durable(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        row = PromptRow(sort_key=10, name="A 款")
        session.add(row)
        session.commit()
        session.refresh(row)

        assert row.id
        assert row.row_revision == 1
        assert row.status == RowStatus.WAITING_IMAGES
        assert row.auto_run is True
        assert row.created_at.year >= 2026


def test_only_one_active_job_can_exist_per_row(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        row = PromptRow(sort_key=10, name="A 款")
        session.add(row)
        session.flush()
        session.add(
            Job(
                row_id=row.id,
                status=JobStatus.QUEUED,
                row_revision=1,
                input_fingerprint="first",
                input_snapshot_json="{}",
            )
        )
        session.commit()

        session.add(
            Job(
                row_id=row.id,
                status=JobStatus.RUNNING,
                row_revision=1,
                input_fingerprint="second",
                input_snapshot_json="{}",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    "terminal_status",
    [
        JobStatus.REVIEW_REQUIRED,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELED,
    ],
)
def test_terminal_job_does_not_block_new_active_job(
    tmp_path: Path, terminal_status: JobStatus
) -> None:
    engine = make_engine(tmp_path)
    with Session(engine) as session:
        row = PromptRow(sort_key=10, name="A 款")
        session.add(row)
        session.flush()
        session.add(
            Job(
                row_id=row.id,
                status=terminal_status,
                row_revision=1,
                input_fingerprint="done",
                input_snapshot_json="{}",
            )
        )
        session.commit()

        session.add(
            Job(
                row_id=row.id,
                status=JobStatus.PENDING_DISPATCH,
                row_revision=1,
                input_fingerprint="next",
                input_snapshot_json="{}",
            )
        )
        session.commit()
