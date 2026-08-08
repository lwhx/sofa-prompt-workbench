from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.dependencies import CurrentUser, DatabaseSession
from app.enums import JobStatus, RowStatus
from app.errors import AppError, success
from app.models import Asset, Job, PromptRow
from app.services.dispatch import create_job_and_outbox

router = APIRouter(tags=["Job 控制"])


class RunJobRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    force_regenerate: bool = False


class CancelJobRequest(BaseModel):
    expected_revision: int = Field(ge=1)


def _fingerprint(row: PromptRow, scene: Asset, sofa: Asset) -> str:
    payload = {
        "row_revision": row.row_revision,
        "scene": scene.sha256 or scene.id,
        "sofa": sofa.sha256 or sofa.id,
        "requirements": row.custom_requirements,
        "view_override": row.view_override_json,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


@router.post("/rows/{row_id}/run")
def run_row(
    row_id: str,
    payload: RunJobRequest,
    response: Response,
    db: DatabaseSession,
    _user: CurrentUser,
) -> dict[str, object]:
    row = db.get(PromptRow, row_id)
    if row is None or row.deleted_at is not None:
        raise AppError("ROW_NOT_FOUND", "任务行不存在", status_code=404)
    if row.row_revision != payload.expected_revision:
        raise AppError("ROW_REVISION_CONFLICT", "该行已被修改，请刷新后重试", status_code=409)
    if not row.scene_asset_id or not row.sofa_asset_id:
        raise AppError("ROW_NOT_READY", "参考图和沙发白底图尚未全部上传完成")
    scene = db.get(Asset, row.scene_asset_id)
    sofa = db.get(Asset, row.sofa_asset_id)
    if scene is None or sofa is None or scene.status != "READY" or sofa.status != "READY":
        raise AppError("ROW_NOT_READY", "图片资产尚未准备完成")

    if payload.force_regenerate and row.active_job_id is None:
        row.input_fingerprint = None
        row.status = RowStatus.READY
        row.error_message = None
        db.commit()
        db.refresh(row)

    fingerprint = _fingerprint(row, scene, sofa)
    snapshot: dict[str, object] = {
        "row_id": row.id,
        "row_revision": row.row_revision,
        "scene_asset": {"id": scene.id, "url": scene.public_url, "sha256": scene.sha256},
        "sofa_asset": {"id": sofa.id, "url": sofa.public_url, "sha256": sofa.sha256},
        "row_options": {
            "custom_requirements": row.custom_requirements,
            "include_person": row.include_person,
        },
    }
    try:
        job_id = create_job_and_outbox(
            db,
            row_id=row.id,
            expected_revision=row.row_revision,
            input_fingerprint=fingerprint,
            input_snapshot=snapshot,
            row_status_after_create=RowStatus.QUEUED,
        )
    except ValueError as exc:
        raise AppError(
            "ROW_REVISION_CONFLICT", "该行已被修改，请刷新后重试", status_code=409
        ) from exc

    response.status_code = 202
    return success({"job_id": job_id, "status": "PENDING_DISPATCH"})


@router.post("/rows/{row_id}/cancel")
def cancel_row_job(
    row_id: str,
    payload: CancelJobRequest,
    db: DatabaseSession,
    _user: CurrentUser,
) -> dict[str, object]:
    row = db.get(PromptRow, row_id)
    if row is None or row.deleted_at is not None:
        raise AppError("ROW_NOT_FOUND", "任务行不存在", status_code=404)
    if row.row_revision != payload.expected_revision:
        raise AppError("ROW_REVISION_CONFLICT", "该行已被修改，请刷新后重试", status_code=409)
    job = db.get(Job, row.active_job_id) if row.active_job_id else None
    if job is None or job.status not in {
        JobStatus.PENDING_DISPATCH,
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.VALIDATING,
        JobStatus.REPAIRING,
    }:
        raise AppError("NO_ACTIVE_JOB", "当前没有可取消的任务", status_code=409)
    job.cancel_requested = True
    if job.status in {JobStatus.PENDING_DISPATCH, JobStatus.QUEUED}:
        job.status = JobStatus.CANCELED
        job.completed_at = datetime.now(UTC)
        row.active_job_id = None
        row.status = RowStatus.CANCELED
    else:
        job.status = JobStatus.CANCEL_REQUESTED
        row.status = RowStatus.CANCELING
    db.commit()
    return success({"job_id": job.id, "status": job.status})
