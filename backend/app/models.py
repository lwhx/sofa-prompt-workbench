from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.enums import JobStatus, RowStatus


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: Text, list[str]: Text}


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="oneimg")
    status: Mapped[str] = mapped_column(String(32), default="UPLOADING")
    oneimg_image_id: Mapped[int | None] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(Text)
    stored_filename: Mapped[str | None] = mapped_column(Text)
    raw_url: Mapped[str | None] = mapped_column(Text)
    public_url: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    ai_cache_path: Mapped[str | None] = mapped_column(Text)
    ai_processing_json: Mapped[str | None] = mapped_column(Text)
    upload_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PromptRow(Base):
    __tablename__ = "prompt_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sort_key: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(Text, default="")
    scene_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    sofa_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    auto_run: Mapped[bool] = mapped_column(Boolean, default=True)
    include_person: Mapped[bool] = mapped_column(Boolean, default=False)
    person_action: Mapped[str] = mapped_column(String(32), default="none")
    output_platform: Mapped[str] = mapped_column(String(32), default="jimeng")
    prompt_length: Mapped[str] = mapped_column(String(32), default="standard")
    camera_preference: Mapped[str] = mapped_column(String(32), default="product_priority")
    custom_requirements: Mapped[str] = mapped_column(Text, default="")
    view_override_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    view_override_json: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RowStatus] = mapped_column(String(32), default=RowStatus.WAITING_IMAGES)
    row_revision: Mapped[int] = mapped_column(Integer, default=1)
    dirty: Mapped[bool] = mapped_column(Boolean, default=False)
    input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_success_fingerprint: Mapped[str | None] = mapped_column(String(64))
    latest_result_id: Mapped[str | None] = mapped_column(String(36))
    selected_result_id: Mapped[str | None] = mapped_column(String(36))
    active_job_id: Mapped[str | None] = mapped_column(String(36))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_template_version"),
        Index(
            "uq_prompt_templates_active",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt_template: Mapped[str] = mapped_column(Text)
    output_schema_json: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_jobs_active_row",
            "row_id",
            unique=True,
            sqlite_where=text(
                "status IN ('PENDING_DISPATCH','QUEUED','RUNNING','VALIDATING',"
                "'REPAIRING','CANCEL_REQUESTED')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    row_id: Mapped[str] = mapped_column(ForeignKey("prompt_rows.id"), index=True)
    status: Mapped[JobStatus] = mapped_column(String(32), default=JobStatus.PENDING_DISPATCH)
    rq_job_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    queue_name: Mapped[str] = mapped_column(String(64), default="prompt-generation")
    row_revision: Mapped[int] = mapped_column(Integer)
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    input_snapshot_json: Mapped[str] = mapped_column(Text)
    scene_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    sofa_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    current_stage: Mapped[str | None] = mapped_column(String(64))
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    redacted_response_json: Mapped[str | None] = mapped_column(Text)
    usage_json: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PromptResult(Base):
    __tablename__ = "prompt_results"
    __table_args__ = (UniqueConstraint("row_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    row_id: Mapped[str] = mapped_column(ForeignKey("prompt_rows.id"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))
    parent_result_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_results.id"))
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    result_payload_json: Mapped[str] = mapped_column(Text)
    sofa_view_json: Mapped[str] = mapped_column(Text)
    sofa_product_json: Mapped[str] = mapped_column(Text)
    scene_observations_json: Mapped[str] = mapped_column(Text)
    composition_plan_json: Mapped[str] = mapped_column(Text)
    review_json: Mapped[str] = mapped_column(Text)
    positive_prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str] = mapped_column(Text)
    warnings_json: Mapped[str] = mapped_column(Text)
    validation_json: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(32))
    row_revision: Mapped[int] = mapped_column(Integer)
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_edit_note: Mapped[str | None] = mapped_column(Text)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AutoRunIntent(Base):
    __tablename__ = "auto_run_intents"
    __table_args__ = (Index("ix_auto_run_intents_status_due_at", "status", "due_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    row_id: Mapped[str] = mapped_column(ForeignKey("prompt_rows.id"), unique=True)
    expected_revision: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class JobDispatchOutbox(Base):
    __tablename__ = "job_dispatch_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    queue_name: Mapped[str] = mapped_column(String(64))
    deterministic_rq_job_id: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_error: Mapped[str | None] = mapped_column(Text)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AICapabilityProfile(Base):
    __tablename__ = "ai_capability_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identity_hash: Mapped[str] = mapped_column(String(64), unique=True)
    base_url_normalized: Mapped[str] = mapped_column(Text)
    chat_path: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="UNTESTED")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("admin_users.id"))
    row_id: Mapped[str | None] = mapped_column(String(36))
    job_id: Mapped[str | None] = mapped_column(String(36))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
