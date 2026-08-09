from pathlib import Path

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from alembic import command
from app.config import Settings
from app.database import create_database_engine
from app.main import create_app


class FakeRedis:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def ping(self) -> bool:
        if not self.available:
            raise ConnectionError("测试 Redis 不可用")
        return True


def _migrate(database_path: Path) -> None:
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    config.attributes["preserve_config_url"] = True
    command.upgrade(config, "head")


def test_live_health_check_is_public() -> None:
    response = TestClient(create_app(redis_client=FakeRedis())).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_health_check_reports_dependencies(tmp_path: Path) -> None:
    database_path = tmp_path / "ready.db"
    _migrate(database_path)
    engine = create_database_engine(f"sqlite:///{database_path}")
    settings = Settings(database_url=f"sqlite:///{database_path}")

    response = TestClient(
        create_app(settings=settings, engine=engine, redis_client=FakeRedis())
    ).get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["alembic"]["revision"] == "0003"
    assert response.json()["checks"]["sqlite"]["writable"] is True
    assert response.json()["checks"]["redis"] == {"status": "ok", "required": True}
    assert response.json()["checks"]["backup"]["status"] == "degraded"


def test_ready_health_check_fails_when_redis_is_required(tmp_path: Path) -> None:
    database_path = tmp_path / "redis-required.db"
    _migrate(database_path)
    engine = create_database_engine(f"sqlite:///{database_path}")
    settings = Settings(database_url=f"sqlite:///{database_path}")

    response = TestClient(
        create_app(settings=settings, engine=engine, redis_client=FakeRedis(available=False))
    ).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["redis"]["status"] == "error"


def test_ready_health_check_degrades_when_optional_redis_is_unavailable(tmp_path: Path) -> None:
    database_path = tmp_path / "redis-optional.db"
    _migrate(database_path)
    engine = create_database_engine(f"sqlite:///{database_path}")
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        health_redis_required=False,
    )

    response = TestClient(
        create_app(settings=settings, engine=engine, redis_client=FakeRedis(available=False))
    ).get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["redis"] == {"status": "degraded", "required": False}


def test_ready_health_check_fails_when_database_is_behind_head(tmp_path: Path) -> None:
    database_path = tmp_path / "old-revision.db"
    _migrate(database_path)
    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='0001'"))
    settings = Settings(database_url=f"sqlite:///{database_path}")

    response = TestClient(
        create_app(settings=settings, engine=engine, redis_client=FakeRedis())
    ).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["alembic"]["status"] == "error"
