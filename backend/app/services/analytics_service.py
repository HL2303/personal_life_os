from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from heapq import heappop, heappush
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity, ActivityCategory
from app.schemas.analytics import (
    AnalyticsCategory,
    AnalyticsDay,
    AnalyticsPeriod,
    AnalyticsResponse,
)


@dataclass(frozen=True)
class ActivityInterval:
    activity_id: int
    category_id: int
    started_at: datetime
    ended_at: datetime


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _local_midnight(value: date, timezone: ZoneInfo) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone).astimezone(UTC)


def _category_summaries(
    category_rows: list[tuple[int, str, str]],
    durations: dict[int, int],
    counts: dict[int, int],
) -> list[AnalyticsCategory]:
    return [
        AnalyticsCategory(
            category_id=category_id,
            category_name=name,
            color=color,
            duration_seconds=durations.get(category_id, 0),
            activity_count=counts.get(category_id, 0),
        )
        for category_id, name, color in category_rows
    ]


def _aggregate(
    intervals: list[ActivityInterval],
    category_rows: list[tuple[int, str, str]],
    start_date: date,
    end_date: date,
    timezone: ZoneInfo,
) -> tuple[AnalyticsPeriod, list[AnalyticsDay]]:
    day_dates: list[date] = []
    current_date = start_date
    while current_date <= end_date:
        day_dates.append(current_date)
        current_date += timedelta(days=1)

    day_bounds = {
        day: (_local_midnight(day, timezone), _local_midnight(day + timedelta(days=1), timezone))
        for day in day_dates
    }
    range_start = day_bounds[start_date][0]
    range_end = day_bounds[end_date][1]

    events: dict[datetime, list[tuple[bool, ActivityInterval]]] = defaultdict(list)
    category_counts: dict[int, int] = defaultdict(int)
    day_counts: dict[date, int] = defaultdict(int)
    day_category_counts: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for interval in intervals:
        clipped_start = max(_as_utc(interval.started_at), range_start)
        clipped_end = min(_as_utc(interval.ended_at), range_end)
        if clipped_start >= clipped_end:
            continue
        category_counts[interval.category_id] += 1
        first_day = clipped_start.astimezone(timezone).date()
        last_day = (clipped_end - timedelta(microseconds=1)).astimezone(timezone).date()
        day = first_day
        while day <= last_day:
            day_counts[day] += 1
            day_category_counts[day][interval.category_id] += 1
            day += timedelta(days=1)
        events[clipped_start].append((True, interval))
        events[clipped_end].append((False, interval))

    boundaries = set(events)
    boundaries.update(start for start, _ in day_bounds.values())
    boundaries.update(end for _, end in day_bounds.values())
    ordered_boundaries = sorted(boundaries)
    active: dict[int, ActivityInterval] = {}
    active_priority: list[tuple[datetime, int]] = []
    category_microseconds: dict[int, int] = defaultdict(int)
    day_microseconds: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for index, boundary in enumerate(ordered_boundaries[:-1]):
        for is_start, interval in events.get(boundary, ()):
            if not is_start:
                active.pop(interval.activity_id, None)
        for is_start, interval in events.get(boundary, ()):
            if is_start:
                active[interval.activity_id] = interval
                heappush(
                    active_priority,
                    (_as_utc(interval.started_at), interval.activity_id),
                )

        next_boundary = ordered_boundaries[index + 1]
        while active_priority and active_priority[0][1] not in active:
            heappop(active_priority)
        if not active_priority or next_boundary <= boundary:
            continue
        owner = active[active_priority[0][1]]
        local_day = boundary.astimezone(timezone).date()
        microseconds = (next_boundary - boundary) // timedelta(microseconds=1)
        category_microseconds[owner.category_id] += microseconds
        day_microseconds[local_day][owner.category_id] += microseconds

    category_durations = {
        category_id: microseconds // 1_000_000
        for category_id, microseconds in category_microseconds.items()
    }

    days: list[AnalyticsDay] = []
    available_seconds = 0
    for day in day_dates:
        day_start, day_end = day_bounds[day]
        day_available = int((day_end - day_start).total_seconds())
        day_durations = {
            category_id: microseconds // 1_000_000
            for category_id, microseconds in day_microseconds[day].items()
        }
        day_categories = _category_summaries(
            category_rows, day_durations, day_category_counts[day]
        )
        tracked = sum(category.duration_seconds for category in day_categories)
        available_seconds += day_available
        days.append(
            AnalyticsDay(
                date=day,
                tracked_seconds=tracked,
                untracked_seconds=max(0, day_available - tracked),
                activity_count=day_counts[day],
                categories=day_categories,
            )
        )

    total_tracked = sum(category_durations.values())
    period = AnalyticsPeriod(
        start_date=start_date,
        end_date=end_date,
        total_tracked_seconds=total_tracked,
        untracked_seconds=max(0, available_seconds - total_tracked),
        available_seconds=available_seconds,
        activity_count=sum(category_counts.values()),
        categories=_category_summaries(category_rows, category_durations, category_counts),
    )
    return period, days


def get_analytics(
    db: Session,
    user_id: int,
    start_date: date,
    end_date: date,
    timezone_name: str,
) -> AnalyticsResponse:
    timezone = ZoneInfo(timezone_name)
    duration_days = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=duration_days - 1)
    query_start = _local_midnight(previous_start, timezone)
    query_end = _local_midnight(end_date + timedelta(days=1), timezone)

    category_rows = list(
        db.execute(
            select(ActivityCategory.id, ActivityCategory.name, ActivityCategory.color)
            .where(ActivityCategory.user_id == user_id)
            .order_by(ActivityCategory.name, ActivityCategory.id)
        )
    )
    records = db.execute(
        select(
            Activity.id,
            Activity.category_id,
            Activity.started_at,
            Activity.ended_at,
        )
        .join(ActivityCategory, ActivityCategory.id == Activity.category_id)
        .where(
            Activity.user_id == user_id,
            ActivityCategory.user_id == user_id,
            Activity.started_at < query_end,
            Activity.ended_at > query_start,
        )
        .order_by(Activity.started_at, Activity.id)
    )
    previous_intervals: list[ActivityInterval] = []
    current_intervals: list[ActivityInterval] = []
    previous_start_utc = _local_midnight(previous_start, timezone)
    current_start_utc = _local_midnight(start_date, timezone)
    current_end_utc = _local_midnight(end_date + timedelta(days=1), timezone)
    for activity_id, category_id, started_at, ended_at in records:
        interval = ActivityInterval(
            activity_id=activity_id,
            category_id=category_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        if _as_utc(started_at) < current_start_utc and _as_utc(ended_at) > previous_start_utc:
            previous_intervals.append(interval)
        if _as_utc(started_at) < current_end_utc and _as_utc(ended_at) > current_start_utc:
            current_intervals.append(interval)

    previous_period, _ = _aggregate(
        previous_intervals, category_rows, previous_start, previous_end, timezone
    )
    current_period, days = _aggregate(
        current_intervals, category_rows, start_date, end_date, timezone
    )
    return AnalyticsResponse(
        **current_period.model_dump(),
        timezone=timezone_name,
        days=days,
        previous_period=previous_period,
    )
