import json
from pathlib import Path

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
