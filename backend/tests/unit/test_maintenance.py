from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import Settings
from app.services.maintenance import maintenance_once


def migrate_database(database_path: Path) -> None:
    """创建具备当前 Alembic 版本的测试数据库。"""
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")


def test_maintenance_creates_due_backup_and_skips_fresh_backup(tmp_path: Path) -> None:
    """维护任务仅在到期时创建备份，并始终返回最近备份健康信息。"""
    database_path = tmp_path / "maintenance.db"
    backup_root = tmp_path / "backups"
    migrate_database(database_path)
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        backup_dir=backup_root,
        backup_interval_hours=24,
        backup_retention_count=2,
        backup_rpo_hours=24,
    )
    now = datetime.now(UTC)

    first = maintenance_once(settings=settings, now=now)
    second = maintenance_once(settings=settings, now=now + timedelta(hours=1))

    assert first["created"] is True
    assert first["health"]["status"] == "ok"
    assert second["created"] is False
    assert second["health"]["backupCount"] == 1


def test_force_backup_bypasses_interval(tmp_path: Path) -> None:
    """CLI 强制备份语义不受定时间隔限制。"""
    database_path = tmp_path / "forced.db"
    backup_root = tmp_path / "backups"
    migrate_database(database_path)
    settings = Settings(database_url=f"sqlite:///{database_path}", backup_dir=backup_root)
    now = datetime.now(UTC)
    maintenance_once(settings=settings, now=now)

    result = maintenance_once(settings=settings, now=now, force_backup=True)

    assert result["created"] is True
    assert result["health"]["backupCount"] == 2
