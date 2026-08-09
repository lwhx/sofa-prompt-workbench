"""为结果版本增加软隐藏能力。

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-10
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "prompt_results",
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prompt_results", "hidden_at")
