from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.main import create_app
from app.models import AICapabilityProfile, AdminUser, AuditEvent, Base, PromptTemplate
from app.security.password import hash_password
from app.services import worker

_PASSWORD = "correct horse battery staple"
_API_KEY = "secret-admin-api-key"


def make_client(tmp_path: Path, **setting_overrides: object) -> tuple[TestClient, Engine]:
    """创建带管理员账号的集成测试客户端。"""
    database_url = f"sqlite:///{tmp_path / 'admin.db'}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AdminUser(username="admin", password_hash=hash_password(_PASSWORD)))
        session.commit()
    settings = Settings(
        database_url=database_url,
        session_secret="test-session-secret-at-least-32-bytes",
        secure_cookies=False,
        **setting_overrides,
    )
    return TestClient(create_app(settings=settings, engine=engine)), engine


def login(client: TestClient) -> dict[str, str]:
    """登录并返回管理写操作所需的 CSRF 请求头。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": _PASSWORD},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": client.cookies.get("spw_csrf") or ""}


def template_payload(name: str, system_prompt: str) -> dict[str, str]:
    """构造合法模板请求。"""
    return {
        "name": name,
        "system_prompt": system_prompt,
        "user_prompt_template": "用户提示词",
        "output_schema_json": '{"type":"object"}',
    }


def test_admin_routes_require_authentication(tmp_path: Path) -> None:
    """全部管理端点必须要求当前用户。"""
    client, _engine = make_client(tmp_path)

    for path in (
        "/api/v1/admin/prompt-templates",
        "/api/v1/admin/ai-capability",
        "/api/v1/admin/audit-events",
    ):
        response = client.get(path)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_prompt_template_versions_activation_and_audit(tmp_path: Path) -> None:
    """同名模板版本递增，且任意时刻只有一个模板活跃。"""
    client, engine = make_client(tmp_path)
    headers = login(client)

    first = client.post(
        "/api/v1/admin/prompt-templates",
        json=template_payload("默认模板", "系统提示词一"),
        headers=headers,
    )
    second = client.post(
        "/api/v1/admin/prompt-templates",
        json=template_payload("默认模板", "系统提示词二"),
        headers=headers,
    )
    invalid = client.post(
        "/api/v1/admin/prompt-templates",
        json={**template_payload("错误模板", "系统提示词"), "output_schema_json": "[]"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert invalid.status_code == 422
    assert first.json()["data"]["version"] == 1
    assert second.json()["data"]["version"] == 2
    assert len(first.json()["data"]["content_hash"]) == 64

    first_id = first.json()["data"]["id"]
    second_id = second.json()["data"]["id"]
    assert client.post(
        f"/api/v1/admin/prompt-templates/{first_id}/activate", headers=headers
    ).status_code == 200
    assert client.post(
        f"/api/v1/admin/prompt-templates/{second_id}/activate", headers=headers
    ).status_code == 200

    with Session(engine) as session:
        active_templates = session.scalars(
            select(PromptTemplate).where(PromptTemplate.is_active.is_(True))
        ).all()
        event_count = session.scalar(select(func.count()).select_from(AuditEvent))
    assert [template.id for template in active_templates] == [second_id]
    assert event_count == 4

    audit_response = client.get("/api/v1/admin/audit-events?limit=2")
    assert audit_response.status_code == 200
    assert len(audit_response.json()["data"]) == 2
    assert audit_response.json()["data"][0]["event_type"] == "PROMPT_TEMPLATE_ACTIVATED"


def test_worker_prefers_active_prompt_template(tmp_path: Path, monkeypatch) -> None:
    """Worker 有活跃数据库模板时不得读取规则文件。"""
    _client, engine = make_client(tmp_path)
    with Session(engine) as session:
        session.add(
            PromptTemplate(
                name="Worker 模板",
                version=1,
                system_prompt="数据库系统提示词",
                user_prompt_template="数据库用户提示词",
                output_schema_json="{}",
                content_hash="a" * 64,
                is_active=True,
            )
        )
        session.commit()

        def reject_file_fallback(*_args: object, **_kwargs: object) -> tuple[str, str]:
            """禁止测试意外进入文件回退分支。"""
            raise AssertionError("不应读取规则文件")

        monkeypatch.setattr(worker, "load_skill_prompts", reject_file_fallback)
        assert worker.resolve_job_prompts(session) == (
            "数据库系统提示词",
            "数据库用户提示词",
        )


@respx.mock
def test_ai_capability_response_is_redacted_and_audited(tmp_path: Path) -> None:
    """能力查询和测试响应、持久化内容均不得包含 API key。"""
    client, engine = make_client(
        tmp_path,
        ai_base_url="https://api.example.com/v1?private=value",
        ai_api_key=_API_KEY,
        ai_model="vision-model",
    )
    headers = login(client)
    route = respx.get("https://api.example.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    get_response = client.get("/api/v1/admin/ai-capability")
    test_response = client.post("/api/v1/admin/ai-capability/test", headers=headers)

    assert get_response.status_code == 200
    assert get_response.json()["data"] == {
        "provider": "openai-compatible",
        "base_url": "https://api.example.com/v1",
        "model": "vision-model",
        "chat_path": "/chat/completions",
        "timeout_seconds": 240,
        "api_key_configured": True,
        "configured": True,
        "source": "environment",
    }
    assert test_response.status_code == 200
    assert test_response.json()["data"]["status"] == "AVAILABLE"
    assert route.called
    assert _API_KEY not in json.dumps(get_response.json())
    assert _API_KEY not in json.dumps(test_response.json())

    with Session(engine) as session:
        profile = session.scalar(select(AICapabilityProfile))
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "AI_CAPABILITY_TESTED")
        )
    assert profile is not None
    assert audit_event is not None
    assert _API_KEY not in profile.details_json
    assert _API_KEY not in profile.base_url_normalized
    assert _API_KEY not in audit_event.details_json
