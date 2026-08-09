import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.enums import JobStatus
from app.main import create_app
from app.models import (
    AdminUser,
    Asset,
    AuditEvent,
    Base,
    Job,
    JobDispatchOutbox,
    PromptResult,
    PromptRow,
    PromptTemplate,
)
from app.security.password import hash_password
from app.services.results import finalize_result_with_row_cas


def make_client(tmp_path: Path) -> tuple[TestClient, object]:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AdminUser(username="admin", password_hash=hash_password("pw")))
        session.commit()
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'jobs.db'}",
        session_secret="test-session-secret-at-least-32-bytes",
        secure_cookies=False,
    )
    client = TestClient(create_app(settings=settings, engine=engine))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    client.headers["X-CSRF-Token"] = client.cookies.get("spw_csrf") or ""
    return client, engine


def create_ready_row(engine: object) -> PromptRow:
    with Session(engine) as session:  # type: ignore[arg-type]
        scene = Asset(kind="scene_reference", status="READY", original_filename="scene.png")
        sofa = Asset(kind="sofa_product", status="READY", original_filename="sofa.png")
        session.add_all((scene, sofa))
        session.flush()
        row = PromptRow(
            sort_key=10,
            name="任务",
            status="READY",
            scene_asset_id=scene.id,
            sofa_asset_id=sofa.id,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def test_run_creates_job_and_outbox_atomically(tmp_path: Path) -> None:
    client, engine = make_client(tmp_path)
    row = create_ready_row(engine)

    response = client.post(
        f"/api/v1/rows/{row.id}/run",
        json={"expected_revision": 1, "force_regenerate": False},
    )

    assert response.status_code == 202
    job_id = response.json()["data"]["job_id"]
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.get(Job, job_id) is not None
        assert session.query(JobDispatchOutbox).filter_by(job_id=job_id).one()
        audit = session.query(AuditEvent).filter_by(event_type="JOB_RUN_REQUESTED").one()
        assert audit.row_id == row.id
        assert audit.job_id == job_id


def test_cancel_records_audit_in_same_transaction(tmp_path: Path) -> None:
    """取消任务时必须记录关联任务行与 Job 的审计事件。"""
    client, engine = make_client(tmp_path)
    row = create_ready_row(engine)
    run = client.post(
        f"/api/v1/rows/{row.id}/run",
        json={"expected_revision": 1, "force_regenerate": False},
    )

    response = client.post(
        f"/api/v1/rows/{row.id}/cancel",
        json={"expected_revision": 1},
    )

    assert response.status_code == 200
    with Session(engine) as session:  # type: ignore[arg-type]
        audit = session.query(AuditEvent).filter_by(event_type="JOB_CANCEL_REQUESTED").one()
        assert audit.row_id == row.id
        assert audit.job_id == run.json()["data"]["job_id"]


def test_repeated_run_returns_same_active_job(tmp_path: Path) -> None:
    client, engine = make_client(tmp_path)
    row = create_ready_row(engine)
    payload = {"expected_revision": 1, "force_regenerate": False}

    first = client.post(f"/api/v1/rows/{row.id}/run", json=payload)
    second = client.post(f"/api/v1/rows/{row.id}/run", json=payload)

    assert second.status_code == 202
    assert second.json()["data"]["job_id"] == first.json()["data"]["job_id"]


def test_run_freezes_ai_prompt_options_in_snapshot(tmp_path: Path) -> None:
    client, engine = make_client(tmp_path)
    row = create_ready_row(engine)
    view_override = {
        "view_type": "right_front_three_quarter",
        "near_end": "右端",
        "far_end": "左端",
        "camera_position": "右前方",
        "space_extension": "左后方",
    }
    with Session(engine) as session:  # type: ignore[arg-type]
        saved = session.get(PromptRow, row.id)
        assert saved is not None
        saved.custom_requirements = "保留落地灯并使用暖光"
        saved.include_person = True
        saved.view_override_enabled = True
        saved.view_override_json = json.dumps(view_override, ensure_ascii=False)
        session.commit()

    response = client.post(
        f"/api/v1/rows/{row.id}/run",
        json={"expected_revision": 1, "force_regenerate": False},
    )

    assert response.status_code == 202
    with Session(engine) as session:  # type: ignore[arg-type]
        job = session.get(Job, response.json()["data"]["job_id"])
        assert job is not None
        options = json.loads(job.input_snapshot_json)["row_options"]
        assert options == {
            "custom_requirements": "保留落地灯并使用暖光",
            "include_person": True,
            "view_override": view_override,
        }


def test_run_freezes_template_and_non_secret_ai_configuration(tmp_path: Path) -> None:
    client, engine = make_client(tmp_path)
    row = create_ready_row(engine)
    with Session(engine) as session:  # type: ignore[arg-type]
        session.add(
            PromptTemplate(
                name="生产模板",
                version=3,
                system_prompt="冻结系统提示词",
                user_prompt_template="冻结用户提示词",
                output_schema_json='{"type":"object"}',
                content_hash="template-hash-v3",
                is_active=True,
            )
        )
        session.commit()

    response = client.post(
        f"/api/v1/rows/{row.id}/run",
        json={"expected_revision": 1, "force_regenerate": False},
    )

    assert response.status_code == 202
    with Session(engine) as session:  # type: ignore[arg-type]
        job = session.get(Job, response.json()["data"]["job_id"])
        assert job is not None
        snapshot = json.loads(job.input_snapshot_json)
        assert snapshot["template"]["version"] == 3
        assert snapshot["template"]["system_prompt"] == "冻结系统提示词"
        assert snapshot["template"]["user_prompt_template"] == "冻结用户提示词"
        assert "api_key" not in snapshot["ai"]
        assert set(snapshot["ai"]) == {
            "provider",
            "base_url",
            "model",
            "chat_path",
            "timeout_seconds",
        }


def test_run_reuses_successful_result_with_same_fingerprint(tmp_path: Path) -> None:
    client, engine = make_client(tmp_path)
    row = create_ready_row(engine)
    payload = {"expected_revision": 1, "force_regenerate": False}
    first = client.post(f"/api/v1/rows/{row.id}/run", json=payload)
    job_id = first.json()["data"]["job_id"]
    with Session(engine) as session:  # type: ignore[arg-type]
        job = session.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.RUNNING
        session.commit()
        result = finalize_result_with_row_cas(
            session,
            job_id=job_id,
            payload={"positive_prompt": "可复用结果", "negative_prompt": "镜像"},
            source="ai",
            review_required=False,
        )
        result_id = result.id

    reused = client.post(f"/api/v1/rows/{row.id}/run", json=payload)

    assert reused.status_code == 200
    assert reused.json()["data"] == {
        "job_id": job_id,
        "result_id": result_id,
        "status": "REUSED",
    }
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.query(Job).filter_by(row_id=row.id).count() == 1
        assert session.query(PromptResult).filter_by(row_id=row.id).count() == 1
