from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.backup import (
    backup_health,
    cleanup_database_backups,
    create_verified_database_backup,
    list_database_backups,
    read_alembic_revision,
    sqlite_database_path,
)
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def maintenance_once(
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    force_backup: bool = False,
) -> dict[str, Any]:
    """执行一次本地备份与保留清理，不访问 Redis 或其他网络服务。"""
    app_settings = settings or get_settings()
    current_time = now or datetime.now(UTC)
    if not app_settings.backup_enabled:
        return {"status": "disabled", "created": False, "removed": 0}

    source_database = sqlite_database_path(app_settings.database_url)
    backups = list_database_backups(app_settings.backup_dir)
    latest_created_at = (
        datetime.fromisoformat(str(backups[0].manifest["createdAt"])) if backups else None
    )
    if latest_created_at is not None and latest_created_at.tzinfo is None:
        latest_created_at = latest_created_at.replace(tzinfo=UTC)
    due = (
        force_backup
        or latest_created_at is None
        or current_time
        >= latest_created_at + timedelta(hours=app_settings.backup_interval_hours)
    )
    bundle = None
    if due:
        bundle = create_verified_database_backup(
            source_database=source_database,
            backup_root=app_settings.backup_dir,
            app_version="1.0.0",
            alembic_revision=read_alembic_revision(source_database),
        )
    removed = cleanup_database_backups(
        app_settings.backup_dir,
        retention_count=app_settings.backup_retention_count,
    )
    health = backup_health(
        app_settings.backup_dir,
        rpo_hours=app_settings.backup_rpo_hours,
        now=current_time,
    )
    return {
        "status": health["status"],
        "created": bundle is not None,
        "createdPath": str(bundle.root) if bundle is not None else None,
        "removed": len(removed),
        "health": health,
    }


def run_maintenance_forever() -> None:
    """按配置周期运行维护；失败后记录错误并在下一周期重试。"""
    while True:
        settings = get_settings()
        try:
            result = maintenance_once(settings=settings)
            logger.info(
                "维护执行完成：status=%s created=%s removed=%s",
                result["status"],
                result["created"],
                result["removed"],
            )
        except Exception:
            logger.exception("维护执行失败")
        time.sleep(settings.maintenance_interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_maintenance_forever()
