from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.main import create_app
from app.models import AdminUser, Base
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
