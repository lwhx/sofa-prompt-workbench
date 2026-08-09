from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import create_database_engine
from app.models import AdminUser
from app.security.password import hash_password
from app.services.maintenance import maintenance_once


def create_admin(username: str, password: str) -> bool:
    normalized_username = username.strip()
    if not normalized_username:
        raise ValueError("管理员用户名不能为空")
    if len(normalized_username) > 100:
        raise ValueError("管理员用户名不能超过 100 个字符")
    if len(password) < 12:
        raise ValueError("管理员密码不能少于 12 个字符")

    engine = create_database_engine(get_settings().database_url)
    with Session(engine) as session:
        existing = session.scalar(
            select(AdminUser).where(AdminUser.username == normalized_username)
        )
        if existing is not None:
            return False
        session.add(
            AdminUser(
                username=normalized_username,
                password_hash=hash_password(password),
            )
        )
        session.commit()
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="沙发场景提示词工作台管理命令")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_admin_parser = subparsers.add_parser("create-admin", help="初始化管理员")
    create_admin_parser.add_argument("--username", required=True, help="管理员用户名")
    backup_parser = subparsers.add_parser("backup", help="执行数据库备份维护")
    backup_parser.add_argument(
        "action",
        choices=("create", "run", "status"),
        help="create 强制创建，run 按周期维护，status 查看最近备份健康信息",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "backup":
        settings = get_settings()
        try:
            if args.action == "status":
                from app.backup import backup_health

                result = backup_health(
                    settings.backup_dir,
                    rpo_hours=settings.backup_rpo_hours,
                )
            else:
                result = maintenance_once(
                    settings=settings,
                    force_backup=args.action == "create",
                )
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    password = getpass.getpass("请输入管理员密码：")
    confirmation = getpass.getpass("请再次输入管理员密码：")
    if password != confirmation:
        print("两次输入的密码不一致", file=sys.stderr)
        return 2

    try:
        created = create_admin(args.username, password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not created:
        print("管理员已存在，未重复创建")
        return 0
    print("管理员创建成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
