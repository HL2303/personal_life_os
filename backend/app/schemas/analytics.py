from datetime import date

from pydantic import BaseModel


class AnalyticsCategory(BaseModel):
    category_id: int
    category_name: str
    color: str
    duration_seconds: int
    activity_count: int


class AnalyticsDay(BaseModel):
    date: date
    tracked_seconds: int
    untracked_seconds: int
    activity_count: int
    categories: list[AnalyticsCategory]


class AnalyticsPeriod(BaseModel):
    start_date: date
    end_date: date
    total_tracked_seconds: int
    untracked_seconds: int
    available_seconds: int
    activity_count: int
    categories: list[AnalyticsCategory]


class AnalyticsResponse(AnalyticsPeriod):
    timezone: str
    days: list[AnalyticsDay]
    previous_period: AnalyticsPeriod
