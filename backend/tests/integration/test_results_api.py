import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.enums import RowStatus
from app.main import create_app
from app.models import AdminUser, Base, PromptResult, PromptRow
from app.security.password import hash_password


def make_client(tmp_path: Path) -> tuple[TestClient, object, PromptRow, PromptResult]:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'results-api.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AdminUser(username="admin", password_hash=hash_password("pw")))
        row = PromptRow(sort_key=10, name="结果任务", status=RowStatus.NEEDS_REVIEW)
        session.add(row)
        session.flush()
        payload = {
            "schema_version": 1,
            "positive_prompt": "米白色模块沙发，现代客厅",
            "negative_prompt": "镜像，强行转正",
        }
        result = PromptResult(
            row_id=row.id,
            version=1,
            source="ai",
            schema_version=1,
            result_payload_json=json.dumps(payload, ensure_ascii=False),
            sofa_view_json="{}",
            sofa_product_json="{}",
            scene_observations_json="{}",
            composition_plan_json="{}",
            review_json='{"required":true,"reasons":["方向不确定"]}',
            positive_prompt=payload["positive_prompt"],
            negative_prompt=payload["negative_prompt"],
            warnings_json="[]",
            validation_json="{}",
            review_status="NEEDS_REVIEW",
            row_revision=1,
            input_fingerprint="fp",
        )
        session.add(result)
        session.commit()
        session.refresh(row)
        session.refresh(result)
        session.expunge(row)
        session.expunge(result)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'results-api.db'}",
        session_secret="test-session-secret-at-least-32-bytes",
        secure_cookies=False,
    )
    client = TestClient(create_app(settings=settings, engine=engine))
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    client.headers["X-CSRF-Token"] = client.cookies.get("spw_csrf") or ""
    return client, engine, row, result


def test_result_history_returns_positive_and_negative_prompts(tmp_path: Path) -> None:
    client, _engine, row, _result = make_client(tmp_path)

    response = client.get(f"/api/v1/rows/{row.id}/results")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["positive_prompt"] == "米白色模块沙发，现代客厅"
    assert data[0]["negative_prompt"] == "镜像，强行转正"


def test_select_result_uses_revision_cas(tmp_path: Path) -> None:
    client, engine, row, result = make_client(tmp_path)

    response = client.post(
        f"/api/v1/rows/{row.id}/results/{result.id}/select",
        json={"expected_revision": 1},
    )

    assert response.status_code == 200
    with Session(engine) as session:  # type: ignore[arg-type]
        saved = session.get(PromptRow, row.id)
        assert saved is not None
        assert saved.selected_result_id == result.id
        assert saved.row_revision == 2


def test_delete_selected_result_promotes_latest_remaining_version(tmp_path: Path) -> None:
    client, engine, row, selected = make_client(tmp_path)
    with Session(engine) as session:  # type: ignore[arg-type]
        saved_row = session.get(PromptRow, row.id)
        assert saved_row is not None
        remaining = PromptResult(
            row_id=row.id, version=2, source="ai", schema_version=1,
            result_payload_json="{}", sofa_view_json="{}", sofa_product_json="{}",
            scene_observations_json="{}", composition_plan_json="{}", review_json="{}",
            positive_prompt="保留版本", negative_prompt="", warnings_json="[]",
            validation_json="{}", review_status="PASSED", row_revision=1,
            input_fingerprint="fp2",
        )
        session.add(remaining)
        session.flush()
        saved_row.selected_result_id = selected.id
        saved_row.latest_result_id = selected.id
        session.commit()
        remaining_id = remaining.id

    response = client.delete(f"/api/v1/rows/{row.id}/results/{selected.id}")

    assert response.status_code == 200
    with Session(engine) as session:  # type: ignore[arg-type]
        saved_row = session.get(PromptRow, row.id)
        assert saved_row is not None
        assert session.get(PromptResult, selected.id) is None
        assert saved_row.selected_result_id == remaining_id
        assert saved_row.latest_result_id == remaining_id


def test_delete_only_result_clears_result_references(tmp_path: Path) -> None:
    client, engine, row, result = make_client(tmp_path)
    with Session(engine) as session:  # type: ignore[arg-type]
        saved_row = session.get(PromptRow, row.id)
        assert saved_row is not None
        saved_row.selected_result_id = result.id
        saved_row.latest_result_id = result.id
        session.commit()

    response = client.delete(f"/api/v1/rows/{row.id}/results/{result.id}")

    assert response.status_code == 200
    with Session(engine) as session:  # type: ignore[arg-type]
        saved_row = session.get(PromptRow, row.id)
        assert saved_row is not None
        assert saved_row.selected_result_id is None
        assert saved_row.latest_result_id is None


def test_confirm_review_saves_override_and_returns_row_ready_for_successor_job(
    tmp_path: Path,
) -> None:
    client, engine, row, _result = make_client(tmp_path)

    response = client.post(
        f"/api/v1/rows/{row.id}/review/confirm",
        json={
            "expected_revision": 1,
            "view_override": {
                "view_type": "right_front_three_quarter",
                "near_end": "右侧",
                "far_end": "左侧",
            },
            "note": "人工确认",
        },
    )

    assert response.status_code == 200
    with Session(engine) as session:  # type: ignore[arg-type]
        saved = session.get(PromptRow, row.id)
        assert saved is not None
        assert saved.view_override_enabled is True
        assert saved.status == RowStatus.READY
        assert saved.row_revision == 2