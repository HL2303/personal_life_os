import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.telegram import TelegramIntegration, TelegramOutbox, TelegramPendingActivity
from app.services.activity_service import create_activity_for_user
from app.telegram.extraction import (
    ActivityParsingError,
    ActivityProviderUnavailable,
    extract_activities,
)

MAX_PENDING_ATTEMPTS = 5
MAX_PENDING_BACKOFF_SECONDS = 3600
PROCESSING_TIMEOUT = timedelta(minutes=5)


def pending_retry_delay(attempt: int, retry_after_seconds: int | None = None) -> timedelta:
    if retry_after_seconds is not None:
        return timedelta(seconds=max(1, retry_after_seconds))
    ceiling = min(MAX_PENDING_BACKOFF_SECONDS, 30 * (2 ** max(0, attempt - 1)))
    return timedelta(seconds=max(1, int(random.uniform(0.75, 1.25) * ceiling)))


def retry_failed_pending(db: Session, integration_id: int, user_id: int, now: datetime) -> int:
    items = list(
        db.scalars(
            select(TelegramPendingActivity)
            .where(
                TelegramPendingActivity.integration_id == integration_id,
                TelegramPendingActivity.user_id == user_id,
                TelegramPendingActivity.status.in_(("failed", "needs_clarification")),
            )
            .with_for_update()
        )
    )
    for item in items:
        item.status = "pending"
        item.attempts = 0
        item.next_attempt_at = now
        item.processing_started_at = None
        item.last_error = None
        item.completed_at = None
        item.updated_at = now
    db.commit()
    return len(items)


def claim_pending_activities(
    session_factory: sessionmaker[Session],
    *,
    now: datetime,
    limit: int = 20,
) -> list[int]:
    instant = now.astimezone(UTC)
    stale_before = instant - PROCESSING_TIMEOUT
    with session_factory() as db:
        items = list(
            db.scalars(
                select(TelegramPendingActivity)
                .where(
                    (
                        (TelegramPendingActivity.status == "pending")
                        & (TelegramPendingActivity.next_attempt_at <= instant)
                    )
                    | (
                        (TelegramPendingActivity.status == "processing")
                        & (TelegramPendingActivity.processing_started_at <= stale_before)
                    )
                )
                .order_by(TelegramPendingActivity.next_attempt_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        ids = []
        for item in items:
            item.status = "processing"
            item.processing_started_at = instant
            item.attempts += 1
            item.updated_at = instant
            ids.append(item.id)
        db.commit()
        return ids


def _queue_outbox(db: Session, *, pending: TelegramPendingActivity, text: str) -> None:
    dedupe_key = (
        f"pending-activity:{pending.id}:{pending.status}:"
        f"{pending.attempts}:{pending.updated_at.isoformat()}"
    )
    if db.scalar(select(TelegramOutbox.id).where(TelegramOutbox.dedupe_key == dedupe_key)):
        return
    chat_id = db.scalar(
        select(TelegramIntegration.telegram_chat_id).where(
            TelegramIntegration.id == pending.integration_id,
            TelegramIntegration.user_id == pending.user_id,
        )
    )
    if chat_id is None:
        return
    db.add(
        TelegramOutbox(
            dedupe_key=dedupe_key,
            telegram_chat_id=chat_id,
            text=text[:4000],
            status="pending",
            delivery_attempts=0,
            next_attempt_at=datetime.now(UTC),
        )
    )


def process_pending_activity(
    session_factory: sessionmaker[Session],
    pending_id: int,
    *,
    now: datetime,
) -> bool:
    instant = now.astimezone(UTC)
    with session_factory() as db:
        pending = db.get(TelegramPendingActivity, pending_id)
        if pending is None or pending.status != "processing":
            return False
        integration = db.get(TelegramIntegration, pending.integration_id)
        if integration is None or integration.user_id != pending.user_id:
            pending.status = "failed"
            pending.last_error = "integration_owner_mismatch"
            pending.processing_started_at = None
            pending.updated_at = instant
            db.commit()
            return False

        try:
            activities, clarification = extract_activities(
                db,
                pending.user_id,
                pending.message_text,
                integration.timezone,
            )
        except ActivityProviderUnavailable as exc:
            pending.last_error = "provider_unavailable"
            pending.processing_started_at = None
            pending.updated_at = instant
            if pending.attempts >= MAX_PENDING_ATTEMPTS:
                pending.status = "failed"
                _queue_outbox(
                    db,
                    pending=pending,
                    text=(
                        "I couldn't extract that activity after several attempts. "
                        "Your message is still safely saved; send /retry to try again."
                    ),
                )
            else:
                pending.status = "pending"
                pending.next_attempt_at = instant + pending_retry_delay(
                    pending.attempts,
                    exc.retry_after_seconds,
                )
            db.commit()
            return False
        except ActivityParsingError:
            pending.status = "failed"
            pending.last_error = "extraction_failed"
            pending.processing_started_at = None
            pending.updated_at = instant
            _queue_outbox(
                db,
                pending=pending,
                text=(
                    "I couldn't safely extract that activity. Your message is still saved; "
                    "send /retry to try again or reply with more detail."
                ),
            )
            db.commit()
            return False

        pending.processing_started_at = None
        pending.updated_at = instant
        if clarification:
            pending.status = "needs_clarification"
            integration.pending_message_text = pending.message_text[:8000]
            _queue_outbox(db, pending=pending, text=clarification)
            db.commit()
            return True

        if not activities:
            pending.status = "failed"
            pending.last_error = "empty_extraction"
            _queue_outbox(
                db,
                pending=pending,
                text=(
                    "I couldn't safely extract that activity. Your message is still saved; "
                    "send /retry to try again or reply with more detail."
                ),
            )
            db.commit()
            return False

        for activity_payload in activities:
            create_activity_for_user(
                db,
                pending.user_id,
                activity_payload,
                source="telegram",
            )
        pending.status = "completed"
        pending.status = "completed"
        pending.last_error = None
        titles = ", ".join(activity.title for activity in activities)
        _queue_outbox(
            db,
            pending=pending,
            text=(
                f"Saved activity message processed. Logged {len(activities)} "
                f"{'activity' if len(activities) == 1 else 'activities'}: {titles}."
            ),
        )
        db.commit()
        return True
