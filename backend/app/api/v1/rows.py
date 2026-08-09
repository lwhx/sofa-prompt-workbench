from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select

from app.dependencies import CurrentUser, DatabaseSession
from app.enums import JobStatus, RowStatus
from app.errors import AppError, success
from app.models import Asset, AutoRunIntent, Job, PromptResult, PromptRow
from app.services.auto_run import upsert_auto_run_intent


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
            select(func.count(PromptResult.id)).where(
                PromptResult.row_id == row.id,
                PromptResult.hidden_at.is_(None),
            )
        ) or 0
    job_started: datetime | None = None
    job_completed: datetime | None = None
    if jobs_map is not None:
        job_times = jobs_map.get(row.id)
        if job_times:
            job_started, job_completed = job_times
    normalized_job_started = _ensure_utc(job_started)
    normalized_job_completed = _ensure_utc(job_completed)
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status.value if isinstance(row.status, RowStatus) else str(row.status),
        "row_revision": row.row_revision,
        "results_count": results_count,
        "selected_result_id": row.selected_result_id,
        "sort_key": row.sort_key,
        "auto_run": row.auto_run,
        "scene_asset_id": row.scene_asset_id,
        "sofa_asset_id": row.sofa_asset_id,
        "scene_asset": _asset_summary(scene),
        "sofa_asset": _asset_summary(sofa),
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        "job_started_at": normalized_job_started.isoformat() if normalized_job_started else None,
        "job_completed_at": (
            normalized_job_completed.isoformat() if normalized_job_completed else None
        ),
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


def _build_rows_query(
    *,
    search: str | None,
    status: list[str] | None,
    include_deleted: bool,
    only_deleted: bool,
) -> Select[tuple[PromptRow]]:
    """构建任务行筛选查询。"""
    stmt = select(PromptRow)
    if only_deleted:
        stmt = stmt.where(PromptRow.deleted_at.is_not(None))
    elif not include_deleted:
        stmt = stmt.where(PromptRow.deleted_at.is_(None))
    normalized_search = search.strip() if search else ""
    if normalized_search:
        escaped_search = (
            normalized_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_search}%"
        stmt = stmt.where(
            or_(
                PromptRow.name.ilike(pattern, escape="\\"),
                PromptRow.id.ilike(pattern, escape="\\"),
            )
        )
    if status:
        normalized_statuses = {item.strip().upper() for item in status if item.strip()}
        if normalized_statuses:
            stmt = stmt.where(PromptRow.status.in_(normalized_statuses))
    return stmt.order_by(PromptRow.sort_key)


def _load_rows(
    db: DatabaseSession,
    *,
    search: str | None,
    status: list[str] | None,
    include_deleted: bool,
    only_deleted: bool,
) -> list[dict[str, object]]:
    """按筛选条件批量加载任务行及其关联摘要。"""
    stmt = _build_rows_query(
        search=search,
        status=status,
        include_deleted=include_deleted,
        only_deleted=only_deleted,
    )
    rows = db.scalars(stmt).all()
    if not rows:
        return []

    row_ids = [row.id for row in rows]
    asset_ids = {
        asset_id
        for row in rows
        for asset_id in (row.scene_asset_id, row.sofa_asset_id)
        if asset_id
    }
    assets_map = {
        asset.id: asset
        for asset in db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))
    } if asset_ids else {}
    counts_map = {
        str(row_id): count
        for row_id, count in db.execute(
            select(PromptResult.row_id, func.count(PromptResult.id))
            .where(
                PromptResult.row_id.in_(row_ids),
                PromptResult.hidden_at.is_(None),
            )
            .group_by(PromptResult.row_id)
        )
    }
    jobs_map: dict[str, tuple[datetime | None, datetime | None]] = {}
    for row_id, created_at, completed_at in db.execute(
        select(Job.row_id, Job.created_at, Job.completed_at)
        .where(Job.row_id.in_(row_ids))
        .order_by(Job.row_id, Job.created_at.desc())
    ):
        normalized_row_id = str(row_id)
        if normalized_row_id not in jobs_map:
            jobs_map[normalized_row_id] = (created_at, completed_at)
    return [_row_to_dict(row, db, assets_map, counts_map, jobs_map) for row in rows]


