from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.dependencies import CurrentUser, DatabaseSession
from app.enums import JobStatus, RowStatus
from app.errors import AppError, success
from app.models import Asset, AutoRunIntent, Job, PromptResult, PromptRow


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """确保 datetime 带有时区信息，无时区时按 UTC 处理。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


router = APIRouter(prefix="/rows", tags=["任务行"])

_MAX_NAME_LENGTH = 200


class CreateRowRequest(BaseModel):
    name: str = Field(default="", max_length=_MAX_NAME_LENGTH)


class PatchRowRequest(BaseModel):
    name: str | None = Field(default=None, max_length=_MAX_NAME_LENGTH)
    scene_asset_id: str | None = None
    sofa_asset_id: str | None = None
    clear_scene_asset: bool = False
    clear_sofa_asset: bool = False
    expected_revision: int = Field(ge=1)



def _row_to_dict(
    row: PromptRow,
    db: DatabaseSession,
    assets_map: dict[str, Asset] | None = None,
    counts_map: dict[str, int] | None = None,
    jobs_map: dict[str, tuple[datetime | None, datetime | None]] | None = None,
) -> dict[str, object]:
    # 批量预加载模式下从 map 获取 Asset，否则回退到逐行查询
    if assets_map is not None:
        scene = assets_map.get(row.scene_asset_id) if row.scene_asset_id else None
        sofa = assets_map.get(row.sofa_asset_id) if row.sofa_asset_id else None
    else:
        scene = db.get(Asset, row.scene_asset_id) if row.scene_asset_id else None
        sofa = db.get(Asset, row.sofa_asset_id) if row.sofa_asset_id else None
    if counts_map is not None:
        results_count = counts_map.get(row.id, 0)
    else:
        results_count = db.scalar(
            select(func.count(PromptResult.id)).where(PromptResult.row_id == row.id)
        ) or 0
    job_started: datetime | None = None
    job_completed: datetime | None = None
    if jobs_map is not None:
        job_times = jobs_map.get(row.id)
        if job_times:
            job_started, job_completed = job_times
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status.value if isinstance(row.status, RowStatus) else str(row.status),
        "row_revision": row.row_revision,
        "results_count": results_count,
        "sort_key": row.sort_key,
        "auto_run": row.auto_run,
        "scene_asset_id": row.scene_asset_id,
        "sofa_asset_id": row.sofa_asset_id,
        "scene_asset": _asset_summary(scene),
        "sofa_asset": _asset_summary(sofa),
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "job_started_at": _ensure_utc(job_started).isoformat() if job_started else None,
        "job_completed_at": _ensure_utc(job_completed).isoformat() if job_completed else None,
    }


def _asset_summary(asset: Asset | None) -> dict[str, object] | None:
    if asset is None or asset.deleted_at is not None:
        return None
    return {
        "id": asset.id,
        "filename": asset.original_filename,
        "thumbnail_url": asset.thumbnail_url or asset.public_url,
        "public_url": asset.public_url,
        "width": asset.width,
        "height": asset.height,
        "mime_type": asset.mime_type,
    }


def _next_sort_key(db: DatabaseSession) -> int:
    max_key = db.scalar(select(func.coalesce(func.max(PromptRow.sort_key), 0)))
    return (max_key or 0) + 10


def _compute_row_status(row: PromptRow) -> RowStatus:
    has_scene = row.scene_asset_id is not None
    has_sofa = row.sofa_asset_id is not None
    if has_scene and has_sofa:
        return RowStatus.READY
    if not has_scene and not has_sofa:
        return RowStatus.WAITING_IMAGES
    return RowStatus.WAITING_IMAGES


def _require_asset(db: DatabaseSession, asset_id: str, expected_kind: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise AppError("ASSET_NOT_FOUND", "图片资产不存在", status_code=404)
    if asset.kind != expected_kind:
        raise AppError("ASSET_KIND_MISMATCH", "图片类型与目标栏位不匹配")
    if asset.status != "READY":
        raise AppError("ASSET_NOT_READY", "图片尚未处理完成")
    return asset


@router.post("")
def create_row(
    payload: CreateRowRequest,
    response: Response,
    db: DatabaseSession,
    _user: CurrentUser,
) -> dict[str, object]:
    row = PromptRow(
        sort_key=_next_sort_key(db),
        name=payload.name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    response.status_code = 201
    return success(_row_to_dict(row, db))


@router.get("")
def list_rows(
    db: DatabaseSession,
    _user: CurrentUser,
    include_deleted: bool = Query(default=False),
) -> dict[str, object]:
    stmt = select(PromptRow).order_by(PromptRow.sort_key)
    if not include_deleted:
        stmt = stmt.where(PromptRow.deleted_at.is_(None))
    rows = db.scalars(stmt).all()
    if not rows:
        return success([])

    # 批量预加载：消除 N+1 查询
    row_ids = [r.id for r in rows]
    asset_ids = {aid for r in rows for aid in (r.scene_asset_id, r.sofa_asset_id) if aid}
    assets_map: dict[str, Asset] = {}
    if asset_ids:
        for asset in db.scalars(select(Asset).where(Asset.id.in_(asset_ids))):
            assets_map[asset.id] = asset
    counts_map: dict[str, int] = {}
    for row_id, count in db.execute(
        select(PromptResult.row_id, func.count(PromptResult.id))
        .where(PromptResult.row_id.in_(row_ids))
        .group_by(PromptResult.row_id)
    ):
        counts_map[str(row_id)] = count

    # 批量预加载：每行最新 Job 的开始和完成时间
    jobs_map: dict[str, tuple[datetime | None, datetime | None]] = {}
    for row_id, created_at, completed_at in db.execute(
        select(Job.row_id, Job.created_at, Job.completed_at)
        .where(Job.row_id.in_(row_ids))
        .order_by(Job.row_id, Job.created_at.desc())
    ):
        rid = str(row_id)
        if rid not in jobs_map:
            jobs_map[rid] = (created_at, completed_at)

    return success([
        _row_to_dict(row, db, assets_map, counts_map, jobs_map)
        for row in rows
    ])


@router.patch("/{row_id}")
def patch_row(
    row_id: str,
    payload: PatchRowRequest,
    db: DatabaseSession,
    _user: CurrentUser,
) -> dict[str, object]:
    row = db.get(PromptRow, row_id)
    if row is None or row.deleted_at is not None:
        raise AppError("ROW_NOT_FOUND", "任务行不存在", status_code=404)
    if row.row_revision != payload.expected_revision:
        raise AppError("ROW_REVISION_CONFLICT", "该行已被修改，请刷新后重试", status_code=409)

    if payload.name is not None:
        row.name = payload.name
    if payload.scene_asset_id is not None:
        _require_asset(db, payload.scene_asset_id, "scene_reference")
        row.scene_asset_id = payload.scene_asset_id
    if payload.sofa_asset_id is not None:
        _require_asset(db, payload.sofa_asset_id, "sofa_product")
        row.sofa_asset_id = payload.sofa_asset_id
    if payload.clear_scene_asset:
        row.scene_asset_id = None
    if payload.clear_sofa_asset:
        row.sofa_asset_id = None
    row.row_revision += 1
    row.updated_at = datetime.now(UTC)
    row.status = _compute_row_status(row)
    db.commit()
    db.refresh(row)
    return success(_row_to_dict(row, db))


@router.delete("/{row_id}")
def delete_row(
    row_id: str,
    db: DatabaseSession,
    _user: CurrentUser,
    expected_revision: int = Query(ge=1),
) -> dict[str, object]:
    row = db.get(PromptRow, row_id)
    if row is None or row.deleted_at is not None:
        raise AppError("ROW_NOT_FOUND", "任务行不存在", status_code=404)
    if expected_revision and row.row_revision != expected_revision:
        raise AppError("ROW_REVISION_CONFLICT", "该行已被修改，请刷新后重试", status_code=409)

    row.deleted_at = datetime.now(UTC)
    row.row_revision += 1
    if row.active_job_id:
        job = db.get(Job, row.active_job_id)
        if job is not None and job.status in {
            JobStatus.PENDING_DISPATCH,
            JobStatus.QUEUED,
            JobStatus.RUNNING,
            JobStatus.VALIDATING,
            JobStatus.REPAIRING,
        }:
            job.cancel_requested = True
            job.status = JobStatus.CANCEL_REQUESTED
    intent = db.scalar(select(AutoRunIntent).where(AutoRunIntent.row_id == row.id))
    if intent is not None:
        intent.status = "CANCELED"
    row.active_job_id = None
    db.commit()
    return success({"deleted": True})
