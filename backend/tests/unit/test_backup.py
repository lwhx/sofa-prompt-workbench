import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.backup import (
    backup_health,
    cleanup_database_backups,
    create_verified_database_backup,
    restore_database_backup,
)
from app.database import create_database_engine
from app.models import Base, PromptRow


def create_source_database(path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(PromptRow(sort_key=10, name="备份样例"))
        session.commit()
    engine.dispose()


def test_backup_manifest_is_verified_by_isolated_restore(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    create_source_database(source)

    bundle = create_verified_database_backup(
        source_database=source,
        backup_root=tmp_path / "backups",
        app_version="1.0.0",
        alembic_revision="0001",
    )

    assert bundle.database_file.exists()
    assert bundle.manifest_file.exists()
    assert bundle.manifest["checksumsVerified"] is True
    assert bundle.manifest["databaseRestoreVerified"] is True
    assert bundle.manifest["restoreSmokeVerified"] is True
    assert bundle.manifest["objectInventoryVerified"] is False
    assert bundle.manifest["tableCounts"]["prompt_rows"] == 1


def test_restore_replaces_target_and_preserves_pre_restore_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    create_source_database(source)
    create_source_database(target)
    bundle = create_verified_database_backup(
        source_database=source,
        backup_root=tmp_path / "backups",
        app_version="1.0.0",
        alembic_revision="0001",
    )

    pre_restore = restore_database_backup(bundle=bundle, target_database=target)

    assert pre_restore.exists()
    engine = create_database_engine(f"sqlite:///{target}")
    with Session(engine) as session:
        assert [row.name for row in session.query(PromptRow).all()] == ["备份样例"]


def test_cleanup_keeps_latest_verified_backups(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup_root = tmp_path / "backups"
    create_source_database(source)
    bundles = [
        create_verified_database_backup(
            source_database=source,
            backup_root=backup_root,
            app_version="1.0.0",
            alembic_revision="0001",
        )
        for _index in range(3)
    ]

    removed = cleanup_database_backups(backup_root, retention_count=2)

    assert removed == [bundles[0].root]
    assert not bundles[0].root.exists()
    assert bundles[1].root.exists()
    assert bundles[2].root.exists()


def test_backup_health_reports_stale_and_unverified_latest_backup(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup_root = tmp_path / "backups"
    create_source_database(source)
    bundle = create_verified_database_backup(
        source_database=source,
        backup_root=backup_root,
        app_version="1.0.0",
        alembic_revision="0001",
    )
    manifest = dict(bundle.manifest)
    manifest["createdAt"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    manifest["checksumsVerified"] = False
    bundle.manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    health = backup_health(backup_root, rpo_hours=24)

    assert health["status"] == "degraded"
    assert health["latestVerified"] is False
    assert health["latestAgeHours"] >= 25


def test_backup_health_reports_modified_database_file(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup_root = tmp_path / "backups"
    create_source_database(source)
    bundle = create_verified_database_backup(
        source_database=source,
        backup_root=backup_root,
        app_version="1.0.0",
        alembic_revision="0001",
    )
    with bundle.database_file.open("ab") as handle:
        handle.write(b"modified")

    health = backup_health(backup_root, rpo_hours=24)

    assert health["status"] == "degraded"
    assert health["latestVerified"] is False
