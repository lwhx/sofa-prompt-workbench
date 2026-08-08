from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import CurrentUser, DatabaseSession
from app.enums import RowStatus
from app.errors import AppError, success
from app.models import PromptResult, PromptRow

router = APIRouter(tags=["结果版本"])


class SelectResultRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class ConfirmReviewRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    view_override: dict[str, object]
    note: str | None = Field(default=None, max_length=2000)


def _result_to_dict(result: PromptResult) -> dict[str, object]:
    return {
        "id": result.id,
        "version": result.version,
        "source": result.source,
        "schema_version": result.schema_version,
        "positive_prompt": result.positive_prompt,
        "negative_prompt": result.negative_prompt,
        "review_status": result.review_status,
        "review": json.loads(result.review_json or "{}"),
        "warnings": json.loads(result.warnings_json or "[]"),
        "is_stale": result.is_stale,
        "selected_at": result.selected_at.isoformat() if result.selected_at else None,
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }


@router.get("/rows/{row_id}/results")
def list_results(
    row_id: str,
    db: DatabaseSession,
    _user: CurrentUser,
) -> dict[str, object]:
    row = db.get(PromptRow, row_id)
    if row is None:
        raise AppError("ROW_NOT_FOUND", "任务行不存在", status_code=404)
    results = db.scalars(
        select(PromptResult)
        .where(PromptResult.row_id == row_id)
        .order_by(PromptResult.version.desc())
    ).all()
    return success([_result_to_dict(result) for result in results])


@router.post("/rows/{row_id}/results/{result_id}/select")
def select_result(
    row_id: str,
    result_id: str,
    payload: SelectResultRequest,
    db: DatabaseSession,
    _user: CurrentUser,
) -> dict[str, object]:
    row = db.get(PromptRow, row_id)
    result = db.get(PromptResult, result_id)
    if row is None or result is None or result.row_id != row_id:
        raise AppError("RESULT_NOT_FOUND", "结果版本不存在", status_code=404)
    if row.row_revision != payload.expected_revision:
        raise AppError("ROW_REVISION_CONFLICT", "该行已被修改，请刷新后重试", status_code=409)
    if result.is_stale:
        raise AppError("RESULT_STALE", "过期输入的结果不能设为正式版本")
    row.selected_result_id = result.id
    row.row_revision += 1
    row.updated_at = datetime.now(UTC)
    result.selected_at = datetime.now(UTC)
    db.commit()
    return success({"selected_result_id": result.id, "row_revision": row.row_revision})


@router.delete("/rows/{row_id}/results/{result_id}")
def delete_result(
    row_id: str,
    result_id: str,
    db: DatabaseSession,
    _user: CurrentUser,
) -> dict[str, object]:
    row = db.get(PromptRow, row_id)
    result = db.get(PromptResult, result_id)
    if row is None or result is None or result.row_id != row_id:
        raise AppError("RESULT_NOT_FOUND", "结果版本不存在", status_code=404)
    replacement = db.scalar(
        select(PromptResult)
        .where(PromptResult.row_id == row_id, PromptResult.id != result_id)
        .order_by(PromptResult.version.desc())
    )
    if row.selected_result_id == result.id:
        row.selected_result_id = replacement.id if replacement else None
    if row.latest_result_id == result.id:
        row.latest_result_id = replacement.id if replacement else None
    db.delete(result)
    db.commit()
    return success(
        {
            "deleted": True,
            "selected_result_id": row.selected_result_id,
            "latest_result_id": row.latest_result_id,
        }
    )


@router.post("/rows/{row_id}/review/confirm")
def confirm_review(
    row_id: str,
    payload: ConfirmReviewRequest,
    db: DatabaseSession,
    _user: CurrentUser,
) -> dict[str, object]:
    row = db.get(PromptRow, row_id)
    if row is None or row.deleted_at is not None:
        raise AppError("ROW_NOT_FOUND", "任务行不存在", status_code=404)
    if row.row_revision != payload.expected_revision:
        raise AppError("ROW_REVISION_CONFLICT", "该行已被修改，请刷新后重试", status_code=409)
    required = ("view_type", "near_end", "far_end")
    if any(not payload.view_override.get(key) for key in required):
        raise AppError("VIEW_OVERRIDE_INVALID", "请完整确认视角、近端和远端")
    row.view_override_enabled = True
    row.view_override_json = json.dumps(payload.view_override, ensure_ascii=False, sort_keys=True)
    row.review_note = payload.note
    row.row_revision += 1
    row.status = RowStatus.READY
    row.dirty = True
    row.input_fingerprint = None
    row.updated_at = datetime.now(UTC)
    db.commit()
    return success({"row_revision": row.row_revision, "status": "READY"})
