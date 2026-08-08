import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.events import _event_fingerprint
from app.config import Settings
from app.database import create_database_engine
from app.enums import JobStatus, RowStatus
from app.main import create_app
from app.models import AdminUser, Base, Job, PromptResult, PromptRow
from app.security.password import hash_password


def test_sse_requires_authentication(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'events.db'}")
    Base.metadata.create_all(engine)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'events.db'}",
        session_secret="test-session-secret-at-least-32-bytes",
    )
    client = TestClient(create_app(settings=settings, engine=engine))

    response = client.get("/api/v1/events")

    assert response.status_code == 401


def test_sse_emits_initial_invalidation_event(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'events-auth.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AdminUser(username="admin", password_hash=hash_password("pw")))
        session.commit()
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'events-auth.db'}",
        session_secret="test-session-secret-at-least-32-bytes",
    )
    client = TestClient(create_app(settings=settings, engine=engine))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})

    with client.stream("GET", "/api/v1/events?once=true") as response:
        content = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "event: invalidate" in content
    assert '"scope":"rows"' in content


def _make_result(row: PromptRow, *, version: int) -> PromptResult:
    payload = {"positive_prompt": "测试提示词", "negative_prompt": "镜像"}
    return PromptResult(
        row_id=row.id,
        version=version,
        source="ai",
        schema_version=1,
        result_payload_json=json.dumps(payload, ensure_ascii=False),
        sofa_view_json="{}",
        sofa_product_json="{}",
        scene_observations_json="{}",
        composition_plan_json="{}",
        review_json="{}",
        positive_prompt=payload["positive_prompt"],
        negative_prompt=payload["negative_prompt"],
        warnings_json="[]",
        validation_json="{}",
        review_status="PASSED",
        row_revision=row.row_revision,
        input_fingerprint="fingerprint",
    )


def test_event_fingerprint_changes_with_row_job_and_result(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'event-fingerprint.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        row = PromptRow(sort_key=10, status=RowStatus.READY)
        session.add(row)
        session.commit()
        initial = _event_fingerprint(session)

        row.row_revision += 1
        row.status = RowStatus.QUEUED
        session.commit()
        row_changed = _event_fingerprint(session)
        assert row_changed != initial

        job = Job(
            row_id=row.id,
            status=JobStatus.RUNNING,
            row_revision=row.row_revision,
            input_fingerprint="fingerprint",
            input_snapshot_json="{}",
            progress_percent=10,
        )
        session.add(job)
        session.commit()
        job_added = _event_fingerprint(session)
        assert job_added != row_changed

        job.progress_percent = 50
        job.status = JobStatus.VALIDATING
        session.commit()
        job_changed = _event_fingerprint(session)
        assert job_changed != job_added

        result = _make_result(row, version=1)
        session.add(result)
        session.commit()
        result_added = _event_fingerprint(session)
        assert result_added != job_changed

        session.delete(result)
        session.commit()
        assert _event_fingerprint(session) != result_added


def test_event_fingerprint_ignores_soft_deleted_rows(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'event-visibility.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        row = PromptRow(sort_key=10, status=RowStatus.READY)
        session.add(row)
        session.commit()
        row.deleted_at = datetime.now(UTC)
        session.commit()
        hidden = _event_fingerprint(session)

        row.row_revision += 1
        row.status = RowStatus.FAILED
        session.add(_make_result(row, version=1))
        session.commit()

        assert _event_fingerprint(session) == hidden