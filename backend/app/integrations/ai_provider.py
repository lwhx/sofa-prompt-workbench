from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from app.domain.ai_schema import PromptResultPayload, normalize_provider_payload

logger = logging.getLogger(__name__)

# 可重试的 HTTP 状态码（服务端瞬时错误）
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0


class AIProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    parsed: PromptResultPayload
    provider_request_id: str | None
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    redacted_response: dict[str, Any]


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        chat_path: str = "chat/completions",
        timeout_seconds: float = 240,
    ) -> None:
        self.endpoint = urljoin(base_url.rstrip("/") + "/", chat_path.lstrip("/"))
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate_prompt(
        self,
        *,
        scene_data_url: str,
        sofa_data_url: str,
        system_prompt: str,
        user_prompt: str,
    ) -> ProviderResult:
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": scene_data_url}},
                        {"type": "image_url", "image_url": {"url": sofa_data_url}},
                    ],
                },
            ],
            "temperature": 0.2,
            "max_tokens": 8000,
            "response_format": {"type": "json_object"},
        }
        payload = self._post_with_retry(request_body)
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            raise AIProviderError("视觉模型未返回结果")
        choice = choices[0]
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        content = message.get("content", "") if isinstance(message, dict) else ""
        parsed = normalize_provider_payload(content)
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        request_id = payload.get("id") if isinstance(payload.get("id"), str) else None
        finish_reason = choice.get("finish_reason")
        finish_reason = finish_reason if isinstance(finish_reason, str) else None
        if finish_reason == "length":
            logger.warning(
                "视觉模型输出被截断 (finish_reason=length)，"
                "positive_prompt 可能不完整，建议提高 max_tokens 或缩减分析字段"
            )
        prompt_tokens = usage.get("prompt_tokens")
        prompt_tokens = prompt_tokens if isinstance(prompt_tokens, int) else None
        completion_tokens = usage.get("completion_tokens")
        completion_tokens = completion_tokens if isinstance(completion_tokens, int) else None
        total_tokens = usage.get("total_tokens")
        total_tokens = total_tokens if isinstance(total_tokens, int) else None
        return ProviderResult(
            parsed=parsed,
            provider_request_id=request_id,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            redacted_response={
                "id": payload.get("id"),
                "model": payload.get("model"),
                "finish_reason": choice.get("finish_reason"),
                "content": content,
                "usage": usage,
            },
        )

    def _post_with_retry(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """
        带指数退避重试的 HTTP POST。
        对 429/5xx 和网络超时错误最多重试 _MAX_RETRIES 次。
        @param request_body - 请求体。
        @return - 解析后的 JSON 响应。
        @raises AIProviderError - 所有重试耗尽后抛出，包含最终状态码和错误详情。
        """
        last_status: int | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = httpx.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=request_body,
                    timeout=self.timeout_seconds,
                )
                last_status = response.status_code
                if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "视觉模型返回 %d，%0.1fs 后重试 (attempt %d/%d)",
                        response.status_code, delay, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                # 不可重试状态码或重试耗尽：尝试提取错误详情
                if response.status_code >= 400:
                    detail = self._extract_error_detail(response)
                    raise AIProviderError(
                        f"视觉模型请求失败 (HTTP {response.status_code}): {detail}"
                    )
                return response.json()
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "视觉模型连接异常: %s，%0.1fs 后重试 (attempt %d/%d)",
                        type(exc).__name__, delay, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                raise AIProviderError(
                    f"视觉模型请求失败（连接异常，重试 {_MAX_RETRIES} 次后仍失败）"
                ) from exc
            except AIProviderError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                raise AIProviderError(f"视觉模型请求失败: {exc}") from exc
        raise AIProviderError(
            f"视觉模型请求失败（重试 {_MAX_RETRIES} 次后仍返回 HTTP {last_status}）"
        )

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        """从 AI 服务的错误响应中提取可读信息。"""
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    return str(error.get("message", body))
                if isinstance(error, str):
                    return error
                return str(body.get("message", body))
        except Exception:
            pass
        text = response.text[:200] if response.text else ""
        return text or "无详细信息"
