from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import create_database_engine
from app.enums import JobStatus
from app.models import Base, Job, JobDispatchOutbox, PromptRow
from app.services.dispatch import create_job_and_outbox, dispatch_pending_outbox


def make_session(tmp_path: Path) -> Session:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'dispatch.db'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_job_and_outbox_are_created_in_one_transaction(tmp_path: Path) -> None:
    with make_session(tmp_path) as session:
        row = PromptRow(
            sort_key=10,
            name="A 款",
            row_revision=3,
            input_fingerprint="fingerprint-v3",
        )
        session.add(row)
        session.commit()

        job_id = create_job_and_outbox(
            session,
            row_id=row.id,
            expected_revision=3,
            input_fingerprint="fingerprint-v3",
            input_snapshot={"row_id": row.id, "row_revision": 3},
        )

        job = session.get(Job, job_id)
        outbox = session.scalar(select(JobDispatchOutbox).where(JobDispatchOutbox.job_id == job_id))
        assert job is not None
        assert job.status == JobStatus.PENDING_DISPATCH
        assert outbox is not None
        assert outbox.deterministic_rq_job_id == job_id
        assert row.active_job_id == job_id


def test_dispatch_is_idempotent_with_deterministic_job_id(tmp_path: Path) -> None:
    sent: list[str] = []

    def enqueue(job_id: str, queue_name: str) -> None:
        assert queue_name == "prompt-generation"
        if job_id not in sent:
            sent.append(job_id)

    with make_session(tmp_path) as session:
        row = PromptRow(
            sort_key=10,
            name="A 款",
            row_revision=1,
            input_fingerprint="same",
        )
        session.add(row)
        session.commit()
        job_id = create_job_and_outbox(
            session,
            row_id=row.id,
            expected_revision=1,
            input_fingerprint="same",
            input_snapshot={"row_id": row.id},
        )

        assert dispatch_pending_outbox(session, enqueue=enqueue) == 1
        assert dispatch_pending_outbox(session, enqueue=enqueue) == 0
        assert sent == [job_id]
        assert session.get(Job, job_id).status == JobStatus.QUEUED  # type: ignore[union-attr]


def test_expired_dispatching_lease_is_reclaimed(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    with make_session(tmp_path) as session:
        row = PromptRow(sort_key=10, name="lease", row_revision=1)
        session.add(row)
        session.commit()
        job_id = create_job_and_outbox(
            session,
            row_id=row.id,
            expected_revision=1,
            input_fingerprint="lease-fp",
            input_snapshot={"row_id": row.id},
        )
        entry = session.scalar(
            select(JobDispatchOutbox).where(JobDispatchOutbox.job_id == job_id)
        )
        assert entry is not None
        entry.status = "DISPATCHING"
        entry.updated_at = datetime.now(UTC) - timedelta(minutes=5)
        session.commit()
        sent: list[str] = []

        count = dispatch_pending_outbox(
            session, enqueue=lambda current_id, _queue: sent.append(current_id)
        )

        assert count == 1
        assert sent == [job_id]
