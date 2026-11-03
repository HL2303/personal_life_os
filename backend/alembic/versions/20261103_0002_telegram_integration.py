"""Add Telegram account linking, check-ins, webhook events, and delivery queues.

Revision ID: 20261103_0002
Revises: 20261103_0001
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_0002"
down_revision: str | Sequence[str] | None = "20261103_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_link_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_telegram_link_tokens_user_id", "telegram_link_tokens", ["user_id"])
    op.create_index(
        "ix_telegram_link_tokens_token_hash",
        "telegram_link_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_telegram_link_tokens_expires_at", "telegram_link_tokens", ["expires_at"]
    )

    op.create_table(
        "telegram_integrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("active_start", sa.Time(), nullable=False),
        sa.Column("active_end", sa.Time(), nullable=False),
        sa.Column("quiet_start", sa.Time(), nullable=False),
        sa.Column("quiet_end", sa.Time(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("next_checkin_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pending_message_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_telegram_integration_user"),
        sa.UniqueConstraint("telegram_chat_id", name="uq_telegram_integration_chat"),
    )
    op.create_index("ix_telegram_integrations_user_id", "telegram_integrations", ["user_id"])
    op.create_index(
        "ix_telegram_integrations_next_checkin",
        "telegram_integrations",
        ["paused", "next_checkin_at"],
    )

    op.create_table(
        "telegram_checkins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["telegram_integrations.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "integration_id", "scheduled_for", name="uq_telegram_checkin_schedule"
        ),
    )
    op.create_index("ix_telegram_checkins_integration_id", "telegram_checkins", ["integration_id"])
    op.create_index(
        "ix_telegram_checkins_delivery", "telegram_checkins", ["status", "next_attempt_at"]
    )

    op.create_table(
        "telegram_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("checkin_id", sa.Integer(), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["telegram_integrations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["checkin_id"], ["telegram_checkins.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_telegram_updates_update_id", "telegram_updates", ["update_id"], unique=True)
    op.create_index("ix_telegram_updates_chat_id", "telegram_updates", ["chat_id"])
    op.create_index("ix_telegram_updates_integration_id", "telegram_updates", ["integration_id"])
    op.create_index("ix_telegram_updates_checkin_id", "telegram_updates", ["checkin_id"])

    op.create_table(
        "telegram_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("update_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(128), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["update_id"], ["telegram_updates.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("update_id"),
        sa.UniqueConstraint("dedupe_key", name="uq_telegram_outbox_dedupe_key"),
    )
    op.create_index("ix_telegram_outbox_delivery", "telegram_outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_telegram_outbox_delivery", table_name="telegram_outbox")
    op.drop_table("telegram_outbox")
    op.drop_index("ix_telegram_updates_checkin_id", table_name="telegram_updates")
    op.drop_index("ix_telegram_updates_integration_id", table_name="telegram_updates")
    op.drop_index("ix_telegram_updates_chat_id", table_name="telegram_updates")
    op.drop_index("ix_telegram_updates_update_id", table_name="telegram_updates")
    op.drop_table("telegram_updates")
    op.drop_index("ix_telegram_checkins_delivery", table_name="telegram_checkins")
    op.drop_index("ix_telegram_checkins_integration_id", table_name="telegram_checkins")
    op.drop_table("telegram_checkins")
    op.drop_index("ix_telegram_integrations_next_checkin", table_name="telegram_integrations")
    op.drop_index("ix_telegram_integrations_user_id", table_name="telegram_integrations")
    op.drop_table("telegram_integrations")
    op.drop_index("ix_telegram_link_tokens_expires_at", table_name="telegram_link_tokens")
    op.drop_index("ix_telegram_link_tokens_token_hash", table_name="telegram_link_tokens")
    op.drop_index("ix_telegram_link_tokens_user_id", table_name="telegram_link_tokens")
    op.drop_table("telegram_link_tokens")
