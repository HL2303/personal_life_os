from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models.telegram import TelegramIntegration


def _contains(value: time, start: time, end: time, *, equal_is_full_day: bool = False) -> bool:
    if start == end:
        return equal_is_full_day
    if start < end:
        return start <= value < end
    return value >= start or value < end


def is_checkin_time_allowed(integration: TelegramIntegration, instant: datetime) -> bool:
    local_time = instant.astimezone(ZoneInfo(integration.timezone)).timetz().replace(tzinfo=None)
    in_active = _contains(
        local_time,
        integration.active_start,
        integration.active_end,
    )
    in_quiet = _contains(
        local_time,
        integration.quiet_start,
        integration.quiet_end,
    )
    return in_active and not in_quiet


def next_checkin_time(
    integration: TelegramIntegration,
    after: datetime,
    *,
    interval_minutes: int | None = None,
) -> datetime:
    interval = interval_minutes or integration.interval_minutes
    if after.tzinfo is None or after.utcoffset() is None:
        after = after.replace(tzinfo=UTC)
    candidate = after.astimezone(UTC) + timedelta(minutes=interval)
    search_limit = candidate + timedelta(days=8)
    while candidate <= search_limit:
        if is_checkin_time_allowed(integration, candidate):
            return candidate
        candidate += timedelta(minutes=interval)
    raise ValueError("Check-in schedule has no available time within the next week.")


def is_time_window_valid(start: time, end: time, quiet_start: time, quiet_end: time) -> bool:
    if start == end:
        return False
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    for minute in range(24 * 60):
        instant = now + timedelta(minutes=minute)
        candidate = instant.timetz().replace(tzinfo=None)
        active = _contains(candidate, start, end)
        quiet = _contains(candidate, quiet_start, quiet_end)
        if active and not quiet:
            return True
    return False
