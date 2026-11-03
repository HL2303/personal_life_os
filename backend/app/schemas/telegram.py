from datetime import datetime, time
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.telegram.scheduling import is_time_window_valid


class TelegramSettingsUpdate(BaseModel):
    interval_minutes: Annotated[int, Field(ge=5, le=240)] = 30
    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "UTC"
    active_start: time = time(8)
    active_end: time = time(22)
    quiet_start: time = time(22)
    quiet_end: time = time(8)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Timezone must be a valid IANA timezone.") from exc
        return value

    @model_validator(mode="after")
    def validate_active_hours(self) -> "TelegramSettingsUpdate":
        if not is_time_window_valid(
            self.active_start,
            self.active_end,
            self.quiet_start,
            self.quiet_end,
        ):
            raise ValueError("Active hours must include at least one non-quiet time.")
        return self


class TelegramSettingsRead(BaseModel):
    connected: bool
    paused: bool
    bot_username: str | None
    interval_minutes: int
    timezone: str
    active_start: time
    active_end: time
    quiet_start: time
    quiet_end: time
    next_checkin_at: datetime | None


class TelegramLinkRead(BaseModel):
    code: str
    expires_at: str
    bot_username: str | None