def _safe_csv_value(value: object) -> str:
    """将导出值转换为可安全打开的 CSV 文本。"""
    if value is None:
        return ""
    text_value = str(value)
    return f"'{text_value}" if text_value.startswith(("=", "+", "-", "@")) else text_value


def _rows_to_csv(rows: list[dict[str, object]]) -> bytes:
    """将任务行列表编码为带 UTF-8 BOM 的 CSV。"""
    output = io.StringIO(newline="")
    field_names = [
        "id", "name", "status", "row_revision", "results_count", "sort_key",
        "scene_asset_id", "sofa_asset_id", "selected_result_id", "error_message",
        "created_at", "deleted_at", "job_started_at", "job_completed_at",
    ]
    writer = csv.DictWriter(output, fieldnames=field_names, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _safe_csv_value(row.get(field)) for field in field_names})
    return output.getvalue().encode("utf-8-sig")


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
    only_deleted: bool = Query(default=False),
    search: str | None = Query(default=None, max_length=200),
    status: Annotated[list[str] | None, Query()] = None,
) -> dict[str, object]:
    rows = _load_rows(
        db,
        search=search,
        status=status,
        include_deleted=include_deleted,
        only_deleted=only_deleted,
    )
    return success(rows, meta={"total": len(rows)})


@router.get("/export")
def export_rows(
    db: DatabaseSession,
    _user: CurrentUser,
    format: Literal["json", "csv"] = Query(default="json"),
    include_deleted: bool = Query(default=False),
    only_deleted: bool = Query(default=False),
    search: str | None = Query(default=None, max_length=200),
    status: Annotated[list[str] | None, Query()] = None,
) -> StreamingResponse:
    """按当前筛选条件导出任务行。"""
    rows = _load_rows(
        db,
        search=search,
        status=status,
        include_deleted=include_deleted,
        only_deleted=only_deleted,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    filename = quote(f"任务数据-{timestamp}.{format}")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    if format == "csv":
        return StreamingResponse(
            iter([_rows_to_csv(rows)]),
            media_type="text/csv; charset=utf-8",
            headers=headers,
        )
    payload = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        iter([payload]),
        media_type="application/json; charset=utf-8",
        headers=headers,
    )


@router.patch("/{row_id}")
def patch_row(
    row_id: str,
    payload: PatchRowRequest,
    request: Request,
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
    upsert_auto_run_intent(
        db,
        row,
        debounce_seconds=request.app.state.settings.auto_run_debounce_seconds,
    )
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


@router.post("/{row_id}/restore")
def restore_row(
    row_id: str,
    db: DatabaseSession,
    _user: CurrentUser,
    expected_revision: int = Query(ge=1),
) -> dict[str, object]:
    """从回收站恢复软删除的任务行。"""
    row = db.get(PromptRow, row_id)
    if row is None or row.deleted_at is None:
        raise AppError("TRASHED_ROW_NOT_FOUND", "回收站中不存在该任务", status_code=404)
    if row.row_revision != expected_revision:
        raise AppError("ROW_REVISION_CONFLICT", "该行已被修改，请刷新后重试", status_code=409)
    active_job = db.scalar(
        select(Job)
        .where(
            Job.row_id == row.id,
            Job.status.in_(
                (
                    JobStatus.PENDING_DISPATCH,
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                    JobStatus.VALIDATING,
                    JobStatus.REPAIRING,
                    JobStatus.CANCEL_REQUESTED,
                )
            ),
        )
        .order_by(Job.created_at.desc())
    )
    row.deleted_at = None
    row.row_revision += 1
    row.updated_at = datetime.now(UTC)
    row.active_job_id = active_job.id if active_job is not None else None
    row.status = RowStatus.CANCELING if active_job is not None else _compute_row_status(row)
    row.error_message = None
    db.commit()
    db.refresh(row)
    return success(_row_to_dict(row, db))
