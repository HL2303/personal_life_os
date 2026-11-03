import hmac
import logging
import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.security import hash_token
from app.db.session import get_db
from app.models.activity import Activity, User
from app.models.telegram import (
    TelegramCheckin,
    TelegramIntegration,
    TelegramLinkToken,
    TelegramOutbox,
    TelegramUpdate,
)
from app.services.activity_service import create_activity_for_user
from app.telegram.extraction import ActivityParsingError, extract_activities
from app.telegram.scheduling import next_checkin_time

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/telegram", tags=["telegram"])
HELP_TEXT = (
    "I can log your activities from messages. Commands: /link CODE, /pause, /resume, "
    "/today, /skip, /help. To link this private chat, create a one-time code in "
    "Personal Life OS settings and send /link CODE here."
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _queue_reply(db: Session, update: TelegramUpdate, text: str) -> None:
    existing = db.scalar(
        select(TelegramOutbox).where(TelegramOutbox.update_id == update.id)
    )
    now = datetime.now(UTC)
    if existing is not None:
        existing.text = text[:4000]
        existing.status = "pending"
        existing.delivery_attempts = 0
        existing.next_attempt_at = now
        existing.last_error = None
        return
    db.add(
        TelegramOutbox(
            update_id=update.id,
            dedupe_key=f"update:{update.update_id}",
            telegram_chat_id=update.chat_id,
            text=text[:4000],
            status="pending",
            delivery_attempts=0,
            next_attempt_at=now,
        )
    )


def _finish(db: Session, update: TelegramUpdate, reply: str | None = None) -> None:
    update.status = "processed"
    update.processed_at = datetime.now(UTC)
    update.processing_error = None
    if reply:
        _queue_reply(db, update, reply)
    db.commit()


def _link_chat(
    db: Session,
    update: TelegramUpdate,
    chat_id: int,
    code: str | None,
) -> None:
    if not code:
        _finish(
            db,
            update,
            "Create a link code in the app's Telegram settings, then send /link CODE.",
        )
        return
    link = db.scalar(
        select(TelegramLinkToken)
        .where(TelegramLinkToken.token_hash == hash_token(code))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        link is None
        or link.consumed_at is not None
        or _utc(link.expires_at) <= now
    ):
        _finish(db, update, "That link code is invalid or expired. Generate a new one in the app.")
        return
    other_owner = db.scalar(
        select(TelegramIntegration).where(
            TelegramIntegration.telegram_chat_id == chat_id,
            TelegramIntegration.user_id != link.user_id,
        )
    )
    if other_owner is not None:
        _finish(db, update, "This Telegram account is already linked to another workspace.")
        return

    integration = db.scalar(
        select(TelegramIntegration).where(TelegramIntegration.user_id == link.user_id)
    )
    if integration is None:
        integration = TelegramIntegration(
            user_id=link.user_id,
            telegram_chat_id=chat_id,
            interval_minutes=30,
            timezone="UTC",
            active_start=time(8),
            active_end=time(22),
            quiet_start=time(22),
            quiet_end=time(8),
            paused=False,
            next_checkin_at=now + timedelta(minutes=30),
            created_at=now,
            updated_at=now,
        )
        db.add(integration)
    else:
        integration.telegram_chat_id = chat_id
        integration.next_checkin_at = next_checkin_time(integration, now)
        integration.updated_at = now
    link.consumed_at = now
    db.flush()
    update.integration_id = integration.id
    _finish(db, update, "Your Telegram account is linked. I'll check in during your active hours.")


def _today_message(db: Session, user: User, integration: TelegramIntegration) -> str:
    local_now = datetime.now(UTC).astimezone(ZoneInfo(integration.timezone))
    local_start = datetime.combine(
        local_now.date(),
        time.min,
        tzinfo=ZoneInfo(integration.timezone),
    )
    local_end = local_start + timedelta(days=1)
    activities = list(
        db.scalars(
            select(Activity)
            .options(selectinload(Activity.category))
            .where(
                Activity.user_id == user.id,
                Activity.started_at < local_end.astimezone(UTC),
                Activity.ended_at > local_start.astimezone(UTC),
            )
            .order_by(Activity.started_at)
        )
    )
    if not activities:
        return "No activities are logged for today yet."
    lines = ["Today's activities:"]
    for activity in activities[:15]:
        start = _utc(activity.started_at).astimezone(ZoneInfo(integration.timezone))
        end = _utc(activity.ended_at).astimezone(ZoneInfo(integration.timezone))
        lines.append(
            f"• {start:%H:%M}–{end:%H:%M} · {activity.title} ({activity.category.name})"
        )
    if len(activities) > 15:
        lines.append(f"…and {len(activities) - 15} more.")
    return "\n".join(lines)


def _command(
    db: Session,
    update: TelegramUpdate,
    chat_id: int,
    text: str,
) -> None:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", 1)[0].casefold()
    argument = parts[1].strip() if len(parts) > 1 else ""
    if command == "/link":
        _link_chat(db, update, chat_id, argument or None)
        return

    integration = db.scalar(
        select(TelegramIntegration).where(TelegramIntegration.telegram_chat_id == chat_id)
    )
    if command in {"/start", "/help"}:
        reply = HELP_TEXT if integration else (
            "Welcome to Personal Life OS. Link your account by generating a one-time code "
            "in the app, then send /link CODE here. " + HELP_TEXT
        )
        _finish(db, update, reply)
        return
    if integration is None:
        _finish(
            db,
            update,
            "This chat isn't linked. Use /link CODE from your app's Telegram settings.",
        )
        return
    update.integration_id = integration.id
    if command == "/pause":
        integration.paused = True
        integration.updated_at = datetime.now(UTC)
        _finish(db, update, "Check-ins are paused. Send /resume when you're ready.")
    elif command == "/resume":
        integration.paused = False
        now = datetime.now(UTC)
        integration.next_checkin_at = next_checkin_time(integration, now)
        integration.updated_at = now
        _finish(db, update, "Check-ins are resumed.")
    elif command == "/today":
        _finish(db, update, _today_message(db, integration.user, integration))
    elif command == "/skip":
        checkin = db.scalar(
            select(TelegramCheckin)
            .where(
                TelegramCheckin.integration_id == integration.id,
                TelegramCheckin.status == "sent",
            )
            .order_by(TelegramCheckin.sent_at.desc())
            .with_for_update()
        )
        if checkin is None:
            _finish(db, update, "There isn't an unanswered check-in to skip.")
        else:
            checkin.status = "skipped"
            checkin.responded_at = datetime.now(UTC)
            update.checkin_id = checkin.id
            _finish(db, update, "Skipped. I'll check in again during your active hours.")
    else:
        _finish(db, update, HELP_TEXT)


def _process_message(
    db: Session,
    update: TelegramUpdate,
    text: str,
) -> None:
    command_name = text.strip().split(maxsplit=1)[0].split("@", 1)[0].casefold()
    if command_name.startswith("/"):
        _command(db, update, update.chat_id, text)
        return

    integration = db.scalar(
        select(TelegramIntegration)
        .options(selectinload(TelegramIntegration.user))
        .where(TelegramIntegration.telegram_chat_id == update.chat_id)
    )
    if integration is None:
        _finish(
            db,
            update,
            "This chat isn't linked. Use /link CODE from your app's Telegram settings.",
        )
        return
    update.integration_id = integration.id
    checkin = db.scalar(
        select(TelegramCheckin)
        .where(
            TelegramCheckin.integration_id == integration.id,
            TelegramCheckin.status == "sent",
        )
        .order_by(TelegramCheckin.sent_at.desc())
        .with_for_update()
    )
    if checkin is not None:
        checkin.status = "responded"
        checkin.responded_at = datetime.now(UTC)
        update.checkin_id = checkin.id

    message = text
    if integration.pending_message_text:
        message = (
            f"Earlier activity details: {integration.pending_message_text}\n"
            f"Clarification: {text}"
        )
    activities, clarification = extract_activities(
        db,
        integration.user_id,
        message,
        integration.timezone,
    )
    if clarification:
        integration.pending_message_text = message[:8000]
        _finish(db, update, clarification)
        return
    if not activities:
        raise ActivityParsingError("No complete activities were extracted.")
    for activity_payload in activities:
        create_activity_for_user(
            db,
            integration.user_id,
            activity_payload,
            source="telegram",
        )
    integration.pending_message_text = None
    titles = ", ".join(activity.title for activity in activities)
    _finish(
        db,
        update,
        (
            f"Logged {len(activities)} "
            f"{'activity' if len(activities) == 1 else 'activities'}: {titles}."
        ),
    )


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    db: Session = Depends(get_db),
    secret_token: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict[str, bool]:
    configured_secret = settings.telegram_webhook_secret
    if (
        settings.telegram_bot_token is None
        or not settings.telegram_bot_token.get_secret_value()
        or configured_secret is None
        or not configured_secret.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram webhook credentials are not configured.",
        )
    expected_secret = configured_secret.get_secret_value()
    if not secret_token or not hmac.compare_digest(secret_token, expected_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret.")

    payload = await request.json()
    update_id = payload.get("update_id") if isinstance(payload, dict) else None
    message_data = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(update_id, int) or isinstance(update_id, bool):
        return {"ok": True}
    if not isinstance(message_data, dict):
        return {"ok": True}
    chat = message_data.get("chat")
    sender = message_data.get("from")
    if (
        not isinstance(chat, dict)
        or chat.get("type") != "private"
        or type(chat.get("id")) is not int
        or not isinstance(sender, dict)
        or type(sender.get("id")) is not int
        or sender.get("id") != chat.get("id")
    ):
        return {"ok": True}
    chat_id = chat["id"]
    text = message_data.get("text")
    message_text = text.strip() if isinstance(text, str) else None
    too_long = message_text is not None and len(message_text) > 4096
    if too_long:
        message_text = None

    return await run_in_threadpool(
        _persist_and_process,
        db,
        update_id,
        chat_id,
        message_data.get("message_id")
        if isinstance(message_data.get("message_id"), int)
        else None,
        message_text,
        too_long,
    )


def _persist_and_process(
    db: Session,
    update_id: int,
    chat_id: int,
    message_id: int | None,
    message_text: str | None,
    too_long: bool,
) -> dict[str, bool]:
    now = datetime.now(UTC)
    update = TelegramUpdate(
        update_id=update_id,
        chat_id=chat_id,
        message_id=message_id,
        message_text=message_text,
        status="processing",
        created_at=now,
        processing_started_at=now,
    )
    db.add(update)
    try:
        db.commit()
        db.refresh(update)
    except IntegrityError:
        db.rollback()
        update = db.scalar(
            select(TelegramUpdate).where(TelegramUpdate.update_id == update_id).with_for_update()
        )
        if update is None:
            return {"ok": True}
        now = datetime.now(UTC)
        if update.status == "processed":
            return {"ok": True}
        if (
            update.status == "processing"
            and _utc(update.processing_started_at) > now - timedelta(minutes=5)
        ):
            return {"ok": True}
        update.status = "processing"
        update.processing_started_at = now
        update.processing_error = None
        db.commit()

    try:
        if too_long:
            _finish(
                db,
                update,
                "That message is too long. Please split it into messages of up to 4096 characters.",
            )
        elif message_text:
            _process_message(db, update, message_text)
        else:
            _finish(db, update, "Please send a text message to log an activity.")
    except Exception as exc:
        db.rollback()
        logger.error(
            "Telegram update processing failed; update_id=%s error_type=%s",
            update_id,
            type(exc).__name__,
        )
        failed_update = db.scalar(
            select(TelegramUpdate).where(TelegramUpdate.update_id == update_id)
        )
        if failed_update is not None:
            failed_update.status = "failed"
            failed_update.processing_error = type(exc).__name__
            failed_update.processed_at = datetime.now(UTC)
            reply = (
                str(exc)
                if isinstance(exc, ActivityParsingError)
                else (
                    "I couldn't process that message safely. "
                    "Please try again or log it in the app."
                )
            )
            _queue_reply(
                db,
                failed_update,
                re.sub(r"\s+", " ", reply)[:500],
            )
            db.commit()
    return {"ok": True}
