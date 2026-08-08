from pathlib import Path

from sqlalchemy.orm import Session

from app.backup import create_verified_database_backup, restore_database_backup
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
