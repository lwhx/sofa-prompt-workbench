from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BackupBundle:
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
    created_at = datetime.now(UTC)
    bundle_root = backup_root / created_at.strftime("%Y%m%dT%H%M%S.%fZ")
    bundle_root.mkdir(parents=True, exist_ok=False)
    database_file = bundle_root / "sofa_prompt_workbench.db"
    with sqlite3.connect(source_database) as source, sqlite3.connect(database_file) as target:
        source.backup(target)

    expected_hash = _sha256(database_file)
    integrity, foreign_keys, counts = _sqlite_checks(database_file)
    with tempfile.TemporaryDirectory(dir=backup_root) as temp_dir:
        isolated_copy = Path(temp_dir) / "restore.db"
        shutil.copy2(database_file, isolated_copy)
        isolated_hash = _sha256(isolated_copy)
        restored_integrity, restored_foreign_keys, restored_counts = _sqlite_checks(isolated_copy)

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


def restore_database_backup(
    *, bundle: BackupBundle, target_database: Path, require_object_inventory: bool = False
) -> Path:
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
