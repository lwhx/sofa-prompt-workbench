"""扩展自动运行意图的并发领取能力。

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-10
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("auto_run_intents", sa.Column("claim_token", sa.String(length=36), nullable=True))
    op.add_column(
        "auto_run_intents",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "auto_run_intents",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("auto_run_intents", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_index(
        "ix_auto_run_intents_status_due_at",
        "auto_run_intents",
        ["status", "due_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auto_run_intents_status_due_at", table_name="auto_run_intents")
    op.drop_column("auto_run_intents", "last_error")
    op.drop_column("auto_run_intents", "attempt_count")
    op.drop_column("auto_run_intents", "lease_expires_at")
    op.drop_column("auto_run_intents", "claim_token")
