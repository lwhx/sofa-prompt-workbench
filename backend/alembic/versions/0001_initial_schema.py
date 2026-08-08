"""初始化数据库结构。

Revision ID: 0001
Revises:
Create Date: 2026-08-03
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# Alembic 修订版本标识。
revision: str = "0001"
# 初始迁移没有前置版本。
down_revision: str | None = None
# 当前迁移不属于分支。
branch_labels: str | None = None
# 当前迁移没有额外依赖。
depends_on: str | None = None


def upgrade() -> None:
    """显式创建应用所需的全部表、约束和索引。"""
    op.create_table(
        "admin_users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("oneimg_image_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_filename", sa.Text(), nullable=True),
        sa.Column("raw_url", sa.Text(), nullable=True),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("ai_cache_path", sa.Text(), nullable=True),
        sa.Column("ai_processing_json", sa.Text(), nullable=True),
        sa.Column("upload_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_assets_sha256"), "assets", ["sha256"], unique=False)
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt_template", sa.Text(), nullable=False),
        sa.Column("output_schema_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_prompt_template_version"),
    )
    op.create_index(
        "uq_prompt_templates_active",
        "prompt_templates",
        ["is_active"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
    )
    op.create_table(
        "ai_capability_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("base_url_normalized", sa.Text(), nullable=False),
        sa.Column("chat_path", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_hash"),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("encrypted", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_admin_sessions_expires_at"),
        "admin_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_sessions_user_id"), "admin_sessions", ["user_id"], unique=False
    )
    op.create_table(
        "prompt_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sort_key", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scene_asset_id", sa.String(length=36), nullable=True),
        sa.Column("sofa_asset_id", sa.String(length=36), nullable=True),
        sa.Column("auto_run", sa.Boolean(), nullable=False),
        sa.Column("include_person", sa.Boolean(), nullable=False),
        sa.Column("person_action", sa.String(length=32), nullable=False),
        sa.Column("output_platform", sa.String(length=32), nullable=False),
        sa.Column("prompt_length", sa.String(length=32), nullable=False),
        sa.Column("camera_preference", sa.String(length=32), nullable=False),
        sa.Column("custom_requirements", sa.Text(), nullable=False),
        sa.Column("view_override_enabled", sa.Boolean(), nullable=False),
        sa.Column("view_override_json", sa.Text(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("row_revision", sa.Integer(), nullable=False),
        sa.Column("dirty", sa.Boolean(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("last_success_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("latest_result_id", sa.String(length=36), nullable=True),
        sa.Column("selected_result_id", sa.String(length=36), nullable=True),
        sa.Column("active_job_id", sa.String(length=36), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scene_asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["sofa_asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_prompt_rows_sort_key"), "prompt_rows", ["sort_key"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("row_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_events_event_type"), "audit_events", ["event_type"], unique=False
    )
    op.create_table(
        "auto_run_intents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("row_id", sa.String(length=36), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["row_id"], ["prompt_rows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("row_id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("row_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("rq_job_id", sa.String(length=64), nullable=True),
        sa.Column("queue_name", sa.String(length=64), nullable=False),
        sa.Column("row_revision", sa.Integer(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_snapshot_json", sa.Text(), nullable=False),
        sa.Column("scene_asset_id", sa.String(length=36), nullable=True),
        sa.Column("sofa_asset_id", sa.String(length=36), nullable=True),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["row_id"], ["prompt_rows.id"]),
        sa.ForeignKeyConstraint(["scene_asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["sofa_asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rq_job_id"),
    )
    op.create_index(op.f("ix_jobs_row_id"), "jobs", ["row_id"], unique=False)
    op.create_index(
        "uq_jobs_active_row",
        "jobs",
        ["row_id"],
        unique=True,
        sqlite_where=sa.text(
            "status IN ('PENDING_DISPATCH','QUEUED','RUNNING','VALIDATING',"
            "'REPAIRING','CANCEL_REQUESTED')"
        ),
    )
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_request_id", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("redacted_response_json", sa.Text(), nullable=True),
        sa.Column("usage_json", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_no"),
    )
    op.create_table(
        "job_dispatch_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("queue_name", sa.String(length=64), nullable=False),
        sa.Column("deterministic_rq_job_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deterministic_rq_job_id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_table(
        "prompt_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("row_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("parent_result_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("result_payload_json", sa.Text(), nullable=False),
        sa.Column("sofa_view_json", sa.Text(), nullable=False),
        sa.Column("sofa_product_json", sa.Text(), nullable=False),
        sa.Column("scene_observations_json", sa.Text(), nullable=False),
        sa.Column("composition_plan_json", sa.Text(), nullable=False),
        sa.Column("review_json", sa.Text(), nullable=False),
        sa.Column("positive_prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("row_revision", sa.Integer(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("is_stale", sa.Boolean(), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_edit_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["parent_result_id"], ["prompt_results.id"]),
        sa.ForeignKeyConstraint(["row_id"], ["prompt_rows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("row_id", "version"),
    )


def downgrade() -> None:
    """按依赖关系的反向顺序删除全部表和显式索引。"""
    op.drop_table("prompt_results")
    op.drop_table("job_dispatch_outbox")
    op.drop_table("job_attempts")
    op.drop_index("uq_jobs_active_row", table_name="jobs")
    op.drop_index(op.f("ix_jobs_row_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("auto_run_intents")
    op.drop_index(op.f("ix_audit_events_event_type"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_prompt_rows_sort_key"), table_name="prompt_rows")
    op.drop_table("prompt_rows")
    op.drop_index(op.f("ix_admin_sessions_user_id"), table_name="admin_sessions")
    op.drop_index(op.f("ix_admin_sessions_expires_at"), table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_table("app_settings")
    op.drop_table("ai_capability_profiles")
    op.drop_index("uq_prompt_templates_active", table_name="prompt_templates")
    op.drop_table("prompt_templates")
    op.drop_index(op.f("ix_assets_sha256"), table_name="assets")
    op.drop_table("assets")
    op.drop_table("admin_users")
