import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api.v1.events import EventWatermarkHub
from app.config import Settings
from app.database import create_database_engine
from app.enums import RowStatus
from app.main import create_app
from app.models import AdminUser, Base, PromptRow
from app.security.password import hash_password


def test_sse_requires_authentication(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'events.db'}")
    Base.metadata.create_all(engine)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'events.db'}",
        session_secret="test-session-secret-at-least-32-bytes",
    )
    client = TestClient(create_app(settings=settings, engine=engine))

    response = client.get("/api/v1/events")

    assert response.status_code == 401


def test_sse_emits_initial_invalidation_event(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'events-auth.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AdminUser(username="admin", password_hash=hash_password("pw")))
        session.commit()
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'events-auth.db'}",
        session_secret="test-session-secret-at-least-32-bytes",
    )
    client = TestClient(create_app(settings=settings, engine=engine))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})

    with client.stream("GET", "/api/v1/events?once=true") as response:
        content = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "event: invalidate" in content
    assert '"scope":"rows"' in content


@pytest.mark.asyncio
async def test_event_watermark_hub_shares_one_lightweight_poll_for_all_subscribers(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'event-watermark.db'}")
    Base.metadata.create_all(engine)
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    hub = EventWatermarkHub(engine, poll_interval_seconds=0.01)
    first = hub.subscribe()
    second = hub.subscribe()
    await asyncio.sleep(0.02)

    with Session(engine) as session:
        row = PromptRow(sort_key=10, status=RowStatus.READY)
        session.add(row)
        session.commit()

    await asyncio.wait_for(first.get(), timeout=0.2)
    await asyncio.wait_for(second.get(), timeout=0.2)
    await hub.unsubscribe(first)
    await hub.unsubscribe(second)

    normalized = [statement.strip().upper() for statement in statements]
    assert normalized
    poll_statements = [statement for statement in normalized if statement == "PRAGMA DATA_VERSION"]
    assert poll_statements
    assert not any(statement.startswith("SELECT") for statement in normalized)
