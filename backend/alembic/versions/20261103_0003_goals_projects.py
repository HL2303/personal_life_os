"""Add user-scoped goals, projects, milestones, and activity associations.

Revision ID: 20261103_0003
Revises: 20261103_0002
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_0003"
down_revision: str | Sequence[str] | None = "20261103_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("goal_type", sa.String(16), nullable=False),
        sa.Column("target_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("current_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("current_period_start", sa.Date(), nullable=True),
        sa.Column("unit", sa.String(40), nullable=True),
        sa.Column("recurring_period", sa.String(10), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["activity_categories.id", "activity_categories.user_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_goal_id_user"),
        sa.CheckConstraint(
            "goal_type IN ('measurable', 'recurring', 'milestone')",
            name="ck_goal_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'paused', 'archived')",
            name="ck_goal_status",
        ),
        sa.CheckConstraint(
            "(goal_type = 'milestone' AND target_value IS NULL AND current_value IS NULL) "
            "OR (goal_type IN ('measurable', 'recurring') "
            "AND target_value > 0 AND current_value >= 0 AND current_value <= target_value)",
            name="ck_goal_values",
        ),
        sa.CheckConstraint(
            "(goal_type = 'recurring' AND recurring_period IN ('weekly', 'monthly')) "
            "OR (goal_type != 'recurring' AND recurring_period IS NULL)",
            name="ck_goal_recurring_period",
        ),
        sa.CheckConstraint("deadline >= start_date", name="ck_goal_date_range"),
    )
    op.create_index("ix_goals_user_id", "goals", ["user_id"])
    op.create_index("ix_goals_category_id", "goals", ["category_id"])
    op.create_index("ix_goals_user_status_deadline", "goals", ["user_id", "status", "deadline"])

    op.create_table(
        "goal_milestones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["goal_id", "user_id"], ["goals.id", "goals.user_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("id", "goal_id", "user_id", name="uq_goal_milestone_owner"),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_goal_milestone_completion_time",
        ),
    )
    op.create_index("ix_goal_milestones_goal_id", "goal_milestones", ["goal_id"])
    op.create_index("ix_goal_milestones_user_id", "goal_milestones", ["user_id"])
    op.create_index(
        "ix_goal_milestones_goal_user_due", "goal_milestones", ["goal_id", "user_id", "due_date"]
    )

    op.create_table(
        "goal_progress_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("previous_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("current_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["goal_id", "user_id"], ["goals.id", "goals.user_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_goal_progress_history_goal_id", "goal_progress_history", ["goal_id"])
    op.create_index("ix_goal_progress_history_user_id", "goal_progress_history", ["user_id"])
    op.create_index(
        "ix_goal_progress_history_goal_recorded",
        "goal_progress_history",
        ["goal_id", "recorded_at"],
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.String(8), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["activity_categories.id", "activity_categories.user_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_project_id_user"),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'paused', 'archived')",
            name="ck_project_status",
        ),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high')", name="ck_project_priority"),
        sa.CheckConstraint(
            "target_date IS NULL OR target_date >= start_date",
            name="ck_project_date_range",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= start_date",
            name="ck_project_completion_date",
        ),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])
    op.create_index("ix_projects_category_id", "projects", ["category_id"])
    op.create_index(
        "ix_projects_user_status_target", "projects", ["user_id", "status", "target_date"]
    )

    op.create_table(
        "project_milestones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["projects.id", "projects.user_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "project_id", "user_id", name="uq_project_milestone_owner"),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_project_milestone_completion_time",
        ),
    )
    op.create_index("ix_project_milestones_project_id", "project_milestones", ["project_id"])
    op.create_index("ix_project_milestones_user_id", "project_milestones", ["user_id"])
    op.create_index(
        "ix_project_milestones_project_user_due",
        "project_milestones",
        ["project_id", "user_id", "due_date"],
    )

    with op.batch_alter_table("activities") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_activities_project_user",
            "projects",
            ["project_id", "user_id"],
            ["id", "user_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_activities_project_id", ["project_id"])


def downgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_index("ix_activities_project_id")
        batch_op.drop_constraint("fk_activities_project_user", type_="foreignkey")
        batch_op.drop_column("project_id")

    op.drop_index("ix_project_milestones_project_user_due", table_name="project_milestones")
    op.drop_index("ix_project_milestones_user_id", table_name="project_milestones")
    op.drop_index("ix_project_milestones_project_id", table_name="project_milestones")
    op.drop_table("project_milestones")
    op.drop_index("ix_projects_user_status_target", table_name="projects")
    op.drop_index("ix_projects_category_id", table_name="projects")
    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_goal_progress_history_goal_recorded", table_name="goal_progress_history")
    op.drop_index("ix_goal_progress_history_user_id", table_name="goal_progress_history")
    op.drop_index("ix_goal_progress_history_goal_id", table_name="goal_progress_history")
    op.drop_table("goal_progress_history")
    op.drop_index("ix_goal_milestones_goal_user_due", table_name="goal_milestones")
    op.drop_index("ix_goal_milestones_user_id", table_name="goal_milestones")
    op.drop_index("ix_goal_milestones_goal_id", table_name="goal_milestones")
    op.drop_table("goal_milestones")
    op.drop_index("ix_goals_user_status_deadline", table_name="goals")
    op.drop_index("ix_goals_category_id", table_name="goals")
    op.drop_index("ix_goals_user_id", table_name="goals")
    op.drop_table("goals")
