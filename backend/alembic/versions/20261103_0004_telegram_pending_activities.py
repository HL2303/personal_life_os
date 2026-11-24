"""Persist and retry Telegram activity messages when AI extraction is unavailable.

Revision ID: 20261103_0004
Revises: 20261103_0003
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_0004"
down_revision: str | Sequence[str] | None = "20261103_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_pending_activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("source_update_id", sa.Integer(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["telegram_integrations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_update_id"], ["telegram_updates.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("source_update_id", name="uq_telegram_pending_source_update"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'needs_clarification', 'failed')",
            name="ck_telegram_pending_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_telegram_pending_attempts"),
    )
    op.create_index(
        "ix_telegram_pending_retry",
        "telegram_pending_activities",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_telegram_pending_activities_user_id",
        "telegram_pending_activities",
        ["user_id"],
    )
    op.create_index(
        "ix_telegram_pending_activities_integration_id",
        "telegram_pending_activities",
        ["integration_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_pending_activities_integration_id",
        table_name="telegram_pending_activities",
    )
    op.drop_index(
        "ix_telegram_pending_activities_user_id",
        table_name="telegram_pending_activities",
    )
    op.drop_index("ix_telegram_pending_retry", table_name="telegram_pending_activities")
    op.drop_table("telegram_pending_activities")
