from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import fakeredis
import httpx
import respx
from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import create_database_engine
from app.enums import JobStatus
from app.models import Base, Job, JobAttempt, PromptResult, PromptRow
from app.services.dispatch import create_job_and_outbox, dispatch_pending_outbox
from app.services.worker import load_skill_prompts


def test_outbox_enqueues_to_rq_via_fakeredis(tmp_path: Path) -> None:
    enqueued: list[str] = []

    def enqueue(job_id: str, queue_name: str) -> None:
        enqueued.append(job_id)

    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_database_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        row = PromptRow(sort_key=10, name="RQ 测试", row_revision=1, input_fingerprint="fp1")
        session.add(row)
        session.commit()

        job_id = create_job_and_outbox(
            session,
            row_id=row.id,
            expected_revision=1,
            input_fingerprint="fp1",
            input_snapshot={"row_id": row.id},
        )
        count = dispatch_pending_outbox(session, enqueue=enqueue)
        assert count == 1
        assert enqueued == [job_id]

        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.QUEUED
        assert job.rq_job_id == job_id


@respx.mock
def test_worker_called_via_fakeredis_job(tmp_path: Path) -> None:
    from app.services.worker import run_prompt_job

    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_database_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        row = PromptRow(sort_key=10, name="Worker 测试", row_revision=1, input_fingerprint="fp-w")
        session.add(row)
        session.commit()

        job_id = create_job_and_outbox(
            session,
            row_id=row.id,
            expected_revision=1,
            input_fingerprint="fp-w",
            input_snapshot={
                "row_id": row.id,
                "row_revision": 1,
                "scene_asset": {"url": "data:image/jpeg;base64,SCENE"},
                "sofa_asset": {"url": "data:image/png;base64,SOFA"},
            },
        )
        job = session.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.QUEUED
        session.commit()

    connection = fakeredis.FakeRedis()
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "req-worker",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"positive_prompt":"真实模型结果","negative_prompt":"镜像"}'
                        },
                    }
                ],
                "usage": {"total_tokens": 12},
            },
        )
    )
    queue = Queue("prompt-generation", connection=connection, is_async=False)
    queue.enqueue(
        run_prompt_job,
        args=(job_id,),
        kwargs={
            "database_url": db_url,
            "ai_base_url": "https://api.example.com/v1",
            "ai_api_key": "test-key",
            "ai_model": "vision-model",
        },
    )

    assert queue.count == 0
    assert queue.finished_job_registry.count == 1

    with Session(engine) as session:
        result = session.scalar(select(PromptResult).where(PromptResult.job_id == job_id))
        assert result is not None
        assert result.positive_prompt == "真实模型结果"
        assert result.is_stale is False


def test_worker_recovers_from_unexpected_exception(tmp_path: Path, monkeypatch) -> None:
    from app.services import worker

    db_url = f"sqlite:///{tmp_path / 'unexpected.db'}"
    engine = create_database_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        row = PromptRow(sort_key=10, name="异常恢复", row_revision=1, input_fingerprint="fp-error")
        session.add(row)
        session.commit()
        row_id = row.id
        job_id = create_job_and_outbox(
            session,
            row_id=row_id,
            expected_revision=1,
            input_fingerprint="fp-error",
            input_snapshot={
                "scene_asset": {"url": "data:image/jpeg;base64,SCENE"},
                "sofa_asset": {"url": "data:image/png;base64,SOFA"},
            },
        )
        job = session.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.QUEUED
        session.commit()

    def raise_unexpected_error():
        raise RuntimeError("规则文件损坏")

    monkeypatch.setattr(worker, "load_skill_prompts", raise_unexpected_error)
    worker.run_prompt_job(
        job_id,
        database_url=db_url,
        ai_base_url="https://api.example.com/v1",
        ai_api_key="test-key",
        ai_model="vision-model",
    )

    with Session(engine) as session:
        job = session.get(Job, job_id)
        row = session.get(PromptRow, row_id)
        attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id))
        assert job is not None
        assert row is not None
        assert attempt is not None
        assert job.status == JobStatus.FAILED
        assert job.error_code == "WORKER_ERROR"
        assert row.status == "FAILED"
        assert row.active_job_id is None
        assert attempt.status == "FAILED"
        assert attempt.error_code == "WORKER_ERROR"
        assert "规则文件损坏" not in (attempt.error_message or "")


