from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
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
    is_stale = False
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

    terminal_status = JobStatus.REVIEW_REQUIRED if review_required else JobStatus.SUCCEEDED
    completed_at = datetime.now(UTC)
    finalized_job = session.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.status.in_(
                (
                    JobStatus.RUNNING,
                    JobStatus.VALIDATING,
                    JobStatus.REPAIRING,
                )
            ),
        )
        .values(status=terminal_status, completed_at=completed_at)
        .execution_options(synchronize_session=False)
    )
    if getattr(finalized_job, "rowcount", 0) != 1:
        session.rollback()
        raise RuntimeError("JOB_TERMINAL_CAS_CONFLICT")
    selected_result_id = row.selected_result_id or result.id
    updated_row = session.execute(
        update(PromptRow)
        .where(
            PromptRow.id == row.id,
            PromptRow.row_revision == job.row_revision,
            PromptRow.input_fingerprint == job.input_fingerprint,
            PromptRow.active_job_id == job.id,
            PromptRow.deleted_at.is_(None),
        )
        .values(
            active_job_id=None,
            latest_result_id=result.id,
            selected_result_id=selected_result_id,
            last_success_fingerprint=job.input_fingerprint,
            status=RowStatus.NEEDS_REVIEW if review_required else RowStatus.COMPLETED,
            dirty=False,
        )
        .execution_options(synchronize_session=False)
    )
    is_stale = getattr(updated_row, "rowcount", 0) != 1
    result.is_stale = is_stale
    if not is_stale and row.selected_result_id is None:
        result.selected_at = result.created_at
    session.commit()
    session.refresh(result)
    return result
