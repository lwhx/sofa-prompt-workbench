from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record_audit(
    session: Session,
    *,
    event_type: str,
    actor_user_id: str | None,
    details: dict[str, Any] | None = None,
    row_id: str | None = None,
    job_id: str | None = None,
) -> AuditEvent:
    """向当前事务添加审计事件，由调用方统一提交。"""
    event = AuditEvent(
        event_type=event_type,
        actor_user_id=actor_user_id,
        row_id=row_id,
        job_id=job_id,
        details_json=json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
    )
    session.add(event)
    return event
