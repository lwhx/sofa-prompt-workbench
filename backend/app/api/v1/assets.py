from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from sqlalchemy import or_, select

from app.dependencies import CurrentUser, DatabaseSession
from app.errors import AppError, success
from app.integrations.oneimg import OneImgUploadError
from app.models import Asset, PromptRow

router = APIRouter(prefix="/assets", tags=["图片资产"])

_VALID_KINDS = {"scene_reference", "sofa_product"}


@router.get("")
def list_assets(
    db: DatabaseSession,
    _user: CurrentUser,
    kind: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, object]:
    """列出已上传的图片资产，支持按类型筛选。"""
    stmt = (
        select(Asset)
        .where(Asset.status == "READY", Asset.deleted_at.is_(None))
        .order_by(Asset.created_at.desc())
        .limit(limit)
    )
    if kind:
        if kind not in _VALID_KINDS:
            raise AppError("INVALID_KIND", f"图片类型必须为 {sorted(_VALID_KINDS)}")
        stmt = stmt.where(Asset.kind == kind)
    assets = db.scalars(stmt).all()
    return success([
        {
            "id": a.id,
            "kind": a.kind,
            "original_filename": a.original_filename,
            "thumbnail_url": a.thumbnail_url,
            "public_url": a.public_url,
            "width": a.width,
            "height": a.height,
            "file_size": a.file_size,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in assets
    ])


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: str,
    db: DatabaseSession,
    _user: CurrentUser,
) -> dict[str, object]:
    """软删除未被有效任务行引用的图片资产。"""
    asset = db.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise AppError("ASSET_NOT_FOUND", "图片资产不存在", status_code=404)

    referenced_row = db.scalar(
        select(PromptRow.id).where(
            PromptRow.deleted_at.is_(None),
            or_(PromptRow.scene_asset_id == asset_id, PromptRow.sofa_asset_id == asset_id),
        )
    )
    if referenced_row is not None:
        raise AppError("ASSET_IN_USE", "图片资产正在被任务行使用", status_code=409)

    asset.deleted_at = datetime.now(UTC)
    db.commit()
    return success({"deleted": True})


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_image(content: bytes, max_pixels: int) -> tuple[int, int, str]:
    image = Image.open(io.BytesIO(content))
    width, height = image.size
    if width * height > max_pixels:
        raise ValueError("IMAGE_PIXELS_EXCEEDED")
    image.load()
    return width, height, image.format or ""


@router.post("/upload")
async def upload_asset(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form()],
    db: DatabaseSession = None,  # type: ignore[assignment]
    _user: CurrentUser = None,  # type: ignore[assignment]
) -> dict[str, object]:
    if kind not in _VALID_KINDS:
        raise AppError("INVALID_KIND", f"图片类型必须为 {sorted(_VALID_KINDS)}")

    max_bytes = request.app.state.settings.max_upload_bytes
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise AppError("IMAGE_TOO_LARGE", "图片体积超过限制")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise AppError("INVALID_IMAGE", "图片文件为空")

    try:
        image = await run_in_threadpool(
            _decode_image, content, request.app.state.settings.max_image_pixels
        )
    except ValueError as exc:
        if str(exc) == "IMAGE_PIXELS_EXCEEDED":
            raise AppError("IMAGE_TOO_LARGE", "图片像素超过限制") from exc
        raise
    except Image.DecompressionBombError as exc:
        raise AppError("IMAGE_TOO_LARGE", "图片像素超过限制") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise AppError("INVALID_IMAGE", "无法解析图片文件") from exc

    width, height, image_format = image

    mime_type = Image.MIME.get(image_format, "application/octet-stream")
    content_hash = _sha256(content)

    existing = db.scalar(
        select(Asset).where(
            Asset.sha256 == content_hash,
            Asset.kind == kind,
            Asset.status == "READY",
            Asset.deleted_at.is_(None),
        )
    )
    if existing is not None:
        response.status_code = 201
        return success(
            {
                "id": existing.id,
                "kind": existing.kind,
                "status": existing.status,
                "sha256": existing.sha256,
                "mime_type": existing.mime_type,
                "width": existing.width,
                "height": existing.height,
                "file_size": existing.file_size,
                "original_filename": existing.original_filename,
                "public_url": existing.public_url,
                "thumbnail_url": existing.thumbnail_url,
                "oneimg_image_id": existing.oneimg_image_id,
                "created_at": existing.created_at.isoformat() if existing.created_at else None,
            }
        )

    oneimg_client = request.app.state.oneimg_client
    remote = None
    if oneimg_client is not None:
        try:
            remote = await run_in_threadpool(
                oneimg_client.upload_image,
                file.filename or "upload",
                content,
                mime_type,
            )
        except OneImgUploadError as exc:
            raise AppError(
                "ONEIMG_UPLOAD_FAILED", "图床上传失败，请稍后重试", status_code=502
            ) from exc
    if remote is None and request.app.state.settings.app_env == "production":
        raise AppError("ONEIMG_NOT_CONFIGURED", "生产环境必须配置图床", status_code=503)
    asset = Asset(
        kind=kind,
        status="READY",
        original_filename=file.filename or "upload",
        mime_type=mime_type,
        file_size=len(content),
        width=width,
        height=height,
        sha256=content_hash,
        oneimg_image_id=remote.image_id if remote else None,
        stored_filename=remote.filename if remote else None,
        public_url=remote.public_url if remote else None,
        thumbnail_url=remote.thumbnail_url if remote else None,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    response.status_code = 201

    return success(
        {
            "id": asset.id,
            "kind": asset.kind,
            "status": asset.status,
            "sha256": asset.sha256,
            "mime_type": asset.mime_type,
            "width": asset.width,
            "height": asset.height,
            "file_size": asset.file_size,
            "original_filename": asset.original_filename,
            "public_url": asset.public_url,
            "thumbnail_url": asset.thumbnail_url,
            "oneimg_image_id": asset.oneimg_image_id,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
        }
    )
