from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.main import create_app
from app.models import AdminUser, Asset, Base, Job, JobDispatchOutbox, PromptRow
from app.security.password import hash_password


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


def test_repeated_run_returns_same_active_job(tmp_path: Path) -> None:
    client, engine = make_client(tmp_path)
    row = create_ready_row(engine)
    payload = {"expected_revision": 1, "force_regenerate": False}

    first = client.post(f"/api/v1/rows/{row.id}/run", json=payload)
    second = client.post(f"/api/v1/rows/{row.id}/run", json=payload)

    assert second.status_code == 202
    assert second.json()["data"]["job_id"] == first.json()["data"]["job_id"]