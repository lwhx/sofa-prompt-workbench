from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine

from app.dependencies import CurrentUser

router = APIRouter(tags=["实时事件"])

_POLL_INTERVAL_SECONDS = 1
_KEEPALIVE_INTERVAL_SECONDS = 15
_INVALIDATE_EVENT = (
    f"event: invalidate\ndata: {json.dumps({'scope': 'rows'}, separators=(',', ':'))}\n\n"
)


class EventWatermarkHub:
    def __init__(self, engine: Engine, *, poll_interval_seconds: float = _POLL_INTERVAL_SECONDS):
        self._engine = engine
        self._poll_interval_seconds = poll_interval_seconds
        self._subscribers: set[asyncio.Queue[None]] = set()
        self._task: asyncio.Task[None] | None = None

    def subscribe(self) -> asyncio.Queue[None]:
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll())
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[None]) -> None:
        self._subscribers.discard(queue)
        if self._subscribers or self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _poll(self) -> None:
        with self._engine.connect() as connection:
            watermark = connection.exec_driver_sql("PRAGMA data_version").scalar_one()
            while True:
                await asyncio.sleep(self._poll_interval_seconds)
                current_watermark = connection.exec_driver_sql("PRAGMA data_version").scalar_one()
                if current_watermark == watermark:
                    continue
                watermark = current_watermark
                for queue in tuple(self._subscribers):
                    if queue.empty():
                        queue.put_nowait(None)


async def _events(*, once: bool, hub: EventWatermarkHub) -> AsyncIterator[str]:
    yield "retry: 3000\n"
    yield _INVALIDATE_EVENT
    if once:
        return

    queue = hub.subscribe()
    try:
        while True:
            try:
                await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL_SECONDS)
                yield _INVALIDATE_EVENT
            except TimeoutError:
                yield ": keepalive\n\n"
    finally:
        await hub.unsubscribe(queue)


@router.get("/events")
def events(
    request: Request,
    _user: CurrentUser,
    once: bool = Query(default=False),
) -> StreamingResponse:
    return StreamingResponse(
        _events(once=once, hub=request.app.state.event_watermark_hub),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
