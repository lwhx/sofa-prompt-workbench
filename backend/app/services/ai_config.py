from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AppSetting
from app.security.outbound import validate_outbound_url

_AI_CONFIGURATION_KEY = "ai_configuration"


@dataclass(frozen=True)
class AIConfiguration:
    """AI 服务运行配置。"""

    provider: str
    base_url: str | None
    api_key: str | None
    model: str | None
    chat_path: str
    timeout_seconds: float
    source: str

    @property
    def configured(self) -> bool:
        """判断必要的 AI 服务参数是否完整。"""
        return bool(self.base_url and self.api_key and self.model)


def normalize_base_url(value: str, *, allow_private_networks: bool = False) -> str:
    """校验并规范化 OpenAI 兼容服务地址。"""
    normalized = validate_outbound_url(
        value,
        allow_private_networks=allow_private_networks,
        strip_query=True,
    )
    return normalized.rstrip("/")


def normalize_chat_path(value: str) -> str:
    """校验并规范化 Chat Completions 路径。"""
    path = value.strip()
    if not path or "://" in path or "?" in path or "#" in path:
        raise ValueError("Chat Completions 路径格式无效")
    return f"/{path.lstrip('/')}"


def _fernet(settings: Settings) -> Fernet:
    """从服务端会话密钥派生配置加密密钥。"""
    digest = hashlib.sha256(settings.session_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _environment_configuration(settings: Settings) -> AIConfiguration:
    """从环境变量构造回退配置。"""
    return AIConfiguration(
        provider="openai-compatible",
        base_url=(
            normalize_base_url(
                settings.ai_base_url,
                allow_private_networks=settings.ssrf_allow_private_networks,
            )
            if settings.ai_base_url
            else None
        ),
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        chat_path=normalize_chat_path(settings.ai_chat_completions_path),
        timeout_seconds=settings.ai_timeout_seconds,
        source="environment",
    )


def load_ai_configuration(session: Session, settings: Settings) -> AIConfiguration:
    """优先读取数据库加密配置，不存在时回退环境变量。"""
    setting = session.get(AppSetting, _AI_CONFIGURATION_KEY)
    if setting is None:
        return _environment_configuration(settings)
    try:
        plaintext = _fernet(settings).decrypt(setting.value_json.encode("utf-8"))
        payload = json.loads(plaintext)
        if payload.get("disabled") is True:
            return AIConfiguration(
                provider="openai-compatible",
                base_url=None,
                api_key=None,
                model=None,
                chat_path="/chat/completions",
                timeout_seconds=240,
                source="database",
            )
        return AIConfiguration(
            provider=str(payload["provider"]),
            base_url=normalize_base_url(
                str(payload["base_url"]),
                allow_private_networks=settings.ssrf_allow_private_networks,
            ),
            api_key=str(payload["api_key"]),
            model=str(payload["model"]),
            chat_path=normalize_chat_path(str(payload["chat_path"])),
            timeout_seconds=float(payload["timeout_seconds"]),
            source="database",
        )
    except (InvalidToken, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("已保存的 AI 配置无法解密或格式无效") from exc


def save_ai_configuration(
    session: Session,
    settings: Settings,
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    chat_path: str,
    timeout_seconds: float,
) -> AIConfiguration:
    """加密保存 AI 配置，API Key 为空时保留现有密钥。"""
    current = load_ai_configuration(session, settings)
    resolved_api_key = api_key.strip() if api_key and api_key.strip() else current.api_key
    configuration = AIConfiguration(
        provider="openai-compatible",
        base_url=normalize_base_url(
            base_url,
            allow_private_networks=settings.ssrf_allow_private_networks,
        ),
        api_key=resolved_api_key,
        model=model.strip(),
        chat_path=normalize_chat_path(chat_path),
        timeout_seconds=timeout_seconds,
        source="database",
    )
    payload = json.dumps(
        {
            "provider": configuration.provider,
            "base_url": configuration.base_url,
            "api_key": configuration.api_key,
            "model": configuration.model,
            "chat_path": configuration.chat_path,
            "timeout_seconds": configuration.timeout_seconds,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    encrypted_value = _fernet(settings).encrypt(payload.encode("utf-8")).decode("utf-8")
    setting = session.get(AppSetting, _AI_CONFIGURATION_KEY)
    if setting is None:
        setting = AppSetting(key=_AI_CONFIGURATION_KEY, value_json=encrypted_value, encrypted=True)
        session.add(setting)
    else:
        setting.value_json = encrypted_value
        setting.encrypted = True
        setting.updated_at = datetime.now(UTC)
    return configuration


def delete_ai_configuration(session: Session, settings: Settings) -> AIConfiguration:
    """保存禁用标记以清空数据库配置，并阻止继续回退环境变量。"""
    payload = json.dumps(
        {"disabled": True},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    encrypted_value = _fernet(settings).encrypt(payload.encode("utf-8")).decode("utf-8")
    setting = session.get(AppSetting, _AI_CONFIGURATION_KEY)
    if setting is None:
        setting = AppSetting(key=_AI_CONFIGURATION_KEY, value_json=encrypted_value, encrypted=True)
        session.add(setting)
    else:
        setting.value_json = encrypted_value
        setting.encrypted = True
        setting.updated_at = datetime.now(UTC)
    return AIConfiguration(
        provider="openai-compatible",
        base_url=None,
        api_key=None,
        model=None,
        chat_path="/chat/completions",
        timeout_seconds=240,
        source="database",
    )


def public_ai_configuration(configuration: AIConfiguration) -> dict[str, object]:
    """返回不暴露 API Key 的管理端配置。"""
    return {
        "provider": configuration.provider,
        "base_url": configuration.base_url,
        "model": configuration.model,
        "chat_path": configuration.chat_path,
        "timeout_seconds": configuration.timeout_seconds,
        "api_key_configured": bool(configuration.api_key),
        "configured": configuration.configured,
        "source": configuration.source,
    }