def test_worker_recovers_when_snapshot_is_invalid(tmp_path: Path) -> None:
    from app.services import worker

    db_url = f"sqlite:///{tmp_path / 'invalid-snapshot.db'}"
    engine = create_database_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        row = PromptRow(sort_key=10, name="快照异常", row_revision=1, input_fingerprint="fp-json")
        session.add(row)
        session.commit()
        row_id = row.id
        job_id = create_job_and_outbox(
            session,
            row_id=row_id,
            expected_revision=1,
            input_fingerprint="fp-json",
            input_snapshot={"row_id": row_id},
        )
        job = session.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.QUEUED
        job.input_snapshot_json = "not-json"
        session.commit()

    worker.run_prompt_job(job_id, database_url=db_url)

    with Session(engine) as session:
        job = session.get(Job, job_id)
        row = session.get(PromptRow, row_id)
        assert job is not None
        assert row is not None
        assert job.status == JobStatus.FAILED
        assert job.error_code == "WORKER_ERROR"
        assert row.status == "FAILED"
        assert row.active_job_id is None


def test_worker_refreshes_heartbeat_during_provider_call(tmp_path: Path, monkeypatch) -> None:
    from app.services import worker

    db_url = f"sqlite:///{tmp_path / 'heartbeat.db'}"
    engine = create_database_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        row = PromptRow(
            sort_key=10,
            name="心跳测试",
            row_revision=1,
            input_fingerprint="fp-heartbeat",
        )
        session.add(row)
        session.commit()
        job_id = create_job_and_outbox(
            session,
            row_id=row.id,
            expected_revision=1,
            input_fingerprint="fp-heartbeat",
            input_snapshot={
                "scene_asset": {"url": "data:image/jpeg;base64,SCENE"},
                "sofa_asset": {"url": "data:image/png;base64,SOFA"},
            },
        )
        job = session.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.QUEUED
        session.commit()

    provider_started = Event()
    provider_release = Event()

    def block_provider_call(self, **kwargs):
        provider_started.set()
        assert provider_release.wait(timeout=5)
        raise RuntimeError("结束测试调用")

    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(worker.OpenAICompatibleProvider, "generate_prompt", block_provider_call)
    thread = Thread(
        target=worker.run_prompt_job,
        kwargs={
            "job_id": job_id,
            "database_url": db_url,
            "ai_base_url": "https://api.example.com/v1",
            "ai_api_key": "test-key",
            "ai_model": "vision-model",
        },
    )
    thread.start()
    assert provider_started.wait(timeout=5)

    with Session(engine) as session:
        initial_heartbeat = session.get(Job, job_id).heartbeat_at

    heartbeat_updated = Event()
    for _ in range(40):
        if heartbeat_updated.wait(timeout=0.025):
            break
        with Session(engine) as session:
            current_heartbeat = session.get(Job, job_id).heartbeat_at
        if current_heartbeat != initial_heartbeat:
            heartbeat_updated.set()

    provider_release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert heartbeat_updated.is_set()


def test_worker_prompt_requires_ai_to_infer_sofa_direction() -> None:
    system_prompt, user_prompt = load_skill_prompts()
    prompt = system_prompt + user_prompt

    assert "空间适配沙发，而不是沙发适配空间" in prompt
    assert "近端" in prompt
    assert "远端" in prompt
    assert "1800—2500" in prompt
    assert "硬上限3000个可见字符" in prompt
    assert "以白底产品图作为唯一产品依据" in prompt
    assert "sofa_view" in user_prompt
    assert "positive_prompt" in user_prompt