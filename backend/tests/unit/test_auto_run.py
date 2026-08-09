from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import create_database_engine
from app.enums import JobStatus, RowStatus
from app.models import (
    Asset,
    AutoRunIntent,
    Base,
    Job,
    JobDispatchOutbox,
    PromptResult,
    PromptRow,
)
from app.services import auto_run


def make_session(tmp_path: Path) -> Session:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'auto-run.db'}")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_ready_row(session: Session, *, revision: int = 1) -> PromptRow:
    scene = Asset(
        kind="scene_reference",
        status="READY",
        original_filename="scene.png",
        public_url="https://example.com/scene.png",
        sha256="scene-sha",
    )
    sofa = Asset(
        kind="sofa_product",
        status="READY",
        original_filename="sofa.png",
        public_url="https://example.com/sofa.png",
        sha256="sofa-sha",
    )
    session.add_all((scene, sofa))
    session.flush()
    row = PromptRow(
        sort_key=10,
        name="自动运行",
        row_revision=revision,
        scene_asset_id=scene.id,
        sofa_asset_id=sofa.id,
        status=RowStatus.READY,
    )
    session.add(row)
    session.commit()
    return row


def test_upsert_resets_claim_and_extends_debounce(tmp_path: Path) -> None:
    with make_session(tmp_path) as session:
        row = make_ready_row(session)
        auto_run.upsert_auto_run_intent(session, row, debounce_seconds=3)
        session.commit()
        intent = session.scalar(select(AutoRunIntent).where(AutoRunIntent.row_id == row.id))
        assert intent is not None
        first_due_at = intent.due_at
        intent.status = "CLAIMED"
        intent.claim_token = "old-token"
        row.row_revision = 2
        session.commit()

        auto_run.upsert_auto_run_intent(session, row, debounce_seconds=30)
        session.commit()
        session.refresh(intent)

        assert intent.expected_revision == 2
        assert intent.status == "PENDING"
        assert intent.claim_token is None
        assert intent.due_at > first_due_at
        assert row.status == RowStatus.DEBOUNCING


def test_due_intent_creates_job_and_outbox_and_is_consumed(tmp_path: Path, monkeypatch) -> None:
    with make_session(tmp_path) as session:
        row = make_ready_row(session, revision=4)
        intent = AutoRunIntent(
            row_id=row.id,
            expected_revision=4,
            due_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(intent)
        session.commit()
        monkeypatch.setattr(
            auto_run,
            "freeze_job_input",
            lambda _session, _row, _settings: SimpleNamespace(
                fingerprint="frozen-fingerprint",
                snapshot={"row_id": row.id, "row_revision": 4},
            ),
        )

        consumed = auto_run.consume_due_auto_run_intents(
            session,
            settings=SimpleNamespace(auto_run_lease_seconds=120),
        )

        session.expire_all()
        persisted_intent = session.get(AutoRunIntent, intent.id)
        job = session.scalar(select(Job).where(Job.row_id == row.id))
        assert consumed == 1
        assert persisted_intent is not None
        assert persisted_intent.status == "CONSUMED"
        assert persisted_intent.claim_token is None
        assert job is not None
        assert job.status == JobStatus.PENDING_DISPATCH
        assert session.scalar(
            select(JobDispatchOutbox).where(JobDispatchOutbox.job_id == job.id)
        ) is not None


def test_expired_claim_is_recovered_and_stale_revision_does_not_create_job(
    tmp_path: Path,
) -> None:
    with make_session(tmp_path) as session:
        row = make_ready_row(session, revision=2)
        intent = AutoRunIntent(
            row_id=row.id,
            expected_revision=1,
            due_at=datetime.now(UTC) - timedelta(minutes=5),
            status="CLAIMED",
            claim_token="abandoned-token",
            lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        session.add(intent)
        session.commit()

        consumed = auto_run.consume_due_auto_run_intents(
            session,
            settings=SimpleNamespace(auto_run_lease_seconds=120),
        )

        session.refresh(intent)
        assert consumed == 0
        assert intent.status == "STALE"
        assert intent.claim_token is None
        assert session.scalar(select(Job).where(Job.row_id == row.id)) is None


def test_due_intent_reuses_result_and_converges_row_state(tmp_path: Path, monkeypatch) -> None:
    """自动运行复用既有结果时必须同步收敛任务行状态。"""
    with make_session(tmp_path) as session:
        row = make_ready_row(session, revision=3)
        row.status = RowStatus.DEBOUNCING
        row.dirty = True
        result = PromptResult(
            row_id=row.id,
            version=1,
            source="ai",
            schema_version=1,
            result_payload_json="{}",
            sofa_view_json="{}",
            sofa_product_json="{}",
            scene_observations_json="{}",
            composition_plan_json="{}",
            review_json="{}",
            positive_prompt="已复用",
            negative_prompt="",
            warnings_json="[]",
            validation_json="{}",
            review_status="PASSED",
            row_revision=3,
            input_fingerprint="reusable-fingerprint",
        )
        intent = AutoRunIntent(
            row_id=row.id,
            expected_revision=3,
            due_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add_all((result, intent))
        session.commit()
        monkeypatch.setattr(
            auto_run,
            "freeze_job_input",
            lambda _session, _row, _settings: SimpleNamespace(
                fingerprint="reusable-fingerprint",
                snapshot={"row_id": row.id, "row_revision": 3},
            ),
        )

        consumed = auto_run.consume_due_auto_run_intents(
            session,
            settings=SimpleNamespace(auto_run_lease_seconds=120),
        )

        session.refresh(row)
        session.refresh(intent)
        assert consumed == 0
        assert intent.status == "CONSUMED"
        assert row.status == RowStatus.COMPLETED
        assert row.latest_result_id == result.id
        assert row.selected_result_id == result.id
        assert row.input_fingerprint == "reusable-fingerprint"
        assert row.last_success_fingerprint == "reusable-fingerprint"
        assert row.dirty is False
        assert session.scalar(select(Job).where(Job.row_id == row.id)) is None
