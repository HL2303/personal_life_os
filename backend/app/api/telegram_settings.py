import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.dependencies import (
    AuthContext,
    get_auth_context,
    require_authenticated_user,
    require_csrf,
)
from app.core.config import settings
from app.core.security import hash_token
from app.db.session import get_db
from app.models.telegram import TelegramIntegration, TelegramLinkToken
from app.schemas.telegram import TelegramLinkRead, TelegramSettingsRead, TelegramSettingsUpdate
from app.telegram.scheduling import next_checkin_time

router = APIRouter(
    prefix="/api/telegram",
    tags=["telegram"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/settings", response_model=TelegramSettingsRead)
def get_settings(
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> TelegramSettingsRead:
    integration = db.scalar(
        select(TelegramIntegration).where(TelegramIntegration.user_id == context.user.id)
    )
    if integration is None:
        return TelegramSettingsRead(
            connected=False,
            paused=False,
            bot_username=settings.telegram_bot_username,
            interval_minutes=30,
            timezone="UTC",
            active_start="08:00",
            active_end="22:00",
            quiet_start="22:00",
            quiet_end="08:00",
            next_checkin_at=None,
        )
    return TelegramSettingsRead(
        connected=True,
        paused=integration.paused,
        bot_username=settings.telegram_bot_username,
        interval_minutes=integration.interval_minutes,
        timezone=integration.timezone,
        active_start=integration.active_start,
        active_end=integration.active_end,
        quiet_start=integration.quiet_start,
        quiet_end=integration.quiet_end,
        next_checkin_at=integration.next_checkin_at,
    )


@router.post("/link-code", response_model=TelegramLinkRead)
def create_link_code(
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TelegramLinkRead:
    if (
        not settings.telegram_bot_token
        or not settings.telegram_bot_token.get_secret_value()
        or not settings.telegram_webhook_secret
        or not settings.telegram_webhook_secret.get_secret_value()
        or not settings.telegram_bot_username
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot token, username, and webhook secret are not configured.",
        )
    now = datetime.now(UTC)
    code = secrets.token_urlsafe(24)
    db.execute(
        update(TelegramLinkToken)
        .where(
            TelegramLinkToken.user_id == context.user.id,
            TelegramLinkToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    db.add(
        TelegramLinkToken(
            user_id=context.user.id,
            token_hash=hash_token(code),
            created_at=now,
            expires_at=now + timedelta(minutes=settings.telegram_link_token_ttl_minutes),
        )
    )
    db.commit()
    return TelegramLinkRead(
        code=code,
        expires_at=(now + timedelta(minutes=settings.telegram_link_token_ttl_minutes)).isoformat(),
        bot_username=settings.telegram_bot_username,
    )


@router.patch("/settings", response_model=TelegramSettingsRead)
def update_settings(
    payload: TelegramSettingsUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TelegramSettingsRead:
    integration = db.scalar(
        select(TelegramIntegration).where(TelegramIntegration.user_id == context.user.id)
    )
    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Link your Telegram account before configuring check-ins.",
        )
    now = datetime.now(UTC)
    for field, value in payload.model_dump().items():
        setattr(integration, field, value)
    integration.next_checkin_at = next_checkin_time(integration, now)
    integration.updated_at = now
    db.commit()
    return TelegramSettingsRead(
        connected=True,
        paused=integration.paused,
        bot_username=settings.telegram_bot_username,
        interval_minutes=integration.interval_minutes,
        timezone=integration.timezone,
        active_start=integration.active_start,
        active_end=integration.active_end,
        quiet_start=integration.quiet_start,
        quiet_end=integration.quiet_end,
        next_checkin_at=integration.next_checkin_at,
    )
