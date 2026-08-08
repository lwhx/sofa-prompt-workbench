from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrades_an_empty_file_database(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.db"
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    tables = set(inspect(create_engine(f"sqlite:///{database_path}")).get_table_names())
    assert {"prompt_rows", "jobs", "prompt_results", "job_dispatch_outbox"} <= tables
    assert "alembic_version" in tables
