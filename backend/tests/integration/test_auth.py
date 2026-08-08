from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.main import create_app
from app.models import AdminUser, Base
from app.security.password import hash_password


def make_client(tmp_path: Path) -> TestClient:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            AdminUser(
                username="admin",
                password_hash=hash_password("correct horse battery staple"),
            )
        )
        session.commit()
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
        session_secret="test-session-secret-at-least-32-bytes",
        secure_cookies=False,
    )
    return TestClient(create_app(settings=settings, engine=engine))


def test_unauthenticated_api_uses_stable_chinese_error(tmp_path: Path) -> None:
    response = make_client(tmp_path).get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json() == {
        "data": None,
        "error": {"code": "AUTH_REQUIRED", "message": "请先登录", "details": {}},
    }


def test_login_sets_http_only_session_and_csrf_cookie(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"username": "admin"}
    assert "HttpOnly" in response.headers.get_list("set-cookie")[0]
    assert client.cookies.get("spw_session")
    assert client.cookies.get("spw_csrf")
    assert client.get("/api/v1/auth/me").json()["data"]["username"] == "admin"


def test_login_rejects_wrong_password_without_leaking_detail(tmp_path: Path) -> None:
    response = make_client(tmp_path).post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert "admin" not in response.json()["error"]["message"]


def test_mutation_requires_matching_csrf_token(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )

    missing = client.post("/api/v1/auth/logout")
    mismatch = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"})

    assert missing.status_code == 403
    assert mismatch.status_code == 403
    csrf = client.cookies.get("spw_csrf")
    success = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf or ""})
    assert success.status_code == 200
    assert not client.cookies.get("spw_session")


def test_business_mutation_requires_csrf(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )

    response = client.post("/api/v1/rows", json={"name": "不得创建"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_INVALID"
