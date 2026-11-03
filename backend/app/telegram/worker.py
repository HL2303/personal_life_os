import logging
import time as time_module
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.telegram import (
    TelegramCheckin,
    TelegramIntegration,
    TelegramOutbox,
)
from app.telegram.bot_api import TelegramAPIError, send_message
from app.telegram.scheduling import is_checkin_time_allowed, next_checkin_time

logger = logging.getLogger(__name__)
MAX_DELIVERY_ATTEMPTS = 8
CHECKIN_PROMPT = (
    "Quick activity check-in: what have you been doing since the last one? "
    "Include exact start and end times when you can, and use /skip if nothing to log."
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _retry_delay(attempt: int, retry_after: int | None = None) -> timedelta:
    seconds = retry_after or min(3600, 30 * (2 ** min(attempt - 1, 7)))
    return timedelta(seconds=max(1, min(seconds, 86400)))


def schedule_due_checkins(
    session_factory: sessionmaker[Session] = SessionLocal,
    *,
    now: datetime | None = None,
) -> int:
    instant = _as_utc(now or datetime.now(UTC))
    with session_factory() as db:
        integrations = list(
            db.scalars(
                select(TelegramIntegration)
                .where(
                    TelegramIntegration.paused.is_(False),
                    TelegramIntegration.next_checkin_at <= instant,
                )
                .order_by(TelegramIntegration.next_checkin_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        )
        scheduled = 0
        for integration in integrations:
            scheduled_for = integration.next_checkin_at
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=UTC)
            is_due_in_active_hours = is_checkin_time_allowed(integration, scheduled_for)
            is_active_now = is_checkin_time_allowed(integration, instant)
            status = "pending" if is_due_in_active_hours and is_active_now else "skipped"
            db.add(
                TelegramCheckin(
                    integration_id=integration.id,
                    scheduled_for=scheduled_for,
                    status=status,
                    delivery_attempts=0,
                    next_attempt_at=instant,
                )
            )
            integration.next_checkin_at = next_checkin_time(integration, instant)
            integration.updated_at = instant
            scheduled += 1
        db.commit()
        return scheduled


def _deliver_checkin(
    session_factory: sessionmaker[Session],
    checkin_id: int,
    *,
    now: datetime,
    sender: Callable[[int, str], int | None],
) -> bool:
    with session_factory() as db:
        checkin = db.get(TelegramCheckin, checkin_id)
        if checkin is None or checkin.status != "pending":
            return False
        chat_id = checkin.integration.telegram_chat_id
    try:
        telegram_message_id = sender(chat_id, CHECKIN_PROMPT)
    except TelegramAPIError as exc:
        with session_factory() as db:
            checkin = db.get(TelegramCheckin, checkin_id)
            if checkin is None:
                return False
            checkin.last_error = str(exc)[:500]
            if checkin.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
                checkin.status = "failed"
            else:
                checkin.next_attempt_at = now + _retry_delay(
                    checkin.delivery_attempts, exc.retry_after
                )
            db.commit()
        logger.warning("Telegram check-in delivery failed; checkin_id=%s", checkin_id)
        return False
    with session_factory() as db:
        checkin = db.get(TelegramCheckin, checkin_id)
        if checkin is None:
            return False
        checkin.status = "sent"
        checkin.sent_at = now
        checkin.telegram_message_id = telegram_message_id
        checkin.last_error = None
        db.commit()
    return True


def _deliver_outbox(
    session_factory: sessionmaker[Session],
    outbox_id: int,
    *,
    now: datetime,
    sender: Callable[[int, str], int | None],
) -> bool:
    with session_factory() as db:
        message = db.get(TelegramOutbox, outbox_id)
        if message is None or message.status != "pending":
            return False
        chat_id, text = message.telegram_chat_id, message.text
    try:
        sender(chat_id, text)
    except TelegramAPIError as exc:
        with session_factory() as db:
            message = db.get(TelegramOutbox, outbox_id)
            if message is None:
                return False
            message.last_error = str(exc)[:500]
            if message.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
                message.status = "failed"
            else:
                message.next_attempt_at = now + _retry_delay(
                    message.delivery_attempts, exc.retry_after
                )
            db.commit()
        logger.warning("Telegram reply delivery failed; outbox_id=%s", outbox_id)
        return False
    with session_factory() as db:
        message = db.get(TelegramOutbox, outbox_id)
        if message is None:
            return False
        message.status = "sent"
        message.sent_at = now
        message.last_error = None
        db.commit()
    return True


def _drain_due(
    session_factory: sessionmaker[Session],
    model: type[TelegramCheckin] | type[TelegramOutbox],
    deliver: Callable[..., bool],
    *,
    now: datetime,
    sender: Callable[[int, str], int | None],
) -> tuple[int, int]:
    with session_factory() as db:
        due_items = list(
            db.scalars(
                select(model)
                .where(model.status == "pending", model.next_attempt_at <= now)
                .order_by(model.next_attempt_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        )
        due_ids = []
        for item in due_items:
            item.delivery_attempts += 1
            item.next_attempt_at = now + _retry_delay(item.delivery_attempts)
            due_ids.append(item.id)
        db.commit()
    sent = sum(
        1
        for item_id in due_ids
        if deliver(session_factory, item_id, now=now, sender=sender)
    )
    return sent, len(due_ids) - sent


def run_once(
    session_factory: sessionmaker[Session] = SessionLocal,
    *,
    now: datetime | None = None,
    sender: Callable[[int, str], int | None] = send_message,
) -> dict[str, int]:
    instant = _as_utc(now or datetime.now(UTC))
    scheduled = schedule_due_checkins(session_factory, now=instant)
    sent_checkins, failed_checkins = _drain_due(
        session_factory,
        TelegramCheckin,
        _deliver_checkin,
        now=instant,
        sender=sender,
    )
    sent_replies, failed_replies = _drain_due(
        session_factory,
        TelegramOutbox,
        _deliver_outbox,
        now=instant,
        sender=sender,
    )
    return {
        "scheduled": scheduled,
        "checkins_sent": sent_checkins,
        "checkins_pending_or_failed": failed_checkins,
        "replies_sent": sent_replies,
        "replies_pending_or_failed": failed_replies,
    }


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info(
        "Telegram worker started; poll interval=%s seconds",
        settings.telegram_worker_poll_seconds,
    )
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("Telegram worker iteration failed")
        time_module.sleep(settings.telegram_worker_poll_seconds)


if __name__ == "__main__":
    run_forever()
