import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.enums import RowStatus
from app.main import create_app
from app.models import AdminUser, Asset, AuditEvent, AutoRunIntent, Base, PromptResult, PromptRow
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
        audit = session.query(AuditEvent).filter_by(event_type="RESULT_SELECTED").one()
        assert audit.row_id == row.id
        assert json.loads(audit.details_json)["result_id"] == result.id


def test_delete_selected_result_is_protected(tmp_path: Path) -> None:
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

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELECTED_RESULT_PROTECTED"
    with Session(engine) as session:  # type: ignore[arg-type]
        saved_row = session.get(PromptRow, row.id)
        assert saved_row is not None
        saved_result = session.get(PromptResult, selected.id)
        assert saved_result is not None
        assert saved_result.hidden_at is None
        assert saved_row.selected_result_id == selected.id
        assert remaining_id is not None


def test_delete_result_soft_hides_and_filters_it_from_history(tmp_path: Path) -> None:
    client, engine, row, result = make_client(tmp_path)
    with Session(engine) as session:  # type: ignore[arg-type]
        saved_row = session.get(PromptRow, row.id)
        assert saved_row is not None
        saved_row.latest_result_id = result.id
        session.commit()

    response = client.delete(f"/api/v1/rows/{row.id}/results/{result.id}")

    assert response.status_code == 200
    with Session(engine) as session:  # type: ignore[arg-type]
        saved_row = session.get(PromptRow, row.id)
        assert saved_row is not None
        saved_result = session.get(PromptResult, result.id)
        assert saved_result is not None
        assert saved_result.hidden_at is not None
        assert saved_row.latest_result_id is None
    listed = client.get(f"/api/v1/rows/{row.id}/results")
    assert listed.json()["data"] == []


def test_confirm_review_saves_override_and_returns_row_ready_for_successor_job(
    tmp_path: Path,
) -> None:
    client, engine, row, _result = make_client(tmp_path)

    response = client.post(
        f"/api/v1/rows/{row.id}/review/confirm",
        json={
            "expected_revision": 1,
            "result_id": _result.id,
            "view_override": {
                "view_type": "right_front_three_quarter",
                "near_end": "右侧",
                "far_end": "左侧",
            },
            "note": "人工确认",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "READY"
    with Session(engine) as session:  # type: ignore[arg-type]
        saved = session.get(PromptRow, row.id)
        assert saved is not None
        assert saved.view_override_enabled is True
        assert saved.status == RowStatus.READY
        assert saved.row_revision == 2
        saved_result = session.get(PromptResult, _result.id)
        assert saved_result is not None
        assert saved_result.review_status == "CONFIRMED"
        audit = session.query(AuditEvent).filter_by(event_type="REVIEW_CONFIRMED").one()
        assert audit.row_id == row.id
        assert json.loads(audit.details_json)["view_type"] == "right_front_three_quarter"


def test_confirm_review_triggers_auto_run_intent_when_row_is_ready(tmp_path: Path) -> None:
    """审核确认后应根据自动运行配置创建后继任务意图。"""
    client, engine, row, _result = make_client(tmp_path)
    with Session(engine) as session:  # type: ignore[arg-type]
        saved = session.get(PromptRow, row.id)
        assert saved is not None
        scene = Asset(
            kind="scene_reference",
            status="READY",
            original_filename="scene.png",
        )
        sofa = Asset(
            kind="sofa_product",
            status="READY",
            original_filename="sofa.png",
        )
        session.add_all((scene, sofa))
        session.flush()
        saved.scene_asset_id = scene.id
        saved.sofa_asset_id = sofa.id
        saved.auto_run = True
        session.commit()

    response = client.post(
        f"/api/v1/rows/{row.id}/review/confirm",
        json={
            "expected_revision": 1,
            "view_override": {
                "view_type": "right_front_three_quarter",
                "near_end": "右侧",
                "far_end": "左侧",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "DEBOUNCING"
    with Session(engine) as session:  # type: ignore[arg-type]
        saved = session.get(PromptRow, row.id)
        intent = session.query(AutoRunIntent).filter_by(row_id=row.id).one()
        assert saved is not None
        assert saved.status == RowStatus.DEBOUNCING
        assert intent.expected_revision == 2
        assert intent.status == "PENDING"
