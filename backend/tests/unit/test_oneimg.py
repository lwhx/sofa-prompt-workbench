import httpx
import pytest
import respx

from app.integrations.oneimg import OneImgClient, OneImgUploadError
from app.security.outbound import OutboundURLValidationError


@respx.mock
@pytest.mark.parametrize("thumbnail", [None, "/uploads/thumb.webp"])
def test_upload_uses_exact_contract_and_accepts_optional_thumbnail(thumbnail: str | None) -> None:
    route = respx.post("https://img.example.com/api/upload/images").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "files": [
                        {
                            "success": True,
                            "id": 7,
                            "url": "/uploads/image.webp",
                            "thumbnail_url": thumbnail,
                            "filename": "image.webp",
                            "file_size": 10,
                            "mime_type": "image/webp",
                            "width": 10,
                            "height": 10,
                            "unknown": "ignored",
                        }
                    ]
                },
            },
        )
    )
    client = OneImgClient("https://img.example.com", "secret-token")

    result = client.upload_image("sofa.png", b"bytes", "image/png")

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == "oneimg_token=secret-token"
    assert b'name="images[]"' in request.content
    assert result.public_url == "https://img.example.com/uploads/image.webp"
    assert result.thumbnail_url == (
        None if thumbnail is None else "https://img.example.com/uploads/thumb.webp"
    )


def test_protocol_relative_proxy_path_preserves_required_double_slash() -> None:
    with respx.mock:
        respx.post("https://img.example/api/upload/images").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "files": [
                            {
                                "success": True,
                                "id": 8,
                                "url": "//uploads/a.png",
                                "filename": "a.png",
                            }
                        ]
                    },
                },
            )
        )
        result = OneImgClient("https://img.example", "token").upload_image(
            "a.png", b"png", "image/png"
        )

    assert result.public_url == "https://img.example//uploads/a.png"


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 500, "data": None},
        {"code": 200, "data": {"files": []}},
        {"code": 200, "data": {"files": [{"success": False}]}},
    ],
)
@respx.mock
def test_http_200_business_failure_is_rejected(payload: dict[str, object]) -> None:
    respx.post("https://img.example.com/api/upload/images").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = OneImgClient("https://img.example.com", "secret-token")

    with pytest.raises(OneImgUploadError) as error:
        client.upload_image("sofa.png", b"bytes", "image/png")

    assert "secret-token" not in str(error.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://img.example.com",
        "https://user:password@img.example.com",
        "http://127.0.0.1",
        "http://169.254.169.254",
    ],
)
def test_client_rejects_unsafe_base_url(base_url: str) -> None:
    """OneImg 客户端初始化时必须执行统一 SSRF 校验。"""
    with pytest.raises(OutboundURLValidationError):
        OneImgClient(base_url, "secret-token")
