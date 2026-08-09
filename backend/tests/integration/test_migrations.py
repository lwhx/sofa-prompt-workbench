from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
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
    inspector = inspect(create_engine(f"sqlite:///{database_path}"))
    columns = {column["name"] for column in inspector.get_columns("auto_run_intents")}
    indexes = {index["name"] for index in inspector.get_indexes("auto_run_intents")}
    assert {"claim_token", "lease_expires_at", "attempt_count", "last_error"} <= columns
    assert "ix_auto_run_intents_status_due_at" in indexes
    result_columns = {column["name"] for column in inspector.get_columns("prompt_results")}
    assert "hidden_at" in result_columns


def test_alembic_has_exactly_one_head() -> None:
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1
