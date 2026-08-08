from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.main import create_app
from app.models import AdminUser, Asset, Base
from app.security.password import hash_password


class FakeOneImgClient:
    def upload_image(self, filename: str, content: bytes, mime_type: str):  # type: ignore[no-untyped-def]
        from app.integrations.oneimg import OneImgUploadResult

        return OneImgUploadResult(
            image_id=42,
            public_url="https://img.example.com/uploads/image.webp",
            thumbnail_url=None,
            filename="image.webp",
            file_size=len(content),
            mime_type="image/webp",
            width=100,
            height=80,
            storage="default",
        )


def _make_test_image(color: tuple[int, int, int] = (200, 150, 100)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (100, 80), color).save(buffer, format="PNG")
    return buffer.getvalue()


def make_client(tmp_path: Path) -> TestClient:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'assets.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AdminUser(username="admin", password_hash=hash_password("pw")))
        session.commit()
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'assets.db'}",
        session_secret="test-session-secret-at-least-32-bytes",
        secure_cookies=False,
    )
    client = TestClient(create_app(settings=settings, engine=engine))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    client.headers["X-CSRF-Token"] = client.cookies.get("spw_csrf") or ""
    return client


def test_upload_scene_asset_creates_record(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.app.state.oneimg_client = FakeOneImgClient()
    image_bytes = _make_test_image()

    response = client.post(
        "/api/v1/assets/upload",
        files={"file": ("scene.png", image_bytes, "image/png")},
        data={"kind": "scene_reference"},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["kind"] == "scene_reference"
    assert data["status"] == "READY"
    assert data["sha256"]
    assert data["width"] == 100
    assert data["height"] == 80
    assert data["mime_type"] == "image/png"
    assert data["public_url"] == "https://img.example.com/uploads/image.webp"
    assert data["oneimg_image_id"] == 42


def test_upload_rejects_non_image(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/assets/upload",
        files={"file": ("bad.txt", b"not an image", "text/plain")},
        data={"kind": "scene_reference"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IMAGE"


def test_duplicate_image_reuses_existing_asset(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.app.state.oneimg_client = FakeOneImgClient()
    image_bytes = _make_test_image()

    first = client.post(
        "/api/v1/assets/upload",
        files={"file": ("scene.png", image_bytes, "image/png")},
        data={"kind": "scene_reference"},
    ).json()["data"]

    second = client.post(
        "/api/v1/assets/upload",
        files={"file": ("scene-copy.png", image_bytes, "image/png")},
        data={"kind": "scene_reference"},
    ).json()["data"]

    assert first["id"] == second["id"]
    assert first["sha256"] == second["sha256"]


def test_delete_unreferenced_asset_soft_deletes_record(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    asset = client.post(
        "/api/v1/assets/upload",
        files={"file": ("unused.png", _make_test_image(), "image/png")},
        data={"kind": "scene_reference"},
    ).json()["data"]

    response = client.delete(f"/api/v1/assets/{asset['id']}")

    assert response.status_code == 200
    assert response.json()["data"] == {"deleted": True}
    with Session(client.app.state.engine) as session:
        deleted = session.get(Asset, asset["id"])
        assert deleted is not None
        assert deleted.deleted_at is not None


def test_delete_referenced_asset_returns_409(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    row = client.post("/api/v1/rows", json={"name": "引用资产"}).json()["data"]
    asset = client.post(
        "/api/v1/assets/upload",
        files={"file": ("used.png", _make_test_image(), "image/png")},
        data={"kind": "scene_reference"},
    ).json()["data"]
    client.patch(
        f"/api/v1/rows/{row['id']}",
        json={"expected_revision": 1, "scene_asset_id": asset["id"]},
    )

    response = client.delete(f"/api/v1/assets/{asset['id']}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ASSET_IN_USE"


def test_delete_missing_asset_returns_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.delete("/api/v1/assets/missing-asset")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSET_NOT_FOUND"


def test_attach_asset_to_row_and_trigger_status_change(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    row = client.post("/api/v1/rows", json={"name": "产品"}).json()["data"]

    scene = client.post(
        "/api/v1/assets/upload",
        files={"file": ("s.png", _make_test_image((10, 20, 30)), "image/png")},
        data={"kind": "scene_reference"},
    ).json()["data"]
    sofa = client.post(
        "/api/v1/assets/upload",
        files={"file": ("p.png", _make_test_image((40, 50, 60)), "image/png")},
        data={"kind": "sofa_product"},
    ).json()["data"]

    rev1 = client.patch(
        f"/api/v1/rows/{row['id']}",
        json={"expected_revision": 1, "scene_asset_id": scene["id"]},
    )
    assert rev1.status_code == 200
    assert rev1.json()["data"]["status"] == "WAITING_IMAGES"

    rev2 = client.patch(
        f"/api/v1/rows/{row['id']}",
        json={"expected_revision": 2, "sofa_asset_id": sofa["id"]},
    )
    assert rev2.status_code == 200
    assert rev2.json()["data"]["status"] in ("READY", "DEBOUNCING")
