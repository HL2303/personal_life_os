"""Create user-scoped activity tracking and authentication tables.

Revision ID: 20261103_0001
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "app_setup",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("owner_user_id"),
    )
    op.bulk_insert(sa.table("app_setup", sa.column("id", sa.Integer())), [{"id": 1}])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "activity_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "name", name="uq_activity_category_user_name"),
        sa.UniqueConstraint("id", "user_id", name="uq_activity_category_id_user"),
    )
    op.create_index("ix_activity_categories_user_id", "activity_categories", ["user_id"])

    op.create_table(
        "activity_subcategories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["activity_categories.id", "activity_categories.user_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "category_id", "user_id", "name", name="uq_activity_subcategory_category_name"
        ),
        sa.UniqueConstraint(
            "id", "category_id", "user_id", name="uq_activity_subcategory_id_category_user"
        ),
    )
    op.create_index(
        "ix_activity_subcategories_category_id", "activity_subcategories", ["category_id"]
    )
    op.create_index(
        "ix_activity_subcategories_user_id", "activity_subcategories", ["user_id"]
    )

    op.create_table(
        "activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("subcategory_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["activity_categories.id", "activity_categories.user_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subcategory_id", "category_id", "user_id"],
            [
                "activity_subcategories.id",
                "activity_subcategories.category_id",
                "activity_subcategories.user_id",
            ],
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_activities_user_id", "activities", ["user_id"])
    op.create_index("ix_activities_category_id", "activities", ["category_id"])
    op.create_index("ix_activities_started_at", "activities", ["started_at"])
    op.create_index("ix_activities_subcategory_id", "activities", ["subcategory_id"])


def downgrade() -> None:
    op.drop_index("ix_activities_subcategory_id", table_name="activities")
    op.drop_index("ix_activities_started_at", table_name="activities")
    op.drop_index("ix_activities_category_id", table_name="activities")
    op.drop_index("ix_activities_user_id", table_name="activities")
    op.drop_table("activities")
    op.drop_index("ix_activity_subcategories_user_id", table_name="activity_subcategories")
    op.drop_index("ix_activity_subcategories_category_id", table_name="activity_subcategories")
    op.drop_table("activity_subcategories")
    op.drop_index("ix_activity_categories_user_id", table_name="activity_categories")
    op.drop_table("activity_categories")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("app_setup")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
