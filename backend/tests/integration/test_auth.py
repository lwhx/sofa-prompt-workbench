from pathlib import Path

import fakeredis
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.main import create_app
from app.models import AdminUser, Base
from app.security.password import hash_password


def make_client(
    tmp_path: Path,
    *,
    settings_overrides: dict[str, object] | None = None,
    redis_client: object | None = None,
) -> TestClient:
    tmp_path.mkdir(parents=True, exist_ok=True)
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
    values: dict[str, object] = {
        "database_url": f"sqlite:///{tmp_path / 'auth.db'}",
        "session_secret": "test-session-secret-at-least-32-bytes",
        "secure_cookies": False,
    }
    values.update(settings_overrides or {})
    settings = Settings(**values)
    return TestClient(
        create_app(
            settings=settings,
            engine=engine,
            redis_client=redis_client or fakeredis.FakeRedis(),
        ),
        client=("127.0.0.1", 50000),
    )


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


def test_login_rate_limit_is_shared_in_redis(tmp_path: Path) -> None:
    """多个应用实例必须共享 Redis 登录限流状态。"""
    redis_client = fakeredis.FakeRedis()
    first = make_client(
        tmp_path / "first",
        settings_overrides={"login_rate_limit": 2},
        redis_client=redis_client,
    )
    second = make_client(
        tmp_path / "second",
        settings_overrides={"login_rate_limit": 2},
        redis_client=redis_client,
    )

    for client in (first, second):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 401
    limited = first.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


def test_untrusted_forwarded_for_cannot_bypass_rate_limit(tmp_path: Path) -> None:
    """非可信直连来源提供的转发头不得改变限流身份。"""
    client = make_client(tmp_path, settings_overrides={"login_rate_limit": 1})
    payload = {"username": "admin", "password": "wrong"}

    first = client.post(
        "/api/v1/auth/login",
        json=payload,
        headers={"X-Forwarded-For": "198.51.100.10"},
    )
    second = client.post(
        "/api/v1/auth/login",
        json=payload,
        headers={"X-Forwarded-For": "198.51.100.11"},
    )

    assert first.status_code == 401
    assert second.status_code == 429


def test_trusted_proxy_uses_forwarded_client_ip(tmp_path: Path) -> None:
    """可信代理链应按从右到左规则解析真实客户端地址。"""
    client = make_client(
        tmp_path,
        settings_overrides={"login_rate_limit": 1, "trusted_proxies": "127.0.0.1/32"},
    )
    payload = {"username": "admin", "password": "wrong"}

    first = client.post(
        "/api/v1/auth/login",
        json=payload,
        headers={"X-Forwarded-For": "198.51.100.10"},
    )
    second = client.post(
        "/api/v1/auth/login",
        json=payload,
        headers={"X-Forwarded-For": "198.51.100.11"},
    )

    assert first.status_code == 401
    assert second.status_code == 401


class UnavailableRedis:
    """模拟所有限流命令失败的 Redis。"""

    def eval(self, _script: str, _numkeys: int, *_arguments: object) -> object:
        """抛出连接错误以触发故障策略。"""
        raise ConnectionError("测试 Redis 不可用")


def test_redis_failure_only_degrades_in_development(tmp_path: Path) -> None:
    """开发环境可显式降级，关闭开关后必须安全拒绝登录。"""
    development = make_client(
        tmp_path / "development",
        settings_overrides={"login_rate_limit": 1},
        redis_client=UnavailableRedis(),
    )
    strict = make_client(
        tmp_path / "strict",
        settings_overrides={"login_rate_limit_development_fallback": False},
        redis_client=UnavailableRedis(),
    )

    degraded = development.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    unavailable = strict.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )

    assert degraded.status_code == 401
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


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
