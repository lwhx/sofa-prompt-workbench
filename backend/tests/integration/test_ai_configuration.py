from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.main import create_app
from app.models import AdminUser, AppSetting, AuditEvent, Base
from app.security.password import hash_password
from app.services.ai_config import load_ai_configuration

_PASSWORD = "correct horse battery staple"
_SESSION_SECRET = "test-session-secret-at-least-32-bytes"


def make_client(tmp_path: Path) -> tuple[TestClient, Engine, Settings]:
    """创建 AI 配置集成测试客户端。"""
    database_url = f"sqlite:///{tmp_path / 'ai-configuration.db'}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AdminUser(username="admin", password_hash=hash_password(_PASSWORD)))
        session.commit()
    settings = Settings(
        database_url=database_url,
        session_secret=_SESSION_SECRET,
        secure_cookies=False,
    )
    return TestClient(create_app(settings=settings, engine=engine)), engine, settings


def login(client: TestClient) -> dict[str, str]:
    """登录并返回 CSRF 请求头。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": _PASSWORD},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": client.cookies.get("spw_csrf") or ""}


def configuration_payload(api_key: str | None) -> dict[str, object]:
    """构造 AI 配置更新请求。"""
    return {
        "provider": "openai-compatible",
        "base_url": "https://api.example.com/v1?secret=query",
        "api_key": api_key,
        "model": "vision-model",
        "chat_path": "/chat/completions",
        "timeout_seconds": 180,
    }


def test_ai_configuration_is_encrypted_redacted_and_audited(tmp_path: Path) -> None:
    """保存配置后密钥必须加密，查询和审计不得泄露明文。"""
    client, engine, settings = make_client(tmp_path)
    headers = login(client)

    response = client.put(
        "/api/v1/admin/ai-capability",
        json=configuration_payload("first-secret-key"),
        headers=headers,
    )
    query_response = client.get("/api/v1/admin/ai-capability")

    assert response.status_code == 200
    assert query_response.status_code == 200
    assert query_response.json()["data"] == {
        "provider": "openai-compatible",
        "base_url": "https://api.example.com/v1",
        "model": "vision-model",
        "chat_path": "/chat/completions",
        "timeout_seconds": 180.0,
        "api_key_configured": True,
        "configured": True,
        "source": "database",
    }
    assert "first-secret-key" not in json.dumps(response.json())
    assert "first-secret-key" not in json.dumps(query_response.json())

    with Session(engine) as session:
        stored = session.get(AppSetting, "ai_configuration")
        audit = session.query(AuditEvent).filter_by(event_type="AI_CONFIGURATION_UPDATED").one()
        configuration = load_ai_configuration(session, settings)
    assert stored is not None
    assert stored.encrypted is True
    assert "first-secret-key" not in stored.value_json
    assert "first-secret-key" not in audit.details_json
    assert configuration.api_key == "first-secret-key"


def test_blank_api_key_keeps_existing_secret(tmp_path: Path) -> None:
    """更新配置时留空 API Key 必须保留既有密钥。"""
    client, engine, settings = make_client(tmp_path)
    headers = login(client)
    assert client.put(
        "/api/v1/admin/ai-capability",
        json=configuration_payload("existing-secret-key"),
        headers=headers,
    ).status_code == 200

    updated_payload = configuration_payload(None)
    updated_payload["model"] = "new-vision-model"
    response = client.put(
        "/api/v1/admin/ai-capability",
        json=updated_payload,
        headers=headers,
    )

    assert response.status_code == 200
    with Session(engine) as session:
        configuration = load_ai_configuration(session, settings)
    assert configuration.api_key == "existing-secret-key"
    assert configuration.model == "new-vision-model"


def test_ai_configuration_rejects_credentialed_url(tmp_path: Path) -> None:
    """Base URL 不得携带可能泄露的用户名或密码。"""
    client, _engine, _settings = make_client(tmp_path)
    headers = login(client)
    payload = configuration_payload("secret-key")
    payload["base_url"] = "https://user:password@api.example.com/v1"

    response = client.put(
        "/api/v1/admin/ai-capability",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_CONFIGURATION_INVALID"
