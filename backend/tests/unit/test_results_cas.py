import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import create_database_engine
from app.enums import JobStatus, RowStatus
from app.models import Base, Job, PromptResult, PromptRow
from app.services.results import finalize_result_with_row_cas


def make_session(tmp_path: Path) -> Session:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'results.db'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_job(session: Session, row: PromptRow, *, revision: int, fingerprint: str) -> Job:
    job = Job(
        row_id=row.id,
        status=JobStatus.RUNNING,
        row_revision=revision,
        input_fingerprint=fingerprint,
        input_snapshot_json="{}",
    )
    session.add(job)
    session.commit()
    return job


def test_stale_job_keeps_history_without_updating_current_row(tmp_path: Path) -> None:
    with make_session(tmp_path) as session:
        row = PromptRow(
            sort_key=10,
            row_revision=2,
            input_fingerprint="new",
            status=RowStatus.DIRTY,
        )
        session.add(row)
        session.commit()
        job = make_job(session, row, revision=1, fingerprint="old")

        result = finalize_result_with_row_cas(
            session,
            job_id=job.id,
            payload={"positive_prompt": "旧提示词", "negative_prompt": "镜像"},
            source="ai",
            review_required=False,
        )

        assert result.is_stale is True
        assert row.status == RowStatus.DIRTY
        assert row.latest_result_id is None
        assert row.selected_result_id is None
        assert row.last_success_fingerprint is None
        assert session.get(PromptResult, result.id) is not None


def test_matching_job_updates_latest_and_first_selected(tmp_path: Path) -> None:
    with make_session(tmp_path) as session:
        row = PromptRow(
            sort_key=10,
            row_revision=1,
            input_fingerprint="current",
            status=RowStatus.ANALYZING,
        )
        session.add(row)
        session.commit()
        job = make_job(session, row, revision=1, fingerprint="current")
        row.active_job_id = job.id
        session.commit()

        result = finalize_result_with_row_cas(
            session,
            job_id=job.id,
            payload={"positive_prompt": "新提示词", "negative_prompt": "镜像"},
            source="ai",
            review_required=False,
        )

        assert result.is_stale is False
        assert row.latest_result_id == result.id
        assert row.selected_result_id == result.id
        assert row.status == RowStatus.COMPLETED
        assert row.active_job_id is None
        assert row.last_success_fingerprint == "current"


def test_validation_json_contains_review_and_warning_data(tmp_path: Path) -> None:
    with make_session(tmp_path) as session:
        row = PromptRow(
            sort_key=10,
            row_revision=1,
            input_fingerprint="current",
            status=RowStatus.ANALYZING,
        )
        session.add(row)
        session.commit()
        job = make_job(session, row, revision=1, fingerprint="current")

        result = finalize_result_with_row_cas(
            session,
            job_id=job.id,
            payload={
                "positive_prompt": "新提示词",
                "negative_prompt": "镜像",
                "review": {"required": True, "reasons": ["视角方向不确定"]},
                "warnings": ["场景参考图局部遮挡"],
            },
            source="ai",
            review_required=True,
        )

        assert json.loads(result.validation_json) == {
            "passed": False,
            "review_required": True,
            "review_reasons": ["视角方向不确定"],
            "warnings": ["场景参考图局部遮挡"],
        }


def test_terminal_cas_rejects_already_finished_job(tmp_path: Path) -> None:
    with make_session(tmp_path) as session:
        row = PromptRow(
            sort_key=10,
            row_revision=1,
            input_fingerprint="current",
            status=RowStatus.CANCELED,
        )
        session.add(row)
        session.commit()
        job = make_job(session, row, revision=1, fingerprint="current")
        job.status = JobStatus.CANCELED
        session.commit()

        with pytest.raises(RuntimeError, match="JOB_TERMINAL_CAS_CONFLICT"):
            finalize_result_with_row_cas(
                session,
                job_id=job.id,
                payload={"positive_prompt": "不应保存", "negative_prompt": "镜像"},
                source="ai",
                review_required=False,
            )

        assert session.scalar(
            select(PromptResult).where(PromptResult.job_id == job.id)
        ) is None


def test_terminal_cas_rejects_concurrent_cancel_request(tmp_path: Path) -> None:
    database_path = tmp_path / "cancel-race.db"
    engine = create_database_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as setup_session:
        row = PromptRow(
            sort_key=10,
            row_revision=1,
            input_fingerprint="current",
            status=RowStatus.CANCELING,
        )
        setup_session.add(row)
        setup_session.commit()
        job = make_job(setup_session, row, revision=1, fingerprint="current")
        row.active_job_id = job.id
        setup_session.commit()
        job_id = job.id

    with Session(engine) as worker_session, Session(engine) as cancel_session:
        worker_session.get(Job, job_id)
        cancel_job = cancel_session.get(Job, job_id)
        assert cancel_job is not None
        cancel_job.status = JobStatus.CANCEL_REQUESTED
        cancel_job.cancel_requested = True
        cancel_session.commit()

        with pytest.raises(RuntimeError, match="JOB_TERMINAL_CAS_CONFLICT"):
            finalize_result_with_row_cas(
                worker_session,
                job_id=job_id,
                payload={"positive_prompt": "不得覆盖取消", "negative_prompt": "镜像"},
                source="ai",
                review_required=False,
            )

    with Session(engine) as verification_session:
        assert verification_session.get(Job, job_id).status == JobStatus.CANCEL_REQUESTED  # type: ignore[union-attr]
        assert verification_session.scalar(
            select(PromptResult).where(PromptResult.job_id == job_id)
        ) is None
