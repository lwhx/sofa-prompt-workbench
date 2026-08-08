from __future__ import annotations

from types import SimpleNamespace

from app.services import dispatcher


def test_local_inline_mode_dispatches_without_redis(monkeypatch) -> None:
    """本地直执行模式不得建立 Redis 连接，并应直接执行待派发任务。"""
    executed_jobs: list[str] = []
    fake_settings = SimpleNamespace(
        local_inline_worker=True,
        ai_timeout_seconds=240,
    )
    fake_session = object()

    class FakeSessionContext:
        """提供 Dispatcher 所需的最小 Session 上下文。"""

        def __init__(self, _engine: object) -> None:
            """保存构造参数以匹配 SQLAlchemy Session 接口。"""

        def __enter__(self) -> object:
            """返回测试 Session。"""
            return fake_session

        def __exit__(self, *_args: object) -> None:
            """结束测试 Session 上下文。"""

    def fake_dispatch(session: object, *, enqueue) -> int:
        """模拟 Outbox 派发并触发执行回调。"""
        assert session is fake_session
        enqueue("job-1", "prompt-generation")
        return 1

    monkeypatch.setattr(dispatcher, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(dispatcher, "_get_engine", lambda: object())
    monkeypatch.setattr(
        dispatcher,
        "_get_redis",
        lambda: (_ for _ in ()).throw(AssertionError("本地直执行模式不应连接 Redis")),
    )
    monkeypatch.setattr(dispatcher, "Session", FakeSessionContext)
    monkeypatch.setattr(dispatcher, "dispatch_pending_outbox", fake_dispatch)
    monkeypatch.setattr(dispatcher, "run_prompt_job", executed_jobs.append)
    monkeypatch.setattr(dispatcher, "reap_stale_jobs", lambda _session: 0)

    dispatched = dispatcher.dispatch_once()

    assert dispatched == 1
    assert executed_jobs == ["job-1"]
