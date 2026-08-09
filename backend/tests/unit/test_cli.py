from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cli
from app.config import Settings
from app.database import create_database_engine
from app.models import AdminUser, Base
from app.security.password import verify_password


def configure_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    database_url = f"sqlite:///{tmp_path / 'cli.db'}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(database_url=database_url))
    return database_url


def test_create_admin_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database_url = configure_database(monkeypatch, tmp_path)

    assert cli.create_admin("admin", "correct horse battery staple") is True
    assert cli.create_admin("admin", "another secure password") is False

    engine = create_database_engine(database_url)
    with Session(engine) as session:
        users = list(session.scalars(select(AdminUser)))
    assert len(users) == 1
    assert verify_password(users[0].password_hash, "correct horse battery staple")


def test_create_admin_rejects_weak_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure_database(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="不能少于 12 个字符"):
        cli.create_admin("admin", "too-short")


def test_main_does_not_echo_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_database(monkeypatch, tmp_path)
    answers = iter(["correct horse battery staple", "correct horse battery staple"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))

    assert cli.main(["create-admin", "--username", "admin"]) == 0
    captured = capsys.readouterr()
    assert "创建成功" in captured.out
    assert "correct horse battery staple" not in captured.out + captured.err


def test_backup_status_command_outputs_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """备份状态命令输出可供运维脚本消费的 JSON。"""
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(backup_dir=tmp_path / "backups", backup_rpo_hours=24),
    )

    assert cli.main(["backup", "status"]) == 0
    captured = capsys.readouterr()
    assert '"status": "degraded"' in captured.out
    assert '"backupCount": 0' in captured.out
