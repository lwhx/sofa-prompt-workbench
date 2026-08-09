from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BackupBundle:
    """描述一个已落盘的数据库备份包。"""

    root: Path
    database_file: Path
    manifest_file: Path
    manifest: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_database_path(database_url: str) -> Path:
    """从 SQLite URL 解析数据库文件路径。"""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("数据库备份仅支持 SQLite 文件数据库")
    raw_path = database_url.removeprefix(prefix)
    if not raw_path or raw_path == ":memory:":
        raise ValueError("数据库备份不支持内存数据库")
    return Path(raw_path).resolve()


def read_alembic_revision(source_database: Path) -> str:
    """直接读取数据库当前 Alembic 版本，不创建业务事务。"""
    with closing(sqlite3.connect(source_database)) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None or not row[0]:
        raise ValueError("数据库缺少 Alembic 版本信息")
    return str(row[0])


def _sqlite_checks(path: Path) -> tuple[bool, bool, dict[str, int]]:
    connection = sqlite3.connect(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall() == []
        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in table_names
        }
    finally:
        connection.close()
    return integrity, foreign_keys, counts


def create_verified_database_backup(
    *,
    source_database: Path,
    backup_root: Path,
    app_version: str,
    alembic_revision: str,
) -> BackupBundle:
    """使用 SQLite Backup API 创建并隔离验证数据库备份。"""
    created_at = datetime.now(UTC)
    backup_root.mkdir(parents=True, exist_ok=True)
    bundle_root = backup_root / created_at.strftime("%Y%m%dT%H%M%S.%fZ")
    bundle_root.mkdir(parents=True, exist_ok=False)
    try:
        database_file = bundle_root / "sofa_prompt_workbench.db"
        with (
            closing(sqlite3.connect(source_database)) as source,
            closing(sqlite3.connect(database_file)) as target,
        ):
            source.backup(target)

        expected_hash = _sha256(database_file)
        integrity, foreign_keys, counts = _sqlite_checks(database_file)
        with tempfile.TemporaryDirectory(dir=backup_root) as temp_dir:
            isolated_copy = Path(temp_dir) / "restore.db"
            shutil.copy2(database_file, isolated_copy)
            isolated_hash = _sha256(isolated_copy)
            restored_integrity, restored_foreign_keys, restored_counts = _sqlite_checks(
                isolated_copy
            )

        manifest: dict[str, Any] = {
            "scope": "database",
            "createdAt": created_at.isoformat(),
            "appVersion": app_version,
            "alembicRevision": alembic_revision,
            "databaseSize": database_file.stat().st_size,
            "databaseSha256": expected_hash,
            "tableCounts": counts,
            "integrityCheck": integrity,
            "foreignKeyCheck": foreign_keys,
            "checksumsVerified": expected_hash == isolated_hash,
            "databaseRestoreVerified": restored_integrity and restored_foreign_keys,
            "objectInventoryVerified": False,
            "restoreSmokeVerified": restored_counts == counts,
            "objectInventory": [],
        }
        manifest_file = bundle_root / "manifest.json"
        manifest_file.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        return BackupBundle(bundle_root, database_file, manifest_file, manifest)
    except Exception:
        shutil.rmtree(bundle_root, ignore_errors=True)
        raise


def list_database_backups(backup_root: Path) -> list[BackupBundle]:
    """读取可识别的备份包，并按创建时间从新到旧排序。"""
    if not backup_root.exists():
        return []
    bundles: list[BackupBundle] = []
    for bundle_root in backup_root.iterdir():
        manifest_file = bundle_root / "manifest.json"
        database_file = bundle_root / "sofa_prompt_workbench.db"
        if not bundle_root.is_dir() or not manifest_file.is_file() or not database_file.is_file():
            continue
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            datetime.fromisoformat(str(manifest["createdAt"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        bundles.append(BackupBundle(bundle_root, database_file, manifest_file, manifest))
    return sorted(
        bundles,
        key=lambda bundle: datetime.fromisoformat(str(bundle.manifest["createdAt"])),
        reverse=True,
    )


def backup_health(
    backup_root: Path,
    *,
    rpo_hours: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """返回最近数据库备份的验证状态和 RPO 新鲜度。"""
    current_time = now or datetime.now(UTC)
    bundles = list_database_backups(backup_root)
    if not bundles:
        return {"status": "degraded", "message": "尚无可用数据库备份", "backupCount": 0}
    latest = bundles[0]
    created_at = datetime.fromisoformat(str(latest.manifest["createdAt"]))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    age_hours = max(0.0, (current_time - created_at).total_seconds() / 3600)
    verified = all(
        latest.manifest.get(key) is True
        for key in ("checksumsVerified", "databaseRestoreVerified", "restoreSmokeVerified")
    )
    # 重新校验最新备份文件的实际校验和，防止文件在创建后被篡改或损坏
    try:
        checksum_verified = (
            _sha256(latest.database_file) == latest.manifest["databaseSha256"]
        )
    except (KeyError, OSError, TypeError):
        checksum_verified = False
    verified = verified and checksum_verified
    fresh = age_hours <= rpo_hours
    return {
        "status": "ok" if verified and fresh else "degraded",
        "backupCount": len(bundles),
        "latestCreatedAt": created_at.isoformat(),
        "latestAgeHours": round(age_hours, 3),
        "latestVerified": verified,
        "rpoHours": rpo_hours,
        "path": str(latest.root),
    }


def cleanup_database_backups(backup_root: Path, *, retention_count: int) -> list[Path]:
    """保留最新指定数量的有效备份包并删除更旧备份。"""
    if retention_count < 1:
        raise ValueError("备份保留数量必须至少为 1")
    expired = list_database_backups(backup_root)[retention_count:]
    removed: list[Path] = []
    for bundle in expired:
        shutil.rmtree(bundle.root)
        removed.append(bundle.root)
    return removed


def restore_database_backup(
    *, bundle: BackupBundle, target_database: Path, require_object_inventory: bool = False
) -> Path:
    """验证备份包后原子替换目标数据库并保留恢复前副本。"""
    required_checks = ["checksumsVerified", "databaseRestoreVerified", "restoreSmokeVerified"]
    if require_object_inventory:
        required_checks.append("objectInventoryVerified")
    if not all(bundle.manifest.get(key) is True for key in required_checks):
        raise ValueError("备份尚未通过所需验证")
    if _sha256(bundle.database_file) != bundle.manifest["databaseSha256"]:
        raise ValueError("备份校验和不匹配")
    target_database.parent.mkdir(parents=True, exist_ok=True)
    pre_restore = target_database.with_name(
        f"{target_database.name}.pre-restore-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    if target_database.exists():
        shutil.copy2(target_database, pre_restore)
    else:
        pre_restore.touch()
    temporary = target_database.with_suffix(target_database.suffix + ".restoring")
    shutil.copy2(bundle.database_file, temporary)
    integrity, foreign_keys, _ = _sqlite_checks(temporary)
    if not integrity or not foreign_keys:
        temporary.unlink(missing_ok=True)
        raise ValueError("恢复文件完整性验证失败")
    os.replace(temporary, target_database)
    target_database.with_name(target_database.name + "-wal").unlink(missing_ok=True)
    target_database.with_name(target_database.name + "-shm").unlink(missing_ok=True)
    return pre_restore
