from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable
from time import monotonic

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import CurrentUser
from app.models import Job, PromptResult, PromptRow

router = APIRouter(tags=["实时事件"])

_POLL_INTERVAL_SECONDS = 1
_KEEPALIVE_INTERVAL_SECONDS = 15
_INVALIDATE_EVENT = (
    f"event: invalidate\ndata: {json.dumps({'scope': 'rows'}, separators=(',', ':'))}\n\n"
)


def _event_fingerprint(session: Session) -> str:
    visible_rows = select(PromptRow.id).where(PromptRow.deleted_at.is_(None))
    row_versions = session.execute(
        select(PromptRow.id, PromptRow.row_revision, PromptRow.status)
        .where(PromptRow.deleted_at.is_(None))
        .order_by(PromptRow.id)
    ).all()
    job_versions = session.execute(
        select(Job.id, Job.row_id, Job.status, Job.progress_percent)
        .where(Job.row_id.in_(visible_rows))
        .order_by(Job.id)
    ).all()
    result_versions = session.execute(
        select(
            PromptResult.id,
            PromptResult.row_id,
            PromptResult.version,
            PromptResult.review_status,
            PromptResult.is_stale,
        )
        .where(PromptResult.row_id.in_(visible_rows))
        .order_by(PromptResult.id)
    ).all()
    payload = (row_versions, job_versions, result_versions)
    return hashlib.sha256(repr(payload).encode()).hexdigest()


async def _events(*, once: bool, session_factory: Callable[[], Session]) -> AsyncIterator[str]:
    yield "retry: 3000\n"
    yield _INVALIDATE_EVENT
    if once:
        return

    with session_factory() as session:
        fingerprint = _event_fingerprint(session)
    last_keepalive = monotonic()
    while True:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        with session_factory() as session:
            current_fingerprint = _event_fingerprint(session)
        if current_fingerprint != fingerprint:
            fingerprint = current_fingerprint
            yield _INVALIDATE_EVENT
            continue
        if monotonic() - last_keepalive >= _KEEPALIVE_INTERVAL_SECONDS:
            last_keepalive = monotonic()
            yield ": keepalive\n\n"


@router.get("/events")
def events(
    request: Request,
    _user: CurrentUser,
    once: bool = Query(default=False),
) -> StreamingResponse:
    return StreamingResponse(
        _events(once=once, session_factory=request.app.state.session_factory),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
