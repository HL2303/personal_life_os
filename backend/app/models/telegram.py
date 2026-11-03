from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TelegramLinkToken(Base):
    __tablename__ = "telegram_link_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramIntegration(Base):
    __tablename__ = "telegram_integrations"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_telegram_integration_user"),
        UniqueConstraint("telegram_chat_id", name="uq_telegram_integration_chat"),
        Index("ix_telegram_integrations_next_checkin", "paused", "next_checkin_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger())
    interval_minutes: Mapped[int] = mapped_column(Integer(), default=30)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    active_start: Mapped[time] = mapped_column(Time(), default=time(8))
    active_end: Mapped[time] = mapped_column(Time(), default=time(22))
    quiet_start: Mapped[time] = mapped_column(Time(), default=time(22))
    quiet_end: Mapped[time] = mapped_column(Time(), default=time(8))
    paused: Mapped[bool] = mapped_column(Boolean(), default=False)
    next_checkin_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pending_message_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user = relationship("User")
    checkins: Mapped[list["TelegramCheckin"]] = relationship(
        back_populates="integration", cascade="all, delete-orphan"
    )


class TelegramCheckin(Base):
    __tablename__ = "telegram_checkins"
    __table_args__ = (
        UniqueConstraint("integration_id", "scheduled_for", name="uq_telegram_checkin_schedule"),
        Index("ix_telegram_checkins_delivery", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_integrations.id", ondelete="CASCADE"), index=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    delivery_attempts: Mapped[int] = mapped_column(Integer(), default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)

    integration: Mapped[TelegramIntegration] = relationship(back_populates="checkins")


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger(), index=True, unique=True)
    chat_id: Mapped[int] = mapped_column(BigInteger(), index=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_integrations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    checkin_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_checkins.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="processing")
    processing_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramOutbox(Base):
    __tablename__ = "telegram_outbox"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_telegram_outbox_dedupe_key"),
        Index("ix_telegram_outbox_delivery", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    update_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_updates.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(128))
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger())
    text: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(16), default="pending")
    delivery_attempts: Mapped[int] = mapped_column(Integer(), default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
