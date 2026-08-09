from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.enums import JobStatus, RowStatus
from app.models import Job, JobDispatchOutbox, PromptRow

Enqueue = Callable[[str, str], None]
QueueContains = Callable[[str, str], bool]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _reusable_active_job(
    job: Job | None,
    *,
    expected_revision: int,
    input_fingerprint: str,
) -> Job | None:
    if job is None or job.status not in {
        JobStatus.PENDING_DISPATCH,
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.VALIDATING,
        JobStatus.REPAIRING,
    }:
        return None
    if job.row_revision != expected_revision or job.input_fingerprint != input_fingerprint:
        raise ValueError("ACTIVE_JOB_CONFLICT")
    return job


def create_job_and_outbox(
    session: Session,
    *,
    row_id: str,
    expected_revision: int,
    input_fingerprint: str,
    input_snapshot: dict[str, object],
    queue_name: str = "prompt-generation",
    row_status_after_create: RowStatus | None = None,
    commit: bool = True,
) -> str:
    row = session.get(PromptRow, row_id)
    if row is None:
        raise LookupError("任务行不存在")
    if row.row_revision != expected_revision:
        raise ValueError("ROW_REVISION_CONFLICT")
    if row.active_job_id:
        active_job = _reusable_active_job(
            session.get(Job, row.active_job_id),
            expected_revision=expected_revision,
            input_fingerprint=input_fingerprint,
        )
        if active_job is None:
            raise ValueError("ACTIVE_JOB_CONFLICT")
        return active_job.id

    job = Job(
        row_id=row.id,
        status=JobStatus.PENDING_DISPATCH,
        row_revision=expected_revision,
        input_fingerprint=input_fingerprint,
        input_snapshot_json=json.dumps(input_snapshot, ensure_ascii=False, sort_keys=True),
        queue_name=queue_name,
    )
    try:
        session.add(job)
        session.flush()
        session.add(
            JobDispatchOutbox(
                job_id=job.id,
                queue_name=queue_name,
                deterministic_rq_job_id=job.id,
                status="PENDING",
            )
        )
        values: dict[str, object] = {
            "active_job_id": job.id,
            "input_fingerprint": input_fingerprint,
        }
        if row_status_after_create is not None:
            values["status"] = row_status_after_create
        updated = session.execute(
            update(PromptRow)
            .where(
                PromptRow.id == row_id,
                PromptRow.row_revision == expected_revision,
                PromptRow.active_job_id.is_(None),
                PromptRow.deleted_at.is_(None),
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if getattr(updated, "rowcount", 0) != 1:
            raise IntegrityError("row CAS failed", {}, RuntimeError("row CAS failed"))
        if commit:
            session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(Job).where(
                Job.row_id == row_id,
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
        )
        if existing is None:
            raise
        reusable_job = _reusable_active_job(
            existing,
            expected_revision=expected_revision,
            input_fingerprint=input_fingerprint,
        )
        if reusable_job is None:
            raise ValueError("ACTIVE_JOB_CONFLICT") from None
        return reusable_job.id
    return job.id


def dispatch_pending_outbox(session: Session, *, enqueue: Enqueue, limit: int = 50) -> int:
    lease_cutoff = utc_now() - timedelta(minutes=2)
    entries = session.scalars(
        select(JobDispatchOutbox)
        .where(
            (JobDispatchOutbox.status.in_(("PENDING", "FAILED")))
            | (
                (JobDispatchOutbox.status == "DISPATCHING")
                & (JobDispatchOutbox.updated_at <= lease_cutoff)
            )
        )
        .where(JobDispatchOutbox.next_attempt_at <= utc_now())
        .order_by(JobDispatchOutbox.created_at)
        .limit(limit)
    ).all()
    dispatched = 0
    for entry in entries:
        previous_status = entry.status
        previous_updated_at = entry.updated_at
        claim = session.execute(
            update(JobDispatchOutbox)
            .where(
                JobDispatchOutbox.id == entry.id,
                JobDispatchOutbox.status == previous_status,
                JobDispatchOutbox.updated_at == previous_updated_at,
            )
            .values(
                status="DISPATCHING",
                attempt_count=JobDispatchOutbox.attempt_count + 1,
                updated_at=utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(claim, "rowcount", 0) != 1:
            session.rollback()
            continue
        session.commit()
        session.refresh(entry)
        claim_updated_at = entry.updated_at
        job = session.get(Job, entry.job_id)
        try:
            enqueue(entry.deterministic_rq_job_id, entry.queue_name)
        except Exception as exc:
            failed = session.execute(
                update(JobDispatchOutbox)
                .where(
                    JobDispatchOutbox.id == entry.id,
                    JobDispatchOutbox.status == "DISPATCHING",
                    JobDispatchOutbox.updated_at == claim_updated_at,
                )
                .values(
                    status="FAILED",
                    last_error=type(exc).__name__,
                    next_attempt_at=utc_now()
                    + timedelta(seconds=min(300, 10 * (2 ** min(entry.attempt_count - 1, 5)))),
                    updated_at=utc_now(),
                )
                .execution_options(synchronize_session=False)
            )
            if getattr(failed, "rowcount", 0) == 1:
                session.commit()
            else:
                session.rollback()
            continue

        if job is not None:
            session.refresh(job)
        succeeded = session.execute(
            update(JobDispatchOutbox)
            .where(
                JobDispatchOutbox.id == entry.id,
                JobDispatchOutbox.status == "DISPATCHING",
                JobDispatchOutbox.updated_at == claim_updated_at,
            )
            .values(
                status="DISPATCHED",
                dispatched_at=utc_now(),
                updated_at=utc_now(),
                last_error=None,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(succeeded, "rowcount", 0) == 1:
            session.execute(
                update(Job)
                .where(
                    Job.id == entry.job_id,
                    Job.status == JobStatus.PENDING_DISPATCH,
                )
                .values(
                    status=JobStatus.QUEUED,
                    rq_job_id=entry.deterministic_rq_job_id,
                )
                .execution_options(synchronize_session=False)
            )
            session.commit()
        else:
            session.rollback()
        dispatched += 1
    return dispatched


def recover_lost_queued_jobs(
    session: Session,
    *,
    queue_contains: QueueContains,
    minimum_age_seconds: float = 120.0,
    limit: int = 50,
) -> int:
    cutoff = utc_now() - timedelta(seconds=minimum_age_seconds)
    jobs = session.scalars(
        select(Job)
        .where(Job.status == JobStatus.QUEUED, Job.created_at <= cutoff)
        .order_by(Job.created_at)
        .limit(limit)
    ).all()
    recovered = 0
    for job in jobs:
        rq_job_id = job.rq_job_id or job.id
        if queue_contains(rq_job_id, job.queue_name):
            continue
        restored = session.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == JobStatus.QUEUED)
            .values(status=JobStatus.PENDING_DISPATCH, rq_job_id=None)
            .execution_options(synchronize_session=False)
        )
        if getattr(restored, "rowcount", 0) != 1:
            session.rollback()
            continue
        session.execute(
            update(JobDispatchOutbox)
            .where(JobDispatchOutbox.job_id == job.id)
            .values(
                status="PENDING",
                next_attempt_at=utc_now(),
                last_error="QUEUE_ENTRY_MISSING",
                updated_at=utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        session.commit()
        recovered += 1
    return recovered
