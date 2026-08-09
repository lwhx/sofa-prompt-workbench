from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import CurrentUser, DatabaseSession
from app.enums import JobStatus, RowStatus
from app.errors import AppError, success
from app.models import Asset, Job, PromptResult, PromptRow, PromptTemplate
from app.services.ai_config import load_ai_configuration
from app.services.audit import record_audit
from app.services.dispatch import create_job_and_outbox
from app.services.worker import resolve_job_prompts

router = APIRouter(tags=["Job 控制"])


class RunJobRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    force_regenerate: bool = False


class CancelJobRequest(BaseModel):
    expected_revision: int = Field(ge=1)


def _fingerprint(
    row: PromptRow,
    scene: Asset,
    sofa: Asset,
    template_snapshot: dict[str, object],
    ai_snapshot: dict[str, object],
) -> str:
    payload = {
        "row_revision": row.row_revision,
        "scene": scene.sha256 or scene.id,
        "sofa": sofa.sha256 or sofa.id,
        "requirements": row.custom_requirements,
        "view_override": row.view_override_json,
        "include_person": row.include_person,
        "person_action": row.person_action,
        "output_platform": row.output_platform,
        "prompt_length": row.prompt_length,
        "camera_preference": row.camera_preference,
        "template": template_snapshot,
        "ai": ai_snapshot,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _snapshot_view_override(row: PromptRow) -> dict[str, object] | None:
    if not row.view_override_enabled or not row.view_override_json:
        return None
    try:
        value = json.loads(row.view_override_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


@router.post("/rows/{row_id}/run")
def run_row(
    row_id: str,
    payload: RunJobRequest,
    response: Response,
    request: Request,
    db: DatabaseSession,
    user: CurrentUser,
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

    try:
        configuration = load_ai_configuration(db, request.app.state.settings)
    except ValueError as exc:
        raise AppError("AI_CONFIGURATION_INVALID", "视觉模型配置无法读取") from exc
    active_template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.is_active.is_(True))
    )
    system_prompt, user_prompt = resolve_job_prompts(db)
    template_snapshot: dict[str, object] = {
        "id": active_template.id if active_template else None,
        "version": active_template.version if active_template else None,
        "content_hash": active_template.content_hash if active_template else None,
        "system_prompt": system_prompt,
        "user_prompt_template": user_prompt,
        "output_schema_json": active_template.output_schema_json if active_template else None,
    }
    ai_snapshot: dict[str, object] = {
        "provider": configuration.provider,
        "base_url": configuration.base_url,
        "model": configuration.model,
        "chat_path": configuration.chat_path,
        "timeout_seconds": configuration.timeout_seconds,
    }
    fingerprint = _fingerprint(row, scene, sofa, template_snapshot, ai_snapshot)
    if not payload.force_regenerate and row.active_job_id is None:
        reusable_result = db.scalar(
            select(PromptResult)
            .where(
                PromptResult.row_id == row.id,
                PromptResult.input_fingerprint == fingerprint,
                PromptResult.hidden_at.is_(None),
                PromptResult.is_stale.is_(False),
            )
            .order_by(PromptResult.version.desc())
        )
        if reusable_result is not None:
            row.latest_result_id = reusable_result.id
            if row.selected_result_id is None:
                row.selected_result_id = reusable_result.id
            row.last_success_fingerprint = fingerprint
            row.input_fingerprint = fingerprint
            row.status = (
                RowStatus.NEEDS_REVIEW
                if reusable_result.review_status == "NEEDS_REVIEW"
                else RowStatus.COMPLETED
            )
            row.dirty = False
            row.error_message = None
            record_audit(
                db,
                event_type="JOB_RUN_REUSED",
                actor_user_id=user.id,
                row_id=row.id,
                job_id=reusable_result.job_id,
                details={
                    "result_id": reusable_result.id,
                    "force_regenerate": payload.force_regenerate,
                    "row_revision": row.row_revision,
                },
            )
            db.commit()
            return success(
                {
                    "job_id": reusable_result.job_id,
                    "result_id": reusable_result.id,
                    "status": "REUSED",
                }
            )
    snapshot: dict[str, object] = {
        "row_id": row.id,
        "row_revision": row.row_revision,
        "scene_asset": {"id": scene.id, "url": scene.public_url, "sha256": scene.sha256},
        "sofa_asset": {"id": sofa.id, "url": sofa.public_url, "sha256": sofa.sha256},
        "row_options": {
            "custom_requirements": row.custom_requirements,
            "include_person": row.include_person,
            "view_override": _snapshot_view_override(row),
        },
        "template": template_snapshot,
        "ai": ai_snapshot,
        "force_regenerate": payload.force_regenerate,
    }
    try:
        job_id = create_job_and_outbox(
            db,
            row_id=row.id,
            expected_revision=row.row_revision,
            input_fingerprint=fingerprint,
            input_snapshot=snapshot,
            row_status_after_create=RowStatus.QUEUED,
            commit=False,
        )
    except ValueError as exc:
        if str(exc) == "ACTIVE_JOB_CONFLICT":
            raise AppError(
                "ACTIVE_JOB_CONFLICT",
                "旧任务仍在取消或当前活动任务与请求不一致，请稍后重试",
                status_code=409,
            ) from exc
        raise AppError(
            "ROW_REVISION_CONFLICT", "该行已被修改，请刷新后重试", status_code=409
        ) from exc

    record_audit(
        db,
        event_type="JOB_RUN_REQUESTED",
        actor_user_id=user.id,
        row_id=row.id,
        job_id=job_id,
        details={
            "force_regenerate": payload.force_regenerate,
            "row_revision": row.row_revision,
        },
    )
    db.commit()

    response.status_code = 202
    return success({"job_id": job_id, "status": "PENDING_DISPATCH"})


@router.post("/rows/{row_id}/cancel")
def cancel_row_job(
    row_id: str,
    payload: CancelJobRequest,
    db: DatabaseSession,
    user: CurrentUser,
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
    record_audit(
        db,
        event_type="JOB_CANCEL_REQUESTED",
        actor_user_id=user.id,
        row_id=row.id,
        job_id=job.id,
        details={"job_status": job.status, "row_revision": row.row_revision},
    )
    db.commit()
    return success({"job_id": job.id, "status": job.status})
