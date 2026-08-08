from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.ai_schema import normalize_provider_payload
from app.enums import JobStatus, RowStatus
from app.models import Job, PromptResult, PromptRow


def finalize_result_with_row_cas(
    session: Session,
    *,
    job_id: str,
    payload: dict[str, Any],
    source: str,
    review_required: bool,
    parent_result_id: str | None = None,
) -> PromptResult:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError("Job 不存在")
    row = session.get(PromptRow, job.row_id)
    if row is None:
        raise LookupError("任务行不存在")

    normalized = normalize_provider_payload(payload)
    version = (
        session.scalar(
            select(func.coalesce(func.max(PromptResult.version), 0)).where(
                PromptResult.row_id == row.id
            )
        )
        or 0
    ) + 1
    is_stale = (
        row.row_revision != job.row_revision
        or row.input_fingerprint != job.input_fingerprint
        or row.deleted_at is not None
    )
    payload_json = normalized.model_dump_json()
    validation = {
        "passed": not review_required and not normalized.review.required,
        "review_required": review_required or normalized.review.required,
        "review_reasons": normalized.review.reasons,
        "warnings": normalized.warnings,
    }
    result = PromptResult(
        row_id=row.id,
        job_id=job.id,
        parent_result_id=parent_result_id,
        version=version,
        source=source,
        schema_version=normalized.schema_version,
        result_payload_json=payload_json,
        sofa_view_json=json.dumps(normalized.sofa_view.model_dump(), ensure_ascii=False),
        sofa_product_json=json.dumps(normalized.sofa_product.model_dump(), ensure_ascii=False),
        scene_observations_json=json.dumps(
            normalized.scene_observations.model_dump(), ensure_ascii=False
        ),
        composition_plan_json=json.dumps(
            normalized.composition_plan.model_dump(), ensure_ascii=False
        ),
        review_json=json.dumps(normalized.review.model_dump(), ensure_ascii=False),
        positive_prompt=normalized.positive_prompt,
        negative_prompt=normalized.negative_prompt,
        warnings_json=json.dumps(normalized.warnings, ensure_ascii=False),
        validation_json=json.dumps(validation, ensure_ascii=False),
        review_status="NEEDS_REVIEW" if review_required else "PASSED",
        row_revision=job.row_revision,
        input_fingerprint=job.input_fingerprint,
        is_stale=is_stale,
    )
    session.add(result)
    session.flush()

    job.status = JobStatus.REVIEW_REQUIRED if review_required else JobStatus.SUCCEEDED
    job.completed_at = datetime.now(UTC)
    if row.active_job_id == job.id:
        row.active_job_id = None
    if not is_stale:
        row.latest_result_id = result.id
        if row.selected_result_id is None:
            row.selected_result_id = result.id
            result.selected_at = result.created_at
        row.last_success_fingerprint = job.input_fingerprint
        row.status = RowStatus.NEEDS_REVIEW if review_required else RowStatus.COMPLETED
        row.dirty = False
    session.commit()
    session.refresh(result)
    return result
