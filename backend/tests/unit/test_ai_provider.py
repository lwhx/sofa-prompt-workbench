import httpx
import pytest
import respx

from app.integrations.ai_provider import AIProviderError, OpenAICompatibleProvider


def create_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="https://api.example.com/v1",
        api_key="secret",
        model="vision-model",
    )


def generate(provider: OpenAICompatibleProvider):
    return provider.generate_prompt(
        scene_data_url="data:image/jpeg;base64,SCENE",
        sofa_data_url="data:image/png;base64,SOFA",
        system_prompt="system",
        user_prompt="user",
    )


@respx.mock
def test_provider_sends_two_images_in_scene_sofa_order() -> None:
    route = respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "req-1",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"positive_prompt":"现代客厅","negative_prompt":"镜像"}'
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )
    )
    provider = create_provider()

    result = generate(provider)

    request_json = route.calls.last.request.content.decode()
    assert request_json.index("SCENE") < request_json.index("SOFA")
    assert result.parsed.positive_prompt == "现代客厅"
    assert result.provider_request_id == "req-1"
    assert result.total_tokens == 15


@pytest.mark.parametrize(
    ("content", "finish_reason", "message"),
    [
        ("", "stop", "内容为空"),
        ("不是 JSON", "stop", "不是有效 JSON"),
        ('{"positive_prompt":"现代客厅"}', "stop", "缺少必需"),
        ('{"negative_prompt":"镜像"}', "stop", "缺少必需"),
        ('{"positive_prompt":"现代客厅","negative_prompt":"镜像"}', "length", "输出被截断"),
    ],
)
@respx.mock
def test_provider_rejects_invalid_ai_output(
    content: str, finish_reason: str, message: str
) -> None:
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": finish_reason, "message": {"content": content}}
                ]
            },
        )
    )

    with pytest.raises(AIProviderError, match=message):
        generate(create_provider())
