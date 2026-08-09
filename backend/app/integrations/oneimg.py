from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.security.outbound import request_outbound, validate_outbound_url


class OneImgUploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class OneImgUploadResult:
    image_id: int | None
    public_url: str
    thumbnail_url: str | None
    filename: str
    file_size: int | None
    mime_type: str | None
    width: int | None
    height: int | None
    storage: str | None


class OneImgClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 120,
        allow_private_networks: bool = False,
    ) -> None:
        self.allow_private_networks = allow_private_networks
        self.base_url = validate_outbound_url(
            base_url,
            allow_private_networks=allow_private_networks,
            strip_query=True,
        ).rstrip("/") + "/"
        self.token = token
        self.timeout_seconds = timeout_seconds

    def upload_image(self, filename: str, content: bytes, mime_type: str) -> OneImgUploadResult:
        try:
            response = request_outbound(
                "POST",
                urljoin(self.base_url, "api/upload/images"),
                allow_private_networks=self.allow_private_networks,
                headers={"Authorization": f"oneimg_token={self.token}"},
                files={"images[]": (filename, content, mime_type)},
                timeout=self.timeout_seconds,
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OneImgUploadError("OneImg 请求失败") from exc
        item = self._successful_item(response, payload)
        return OneImgUploadResult(
            image_id=item.get("id") if isinstance(item.get("id"), int) else None,
            public_url=self._public_url(str(item["url"])),
            thumbnail_url=(
                self._public_url(str(item["thumbnail_url"]))
                if item.get("thumbnail_url")
                else None
            ),
            filename=str(item.get("filename", filename)),
            file_size=item.get("file_size") if isinstance(item.get("file_size"), int) else None,
            mime_type=item.get("mime_type") if isinstance(item.get("mime_type"), str) else None,
            width=item.get("width") if isinstance(item.get("width"), int) else None,
            height=item.get("height") if isinstance(item.get("height"), int) else None,
            storage=item.get("storage") if isinstance(item.get("storage"), str) else None,
        )

    def _public_url(self, path: str) -> str:
        if path.startswith("//"):
            origin = urlsplit(self.base_url)
            return f"{origin.scheme}://{origin.netloc}{path}"
        return urljoin(self.base_url, path)

    @staticmethod
    def _successful_item(response: httpx.Response, payload: Any) -> dict[str, Any]:
        if (
            response.status_code != 200
            or not isinstance(payload, dict)
            or payload.get("code") != 200
        ):
            raise OneImgUploadError("OneImg 业务返回失败")
        data = payload.get("data")
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, list) or not files or not isinstance(files[0], dict):
            raise OneImgUploadError("OneImg 未返回上传文件")
        item = files[0]
        if item.get("success") is not True or not item.get("url"):
            raise OneImgUploadError("OneImg 文件上传失败")
        return item
