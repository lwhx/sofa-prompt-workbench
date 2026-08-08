from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Annotated
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update

from app.config import Settings
from app.dependencies import CurrentUser, DatabaseSession, get_settings_from_request
from app.errors import AppError, success
from app.models import AICapabilityProfile, AuditEvent, PromptTemplate
from app.services.ai_config import (
    AIConfiguration,
    load_ai_configuration,
    public_ai_configuration,
    save_ai_configuration,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/admin", tags=["管理"])


class PromptTemplateCreate(BaseModel):
    """提示词模板新版本创建参数。"""

    name: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(min_length=1)
    user_prompt_template: str = Field(min_length=1)
    output_schema_json: str

    @field_validator("output_schema_json")
    @classmethod
    def validate_output_schema_json(cls, value: str) -> str:
        """验证并规范化 JSON object。"""
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("output_schema_json 必须是有效 JSON object") from exc
        if not isinstance(parsed, dict):
            raise ValueError("output_schema_json 必须是 JSON object")
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _template_data(template: PromptTemplate) -> dict[str, Any]:
    """序列化提示词模板。"""
    return {
        "id": template.id,
        "name": template.name,
        "version": template.version,
        "system_prompt": template.system_prompt,
        "user_prompt_template": template.user_prompt_template,
        "output_schema_json": template.output_schema_json,
        "content_hash": template.content_hash,
        "is_active": template.is_active,
        "created_at": template.created_at.isoformat(),
    }


class AIConfigurationUpdate(BaseModel):
    """AI 服务配置更新参数。"""

    provider: str = Field(default="openai-compatible", pattern="^openai-compatible$")
    base_url: str = Field(min_length=1, max_length=2000)
    api_key: str | None = Field(default=None, max_length=4000)
    model: str = Field(min_length=1, max_length=500)
    chat_path: str = Field(default="/chat/completions", min_length=1, max_length=1000)
    timeout_seconds: float = Field(default=240, ge=10, le=600)


def _load_ai_configuration(db: DatabaseSession, settings: Settings) -> AIConfiguration:
    """读取 AI 配置并把损坏配置转换为稳定业务错误。"""
    try:
        return load_ai_configuration(db, settings)
    except ValueError as exc:
        raise AppError("AI_CONFIGURATION_INVALID", str(exc), status_code=500) from exc


@router.get("/prompt-templates")
def list_prompt_templates(
    _user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any]:
    """按创建时间倒序返回提示词模板。"""
    templates = db.scalars(
        select(PromptTemplate).order_by(PromptTemplate.created_at.desc(), PromptTemplate.version.desc())
    ).all()
    return success([_template_data(template) for template in templates])


@router.post("/prompt-templates")
def create_prompt_template(
    payload: PromptTemplateCreate,
    user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any]:
    """为同名模板创建递增版本。"""
    version = (
        db.scalar(select(func.max(PromptTemplate.version)).where(PromptTemplate.name == payload.name))
        or 0
    ) + 1
    hash_payload = json.dumps(
        {
            "name": payload.name,
            "system_prompt": payload.system_prompt,
            "user_prompt_template": payload.user_prompt_template,
            "output_schema_json": payload.output_schema_json,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    template = PromptTemplate(
        name=payload.name,
        version=version,
        system_prompt=payload.system_prompt,
        user_prompt_template=payload.user_prompt_template,
        output_schema_json=payload.output_schema_json,
        content_hash=hashlib.sha256(hash_payload.encode("utf-8")).hexdigest(),
    )
    db.add(template)
    db.flush()
    record_audit(
        db,
        event_type="PROMPT_TEMPLATE_CREATED",
        actor_user_id=user.id,
        details={"template_id": template.id, "name": template.name, "version": template.version},
    )
    db.commit()
    return success(_template_data(template))


@router.post("/prompt-templates/{template_id}/activate")
def activate_prompt_template(
    template_id: str,
    user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any]:
    """在单事务中切换唯一活跃模板。"""
    template = db.get(PromptTemplate, template_id)
    if template is None:
        raise AppError("PROMPT_TEMPLATE_NOT_FOUND", "提示词模板不存在", status_code=404)
    db.execute(update(PromptTemplate).where(PromptTemplate.is_active.is_(True)).values(is_active=False))
    template.is_active = True
    record_audit(
        db,
        event_type="PROMPT_TEMPLATE_ACTIVATED",
        actor_user_id=user.id,
        details={"template_id": template.id, "name": template.name, "version": template.version},
    )
    db.commit()
    return success(_template_data(template))


@router.get("/ai-capability")
def get_ai_capability(
    _user: CurrentUser,
    db: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> dict[str, Any]:
    """返回当前已脱敏的 AI 能力配置。"""
    configuration = _load_ai_configuration(db, settings)
    return success(public_ai_configuration(configuration))


@router.put("/ai-capability")
def update_ai_capability(
    payload: AIConfigurationUpdate,
    user: CurrentUser,
    db: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> dict[str, Any]:
    """加密保存 AI 配置并立即供后续任务使用。"""
    try:
        configuration = save_ai_configuration(
            db,
            settings,
            base_url=payload.base_url,
            api_key=payload.api_key,
            model=payload.model,
            chat_path=payload.chat_path,
            timeout_seconds=payload.timeout_seconds,
        )
    except ValueError as exc:
        raise AppError("AI_CONFIGURATION_INVALID", str(exc), status_code=422) from exc
    record_audit(
        db,
        event_type="AI_CONFIGURATION_UPDATED",
        actor_user_id=user.id,
        details={
            "provider": configuration.provider,
            "base_url": configuration.base_url,
            "model": configuration.model,
            "chat_path": configuration.chat_path,
            "timeout_seconds": configuration.timeout_seconds,
            "api_key_updated": bool(payload.api_key and payload.api_key.strip()),
        },
    )
    db.commit()
    return success(public_ai_configuration(configuration))


@router.post("/ai-capability/test")
def test_ai_capability(
    user: CurrentUser,
    db: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> dict[str, Any]:
    """通过低成本 models 请求验证 AI 配置并记录结果。"""
    configuration = _load_ai_configuration(db, settings)
    capability = public_ai_configuration(configuration)
    status = "NOT_CONFIGURED"
    details: dict[str, Any] = {"message": "AI 配置不完整"}
    if configuration.configured:
        endpoint = urljoin(str(configuration.base_url).rstrip("/") + "/", "models")
        try:
            response = httpx.get(
                endpoint,
                headers={"Authorization": f"Bearer {configuration.api_key}"},
                timeout=min(configuration.timeout_seconds, 30.0),
            )
            status = "AVAILABLE" if response.is_success else "UNAVAILABLE"
            details = {"http_status": response.status_code}
        except httpx.HTTPError as exc:
            status = "UNAVAILABLE"
            details = {"error": type(exc).__name__}

    identity_source = json.dumps(
        {
            "base_url": capability["base_url"],
            "chat_path": configuration.chat_path,
            "model": configuration.model,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    identity_hash = hashlib.sha256(identity_source.encode("utf-8")).hexdigest()
    profile = db.scalar(
        select(AICapabilityProfile).where(AICapabilityProfile.identity_hash == identity_hash)
    )
    if profile is None:
        profile = AICapabilityProfile(
            identity_hash=identity_hash,
            base_url_normalized=str(capability["base_url"] or ""),
            chat_path=configuration.chat_path,
            model=configuration.model or "",
        )
        db.add(profile)
    profile.status = status
    profile.details_json = json.dumps(details, ensure_ascii=False, sort_keys=True)
    profile.updated_at = datetime.now(UTC)
    record_audit(
        db,
        event_type="AI_CAPABILITY_TESTED",
        actor_user_id=user.id,
        details={"status": status, **details},
    )
    db.commit()
    return success({**capability, "status": status, "details": details})


@router.get("/audit-events")
def list_audit_events(
    _user: CurrentUser,
    db: DatabaseSession,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """按时间倒序返回审计事件。"""
    events = db.scalars(
        select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    ).all()
    return success(
        [
            {
                "id": event.id,
                "event_type": event.event_type,
                "actor_user_id": event.actor_user_id,
                "row_id": event.row_id,
                "job_id": event.job_id,
                "details": json.loads(event.details_json),
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ]
    )
