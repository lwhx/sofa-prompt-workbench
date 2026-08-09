from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.enums import JobStatus
from app.main import create_app
from app.models import AdminUser, AutoRunIntent, Base, Job, PromptRow
from app.security.password import hash_password


def make_client(tmp_path: Path) -> TestClient:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'rows.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AdminUser(username="admin", password_hash=hash_password("test-password")))
        session.commit()
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'rows.db'}",
        session_secret="test-session-secret-at-least-32-bytes",
        secure_cookies=False,
    )
    client = TestClient(create_app(settings=settings, engine=engine))
    client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password"},
    )
    client.headers["X-CSRF-Token"] = client.cookies.get("spw_csrf") or ""
    return client


def test_create_row_and_list(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post("/api/v1/rows", json={"name": "A 款沙发"})
    assert response.status_code == 201
    created = response.json()["data"]
    assert created["name"] == "A 款沙发"
    assert created["status"] == "WAITING_IMAGES"
    assert created["row_revision"] == 1

    listed = client.get("/api/v1/rows")
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1


def test_edit_row_with_revision_cas_succeeds(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    row = client.post("/api/v1/rows", json={"name": "初始"}).json()["data"]

    response = client.patch(
        f"/api/v1/rows/{row['id']}",
        json={"name": "更新后", "expected_revision": 1},
    )
    assert response.status_code == 200
    updated = response.json()["data"]
    assert updated["name"] == "更新后"
    assert updated["row_revision"] == 2


def test_ready_row_edit_upserts_auto_run_intent_in_same_request(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    row = client.post("/api/v1/rows", json={"name": "自动运行"}).json()["data"]
    from app.models import Asset

    with Session(client.app.state.engine) as session:
        scene = Asset(
            kind="scene_reference",
            status="READY",
            original_filename="scene.png",
        )
        sofa = Asset(kind="sofa_product", status="READY", original_filename="sofa.png")
        session.add_all((scene, sofa))
        session.commit()
        scene_id = scene.id
        sofa_id = sofa.id

    response = client.patch(
        f"/api/v1/rows/{row['id']}",
        json={
            "expected_revision": 1,
            "scene_asset_id": scene_id,
            "sofa_asset_id": sofa_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "DEBOUNCING"
    with Session(client.app.state.engine) as session:
        intent = session.query(AutoRunIntent).filter_by(row_id=row["id"]).one()
        assert intent.expected_revision == 2
        assert intent.status == "PENDING"


def test_edit_row_with_stale_revision_returns_409(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    row = client.post("/api/v1/rows", json={"name": "初始"}).json()["data"]

    response = client.patch(
        f"/api/v1/rows/{row['id']}",
        json={"name": "冲突写入", "expected_revision": 99},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROW_REVISION_CONFLICT"


def test_patch_rejects_asset_with_wrong_kind(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    row = client.post("/api/v1/rows", json={"name": "初始"}).json()["data"]
    engine = client.app.state.engine
    from app.models import Asset

    with Session(engine) as session:
        sofa = Asset(
            kind="sofa_product",
            status="READY",
            original_filename="sofa.png",
        )
        session.add(sofa)
        session.commit()
        asset_id = sofa.id

    response = client.patch(
        f"/api/v1/rows/{row['id']}",
        json={"expected_revision": 1, "scene_asset_id": asset_id},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ASSET_KIND_MISMATCH"


def test_soft_delete_moves_row_out_of_default_list(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    row = client.post("/api/v1/rows", json={"name": "待删除"}).json()["data"]

    delete_response = client.delete(
        f"/api/v1/rows/{row['id']}?expected_revision=1",
    )
    assert delete_response.status_code == 200

    listed = client.get("/api/v1/rows")
    assert len(listed.json()["data"]) == 0

    trashed = client.get("/api/v1/rows?include_deleted=true")
    assert len(trashed.json()["data"]) == 1


def test_list_rows_supports_search_status_and_trash_filters(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    completed = client.post("/api/v1/rows", json={"name": "北欧云朵沙发"}).json()["data"]
    deleted = client.post("/api/v1/rows", json={"name": "复古皮沙发"}).json()["data"]
    client.post("/api/v1/rows", json={"name": "餐桌"})
    with Session(client.app.state.engine) as session:
        row = session.get(PromptRow, completed["id"])
        assert row is not None
        row.status = "COMPLETED"
        session.commit()
    client.delete(f"/api/v1/rows/{deleted['id']}?expected_revision=1")

    searched = client.get("/api/v1/rows", params={"search": "沙发", "status": "COMPLETED"})
    assert searched.status_code == 200
    assert [item["id"] for item in searched.json()["data"]] == [completed["id"]]
    assert searched.json()["meta"]["total"] == 1

    trashed = client.get("/api/v1/rows", params={"only_deleted": True, "search": "皮沙发"})
    assert trashed.status_code == 200
    assert [item["id"] for item in trashed.json()["data"]] == [deleted["id"]]
    assert trashed.json()["data"][0]["deleted_at"] is not None


def test_restore_soft_deleted_row_preserves_related_data(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    row = client.post("/api/v1/rows", json={"name": "可恢复任务"}).json()["data"]
    client.delete(f"/api/v1/rows/{row['id']}?expected_revision=1")

    response = client.post(f"/api/v1/rows/{row['id']}/restore?expected_revision=2")

    assert response.status_code == 200
    restored = response.json()["data"]
    assert restored["id"] == row["id"]
    assert restored["row_revision"] == 3
    assert restored["deleted_at"] is None
    listed_ids = [item["id"] for item in client.get("/api/v1/rows").json()["data"]]
    assert row["id"] in listed_ids


def test_restore_relinks_canceling_job_and_run_does_not_silently_reuse_it(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    row = client.post("/api/v1/rows", json={"name": "恢复并发任务"}).json()["data"]
    with Session(client.app.state.engine) as session:
        saved_row = session.get(PromptRow, row["id"])
        assert saved_row is not None
        job = Job(
            row_id=saved_row.id,
            status=JobStatus.RUNNING,
            row_revision=saved_row.row_revision,
            input_fingerprint="旧任务指纹",
            input_snapshot_json="{}",
        )
        session.add(job)
        session.flush()
        saved_row.active_job_id = job.id
        session.commit()
        job_id = job.id

    deleted = client.delete(f"/api/v1/rows/{row['id']}?expected_revision=1")
    restored = client.post(f"/api/v1/rows/{row['id']}/restore?expected_revision=2")

    assert deleted.status_code == 200
    assert restored.status_code == 200
    assert restored.json()["data"]["status"] == "CANCELING"
    with Session(client.app.state.engine) as session:
        saved_row = session.get(PromptRow, row["id"])
        saved_job = session.get(Job, job_id)
        assert saved_row is not None
        assert saved_job is not None
        assert saved_row.active_job_id == job_id
        assert saved_job.status == JobStatus.CANCEL_REQUESTED
        assert saved_job.cancel_requested is True


def test_export_rows_as_json_and_csv_uses_current_filters(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/api/v1/rows", json={"name": "导出沙发"})
    client.post("/api/v1/rows", json={"name": "不应导出的餐桌"})

    json_response = client.get("/api/v1/rows/export", params={"format": "json", "search": "沙发"})
    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert json_response.json()[0]["name"] == "导出沙发"
    assert "%E4%BB%BB%E5%8A%A1%E6%95%B0%E6%8D%AE-" in json_response.headers[
        "content-disposition"
    ]

    csv_response = client.get("/api/v1/rows/export", params={"format": "csv", "search": "沙发"})
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    csv_text = csv_response.content.decode("utf-8-sig")
    assert "导出沙发" in csv_text
    assert "不应导出的餐桌" not in csv_text
