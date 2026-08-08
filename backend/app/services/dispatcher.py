from __future__ import annotations

import logging
import time
from typing import Any

from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import create_database_engine
from app.services.dispatch import dispatch_pending_outbox
from app.services.worker import reap_stale_jobs, run_prompt_job

logger = logging.getLogger(__name__)

_engine: Any = None
_redis: Any = None


def _get_engine():
    """获取数据库引擎单例。连接异常时自动重建。"""
    global _engine
    if _engine is None:
        _engine = create_database_engine(get_settings().database_url)
    return _engine


def _get_redis():
    """获取 Redis 连接单例。连接异常时自动重建。"""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url)
    return _redis


def _reset_connections() -> None:
    """重置连接单例，下次调用时重新创建。"""
    global _engine, _redis
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = None
    _redis = None


def dispatch_once() -> int:
    settings = get_settings()
    engine = _get_engine()
    connection = None if settings.local_inline_worker else _get_redis()

    def enqueue(job_id: str, queue_name: str) -> None:
        if settings.local_inline_worker:
            run_prompt_job(job_id)
            return
        queue = Queue(queue_name, connection=connection)
        existing = queue.fetch_job(job_id)
        if existing is not None:
            status = existing.get_status(refresh=True)
            if status in {"queued", "started", "deferred", "scheduled"}:
                return
            if status in {"finished", "failed", "stopped", "canceled"}:
                existing.delete()
        queue.enqueue(
            run_prompt_job,
            job_id,
            job_id=job_id,
            job_timeout=max(300, int(settings.ai_timeout_seconds) + 60),
            result_ttl=86400,
            failure_ttl=604800,
        )

    with Session(engine) as session:
        dispatched = dispatch_pending_outbox(session, enqueue=enqueue)
        reap_stale_jobs(session)
        return dispatched


def run_dispatcher_forever(interval_seconds: float = 3.0) -> None:
    """Dispatcher 主循环，每 interval_seconds 执行一次调度+回收。连接异常时自动重建。"""
    backoff = interval_seconds
    max_backoff = 60.0
    while True:
        try:
            dispatch_once()
            backoff = interval_seconds
        except Exception:
            logger.error("Dispatcher 调度异常，%ds 后重试", int(backoff), exc_info=True)
            _reset_connections()
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            continue
        time.sleep(interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_dispatcher_forever()
