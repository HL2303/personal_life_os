from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    categories: Mapped[list["ActivityCategory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class AppSetup(Base):
    __tablename__ = "app_setup"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), unique=True, nullable=True
    )


class ActivityCategory(Base):
    __tablename__ = "activity_categories"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_activity_category_user_name"),
        UniqueConstraint("id", "user_id", name="uq_activity_category_id_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(7), default="#64748b")

    user: Mapped[User] = relationship(back_populates="categories")
    subcategories: Mapped[list["ActivitySubcategory"]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class ActivitySubcategory(Base):
    __tablename__ = "activity_subcategories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["activity_categories.id", "activity_categories.user_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "category_id", "user_id", "name", name="uq_activity_subcategory_category_name"
        ),
        UniqueConstraint(
            "id", "category_id", "user_id", name="uq_activity_subcategory_id_category_user"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))

    category: Mapped[ActivityCategory] = relationship(back_populates="subcategories")


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["activity_categories.id", "activity_categories.user_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["subcategory_id", "category_id", "user_id"],
            [
                "activity_subcategories.id",
                "activity_subcategories.category_id",
                "activity_subcategories.user_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["projects.id", "projects.user_id"],
            ondelete="RESTRICT",
            name="fk_activities_project_user",
        ),
        Index("ix_activities_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int] = mapped_column(index=True)
    subcategory_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    project_id: Mapped[int | None] = mapped_column(nullable=True, index=True)

    category: Mapped[ActivityCategory] = relationship(viewonly=True)
    subcategory: Mapped[ActivitySubcategory | None] = relationship(viewonly=True)

    @property
    def duration_seconds(self) -> int:
        return int((self.ended_at - self.started_at).total_seconds())
