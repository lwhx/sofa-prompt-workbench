from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app.backup import backup_health


class RedisHealthClient(Protocol):
    def ping(self) -> bool: ...


def check_alembic_head(engine: Engine) -> dict[str, Any]:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())
    with engine.connect() as connection:
        current_heads = {
            str(row[0])
            for row in connection.execute(text("SELECT version_num FROM alembic_version"))
        }
    if current_heads != expected_heads:
        raise RuntimeError(
            f"数据库迁移版本不一致，当前={sorted(current_heads)}，期望={sorted(expected_heads)}"
        )
    return {"status": "ok", "revision": next(iter(expected_heads))}


def check_sqlite(engine: Engine) -> dict[str, Any]:
    if engine.dialect.name != "sqlite":
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "dialect": engine.dialect.name}
    with engine.connect() as connection:
        integrity = connection.exec_driver_sql("PRAGMA quick_check(1)").scalar_one()
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
        query_only = connection.exec_driver_sql("PRAGMA query_only").scalar_one()
    if integrity != "ok":
        raise RuntimeError(f"SQLite 完整性检查失败：{integrity}")
    if foreign_keys != 1:
        raise RuntimeError("SQLite 外键约束未启用")
    if query_only != 0:
        raise RuntimeError("SQLite 当前为只读模式")
    return {"status": "ok", "integrity": integrity, "writable": True}


def check_redis(client: RedisHealthClient, *, required: bool) -> dict[str, Any]:
    try:
        if not client.ping():
            raise RuntimeError("Redis PING 未返回成功")
    except Exception as exc:
        if required:
            raise RuntimeError("Redis 不可用") from exc
        return {"status": "degraded", "required": False}
    return {"status": "ok", "required": required}


def readiness_checks(
    engine: Engine,
    redis_client: RedisHealthClient,
    *,
    redis_required: bool,
    backup_root: Path | None = None,
    backup_rpo_hours: float = 24,
) -> tuple[bool, Mapping[str, dict[str, Any]]]:
    checks: dict[str, dict[str, Any]] = {}
    failures = False
    checkers: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
        ("alembic", lambda: check_alembic_head(engine)),
        ("sqlite", lambda: check_sqlite(engine)),
        ("redis", lambda: check_redis(redis_client, required=redis_required)),
    )
    for name, checker in checkers:
        try:
            checks[name] = checker()
        except Exception as exc:
            failures = True
            checks[name] = {"status": "error", "message": str(exc)}
    if backup_root is not None:
        checks["backup"] = backup_health(backup_root, rpo_hours=backup_rpo_hours)
    return not failures, checks
