from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.enums import RowStatus
from app.models import AutoRunIntent, PromptResult, PromptRow
from app.services.dispatch import create_job_and_outbox
from app.services.job_inputs import freeze_job_input


def utc_now() -> datetime:
    return datetime.now(UTC)


def upsert_auto_run_intent(
    session: Session,
    row: PromptRow,
    *,
    debounce_seconds: float,
) -> None:
    now = utc_now()
    if not row.auto_run or not row.scene_asset_id or not row.sofa_asset_id or row.active_job_id:
        session.execute(
            update(AutoRunIntent)
            .where(AutoRunIntent.row_id == row.id)
            .values(
                status="CANCELED",
                claim_token=None,
                claimed_at=None,
                lease_expires_at=None,
                updated_at=now,
            )
        )
        return
    due_at = now + timedelta(seconds=debounce_seconds)
    statement = insert(AutoRunIntent).values(
        row_id=row.id,
        expected_revision=row.row_revision,
        due_at=due_at,
        status="PENDING",
        claimed_at=None,
        claim_token=None,
        lease_expires_at=None,
        attempt_count=0,
        last_error=None,
        updated_at=now,
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[AutoRunIntent.row_id],
            set_={
                "expected_revision": row.row_revision,
                "due_at": due_at,
                "status": "PENDING",
                "claimed_at": None,
                "claim_token": None,
                "lease_expires_at": None,
                "attempt_count": 0,
                "last_error": None,
                "updated_at": now,
            },
        )
    )
    row.status = RowStatus.DEBOUNCING


def consume_due_auto_run_intents(
    session: Session,
    *,
    settings: Settings,
    limit: int = 50,
) -> int:
    now = utc_now()
    candidates = session.scalars(
        select(AutoRunIntent)
        .where(
            AutoRunIntent.due_at <= now,
            or_(
                AutoRunIntent.status == "PENDING",
                (AutoRunIntent.status == "CLAIMED")
                & (
                    AutoRunIntent.lease_expires_at.is_(None)
                    | (AutoRunIntent.lease_expires_at <= now)
                ),
            ),
        )
        .order_by(AutoRunIntent.due_at)
        .limit(limit)
    ).all()
    consumed = 0
    for candidate in candidates:
        token = str(uuid.uuid4())
        claim = session.execute(
            update(AutoRunIntent)
            .where(
                AutoRunIntent.id == candidate.id,
                AutoRunIntent.expected_revision == candidate.expected_revision,
                or_(
                    AutoRunIntent.status == "PENDING",
                    (AutoRunIntent.status == "CLAIMED")
                    & (
                        AutoRunIntent.lease_expires_at.is_(None)
                        | (AutoRunIntent.lease_expires_at <= now)
                    ),
                ),
            )
            .values(
                status="CLAIMED",
                claimed_at=now,
                claim_token=token,
                lease_expires_at=now + timedelta(seconds=settings.auto_run_lease_seconds),
                attempt_count=AutoRunIntent.attempt_count + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(claim, "rowcount", 0) != 1:
            session.rollback()
            continue
        session.commit()
        try:
            if _consume_claimed_intent(session, candidate.id, token, settings):
                consumed += 1
        except Exception as exc:
            session.rollback()
            _release_failed_intent(session, candidate.id, token, exc)
    return consumed


def _consume_claimed_intent(
    session: Session,
    intent_id: str,
    claim_token: str,
    settings: Settings,
) -> bool:
    intent = session.scalar(
        select(AutoRunIntent).where(
            AutoRunIntent.id == intent_id,
            AutoRunIntent.status == "CLAIMED",
            AutoRunIntent.claim_token == claim_token,
        )
    )
    if intent is None:
        return False
    row = session.get(PromptRow, intent.row_id)
    if (
        row is None
        or row.deleted_at is not None
        or row.row_revision != intent.expected_revision
        or not row.auto_run
        or not row.scene_asset_id
        or not row.sofa_asset_id
        or row.active_job_id is not None
        or (row.status == RowStatus.NEEDS_REVIEW and not row.view_override_enabled)
    ):
        _finish_intent(intent, "STALE")
        session.commit()
        return False
    frozen_input = freeze_job_input(session, row, settings)
    reusable_result = session.scalar(
        select(PromptResult)
        .where(
            PromptResult.row_id == row.id,
            PromptResult.input_fingerprint == frozen_input.fingerprint,
            PromptResult.is_stale.is_(False),
            PromptResult.hidden_at.is_(None),
        )
        .order_by(PromptResult.version.desc())
    )
    if reusable_result is not None:
        row.latest_result_id = reusable_result.id
        if row.selected_result_id is None:
            row.selected_result_id = reusable_result.id
        row.last_success_fingerprint = frozen_input.fingerprint
        row.input_fingerprint = frozen_input.fingerprint
        row.status = (
            RowStatus.NEEDS_REVIEW
            if reusable_result.review_status == "NEEDS_REVIEW"
            else RowStatus.COMPLETED
        )
        row.dirty = False
        row.error_message = None
        _finish_intent(intent, "CONSUMED")
        session.commit()
        return False
    create_job_and_outbox(
        session,
        row_id=row.id,
        expected_revision=intent.expected_revision,
        input_fingerprint=frozen_input.fingerprint,
        input_snapshot=frozen_input.snapshot,
        row_status_after_create=RowStatus.QUEUED,
        commit=False,
    )
    _finish_intent(intent, "CONSUMED")
    session.commit()
    return True


def _finish_intent(intent: AutoRunIntent, status: str) -> None:
    intent.status = status
    intent.claim_token = None
    intent.lease_expires_at = None
    intent.last_error = None
    intent.updated_at = utc_now()


def _release_failed_intent(
    session: Session,
    intent_id: str,
    claim_token: str,
    exc: Exception,
) -> None:
    now = utc_now()
    released = session.execute(
        update(AutoRunIntent)
        .where(
            AutoRunIntent.id == intent_id,
            AutoRunIntent.status == "CLAIMED",
            AutoRunIntent.claim_token == claim_token,
        )
        .values(
            status="PENDING",
            due_at=now + timedelta(seconds=10),
            claim_token=None,
            claimed_at=None,
            lease_expires_at=None,
            last_error=type(exc).__name__,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(released, "rowcount", 0) == 1:
        session.commit()
    else:
        session.rollback()
