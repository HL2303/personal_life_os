from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["activity_categories.id", "activity_categories.user_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "user_id", name="uq_goal_id_user"),
        CheckConstraint(
            "goal_type IN ('measurable', 'recurring', 'milestone')",
            name="ck_goal_type",
        ),
        CheckConstraint(
            "status IN ('active', 'completed', 'paused', 'archived')",
            name="ck_goal_status",
        ),
        CheckConstraint(
            "(goal_type = 'milestone' AND target_value IS NULL AND current_value IS NULL) "
            "OR (goal_type IN ('measurable', 'recurring') "
            "AND target_value > 0 AND current_value >= 0 AND current_value <= target_value)",
            name="ck_goal_values",
        ),
        CheckConstraint(
            "(goal_type = 'recurring' AND recurring_period IN ('weekly', 'monthly')) "
            "OR (goal_type != 'recurring' AND recurring_period IS NULL)",
            name="ck_goal_recurring_period",
        ),
        CheckConstraint("deadline >= start_date", name="ck_goal_date_range"),
        Index("ix_goals_user_status_deadline", "user_id", "status", "deadline"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    goal_type: Mapped[str] = mapped_column(String(16))
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    recurring_period: Mapped[str | None] = mapped_column(String(10), nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    deadline: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoalMilestone(Base):
    __tablename__ = "goal_milestones"
    __table_args__ = (
        ForeignKeyConstraint(
            ["goal_id", "user_id"],
            ["goals.id", "goals.user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "goal_id", "user_id", name="uq_goal_milestone_owner"),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_goal_milestone_completion_time",
        ),
        Index("ix_goal_milestones_goal_user_due", "goal_id", "user_id", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoalProgressHistory(Base):
    __tablename__ = "goal_progress_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["goal_id", "user_id"],
            ["goals.id", "goals.user_id"],
            ondelete="CASCADE",
        ),
        Index("ix_goal_progress_history_goal_recorded", "goal_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    previous_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["activity_categories.id", "activity_categories.user_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "user_id", name="uq_project_id_user"),
        CheckConstraint(
            "status IN ('active', 'completed', 'paused', 'archived')",
            name="ck_project_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="ck_project_priority",
        ),
        CheckConstraint(
            "target_date IS NULL OR target_date >= start_date",
            name="ck_project_date_range",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= start_date",
            name="ck_project_completion_date",
        ),
        Index("ix_projects_user_status_target", "user_id", "status", "target_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    priority: Mapped[str] = mapped_column(String(8), default="medium")
    start_date: Mapped[date] = mapped_column(Date)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectMilestone(Base):
    __tablename__ = "project_milestones"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["projects.id", "projects.user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "project_id", "user_id", name="uq_project_milestone_owner"),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_project_milestone_completion_time",
        ),
        Index("ix_project_milestones_project_user_due", "project_id", "user_id", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
