import json
import logging
import random
import re
import time
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from math import ceil
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import USER_AGENT, settings
from app.models.activity import ActivityCategory
from app.schemas.activity import ActivityCreate

logger = logging.getLogger(__name__)
CONFIDENCE_THRESHOLD = 0.8
MAX_PROVIDER_ATTEMPTS = 3
MAX_INLINE_RETRY_DELAY_SECONDS = 2.0
MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRY_AFTER_SECONDS = 30 * 24 * 60 * 60
SAFE_PROVIDER_ERROR_TYPES = {
    "api_error",
    "authentication_error",
    "INTERNAL",
    "invalid_request_error",
    "rate_limit_error",
    "RESOURCE_EXHAUSTED",
    "server_error",
    "UNAVAILABLE",
}
SAFE_PROVIDER_ERROR_CODES = {
    "500",
    "503",
    "INTERNAL",
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
    "context_length_exceeded",
    "insufficient_quota",
    "invalid_api_key",
    "invalid_request_error",
    "model_not_found",
    "rate_limit_exceeded",
    "server_error",
}


class ExtractedActivity(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    category: Annotated[str | None, Field(max_length=80)] = None
    subcategory: Annotated[str | None, Field(max_length=80)] = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, gt=0, le=1440)
    description: Annotated[str | None, Field(max_length=10000)] = None
    notes: Annotated[str | None, Field(max_length=10000)] = None
    tags: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=list, max_length=30
    )
    confidence: float = Field(ge=0, le=1)

    @field_validator("started_at", "ended_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Activity times must include timezone offsets.")
        return value


class ExtractionResponse(BaseModel):
    activities: list[ExtractedActivity] = Field(default_factory=list, max_length=10)
    clarification: Annotated[str | None, Field(max_length=500)] = None


class ActivityParsingError(Exception):
    pass


class ActivityProviderUnavailable(ActivityParsingError):
    def __init__(self, *, retry_after_seconds: int | None = None):
        super().__init__("The activity extraction provider is temporarily unavailable.")
        self.retry_after_seconds = retry_after_seconds


TAXONOMY_ALIASES = {
    "coding": {"programming", "learning"},
    "exercise": {"fitness"},
    "gym": {"gym", "fitness"},
    "python": {"programming", "learning"},
    "study": {"learning"},
    "studied": {"learning"},
    "workout": {"fitness", "exercise"},
}


def _resolve_timezone(timezone: str | None) -> tuple[str, ZoneInfo]:
    configured = timezone or settings.default_timezone
    try:
        return configured, ZoneInfo(configured)
    except (ValueError, ZoneInfoNotFoundError):
        return settings.default_timezone, ZoneInfo(settings.default_timezone)


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _taxonomy_name_matches(name: str, words: set[str]) -> bool:
    name_words = _words(name)
    return bool(name_words and name_words <= words)


def _infer_category(
    candidate: ExtractedActivity,
    categories: list[ActivityCategory],
    user_message: str,
) -> ActivityCategory | None:
    if candidate.category:
        category = next(
            (item for item in categories if item.name.casefold() == candidate.category.casefold()),
            None,
        )
        if category is not None:
            return category

    text = " ".join(
        part
        for part in (candidate.title, candidate.description, candidate.category, user_message)
        if part
    )
    words = _words(text)
    inferred_names = set().union(*(TAXONOMY_ALIASES.get(word, set()) for word in words))
    for category in categories:
        if _taxonomy_name_matches(category.name, words | inferred_names):
            return category
    return None


def _infer_subcategory(
    candidate: ExtractedActivity,
    category: ActivityCategory,
    user_message: str,
) -> int | None:
    if candidate.subcategory:
        subcategory = next(
            (
                item
                for item in category.subcategories
                if item.name.casefold() == candidate.subcategory.casefold()
            ),
            None,
        )
        if subcategory is not None:
            return subcategory.id

    text = " ".join(
        part
        for part in (candidate.title, candidate.description, candidate.subcategory, user_message)
        if part
    )
    words = _words(text)
    inferred_names = set().union(*(TAXONOMY_ALIASES.get(word, set()) for word in words))
    for subcategory in category.subcategories:
        if _taxonomy_name_matches(subcategory.name, words | inferred_names):
            return subcategory.id
    return None


def _activity_summary(
    candidate: ExtractedActivity,
    category_name: str | None = None,
    subcategory_name: str | None = None,
) -> str:
    parts = [candidate.title]
    if candidate.category or category_name:
        parts.append(category_name or candidate.category or "")
    if candidate.subcategory or subcategory_name:
        parts.append(subcategory_name or candidate.subcategory or "")
    time_summary = ""
    if candidate.started_at and candidate.ended_at:
        time_summary = (
            f", {candidate.started_at.isoformat()}–{candidate.ended_at.isoformat()}"
        )
    elif candidate.duration_minutes:
        time_summary = f", {candidate.duration_minutes} minutes"
    return f"I have: {' · '.join(parts)}{time_summary}."


def _parse_retry_after(value: str | None, *, now: datetime | None = None) -> int | None:
    if not value:
        return None
    try:
        seconds = max(0, ceil(float(value)))
    except (ValueError, OverflowError):
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            return None
        seconds = max(
            0,
            ceil((retry_at.astimezone(UTC) - (now or datetime.now(UTC))).total_seconds()),
        )
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def _retry_delay(attempt: int, retry_after_seconds: int | None) -> float | None:
    jitter_ceiling = min(1.0, 0.25 * (2 ** max(0, attempt - 1)))
    jitter = random.uniform(0, jitter_ceiling)
    if retry_after_seconds is not None:
        if retry_after_seconds > MAX_INLINE_RETRY_DELAY_SECONDS:
            return None
        return max(float(retry_after_seconds), jitter)
    return jitter


def _sanitize_provider_error(response: bytes) -> str:
    try:
        body = json.loads(response)
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = None

    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return '{"error":"unavailable"}'

    sanitized = {}
    error_type = error.get("type")
    if isinstance(error_type, str) and error_type in SAFE_PROVIDER_ERROR_TYPES:
        sanitized["type"] = error_type
    error_status = error.get("status")
    if isinstance(error_status, str) and error_status in {
        "INTERNAL",
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
    }:
        sanitized["status"] = error_status
    code = error.get("code")
    if isinstance(code, str) and code in SAFE_PROVIDER_ERROR_CODES:
        sanitized["code"] = code
    elif isinstance(code, int) and not isinstance(code, bool) and code in {500, 503}:
        sanitized["code"] = str(code)
    return json.dumps({"error": sanitized or "unavailable"}, separators=(",", ":"))


def _call_provider(prompt: str) -> ExtractionResponse:
    if settings.ai_provider == "none":
        raise ActivityParsingError(
            "Activity parsing is not configured. Please log this in the app."
        )
    if settings.ai_api_key is None or not settings.ai_api_key.get_secret_value():
        raise ActivityParsingError(
            "Activity parsing is not configured. Please log this in the app."
        )

    request = Request(
        f"{settings.ai_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(
            {
                "model": settings.ai_model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Extract only activities the user explicitly describes. Never invent "
                            "an activity title, category, start/end time, or duration. Use "
                            "explicit or relative dates when stated; otherwise use the current "
                            "local calendar date. "
                            "Return one JSON object with keys activities and clarification. "
                            "activities is an array of objects with title, category (exactly "
                            "one provided category), subcategory (provided subcategory or null), "
                            "started_at and ended_at as ISO-8601 datetimes including the user's "
                            "timezone offset, duration_minutes when explicitly given, description, "
                            "notes, tags, and confidence from 0 to 1. Infer category and "
                            "subcategory from the activity meaning using only the supplied "
                            "taxonomy; do not ask for a category when it can be inferred. "
                            "Resolve today, yesterday, last night, and relative dates using the "
                            "given current local datetime; yesterday evening and last night refer "
                            "to the preceding local calendar date, including across midnight. "
                            "Use explicit time ranges and durations. For times without AM/PM, "
                            "prefer the plausible past interpretation using local current time "
                            "and any conversation or check-in context; ask one concise question "
                            "only if AM/PM remains genuinely ambiguous. Never ask for a timezone; "
                            "the supplied IANA timezone is authoritative. Never silently invent "
                            "a start time or duration. If a necessary field is missing, return "
                            "known activity fields with one concise clarification question. "
                            "Preserve facts from all earlier messages in the supplied "
                            "conversation. "
                            "If the text responds to a check-in, use its time window as context "
                            "but do not assume the activity occupied the entire window. If the "
                            "message has multiple activities, extract each separately. Do not "
                            "create overlapping or guessed intervals."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.ai_api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        data = None
        for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
            try:
                with urlopen(
                    request,
                    timeout=min(
                        settings.ai_request_timeout_seconds,
                        MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS,
                    ),
                ) as response:
                    data = json.loads(response.read())
                break
            except HTTPError as exc:
                try:
                    response_body = exc.read()
                except OSError:
                    response_body = b""
                logger.warning(
                    "Activity extraction provider HTTP error; status_code=%s "
                    "sanitized_response=%s",
                    exc.code,
                    _sanitize_provider_error(response_body),
                )
                if exc.code not in {500, 503}:
                    raise ActivityParsingError(
                        "I couldn't process that message right now. Please try again shortly."
                    ) from None
                retry_after = _parse_retry_after(
                    exc.headers.get("Retry-After") if exc.headers else None
                )
                delay = _retry_delay(attempt, retry_after)
                if attempt >= MAX_PROVIDER_ATTEMPTS or delay is None:
                    raise ActivityProviderUnavailable(
                        retry_after_seconds=retry_after
                    ) from None
                time.sleep(delay)
        if data is None:
            raise ActivityProviderUnavailable()
        content = data["choices"][0]["message"]["content"]
        return ExtractionResponse.model_validate_json(content)
    except (
        URLError,
        TimeoutError,
        OSError,
        KeyError,
        IndexError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        logger.warning("Activity extraction provider failed; error_type=%s", type(exc).__name__)
        raise ActivityProviderUnavailable() from None
    except ValidationError:
        logger.warning("Activity extraction provider returned invalid data")
        raise ActivityParsingError(
            "I couldn't safely read that activity. Please include its name and exact "
            "start/end times."
        ) from None


def extract_activities(
    db: Session,
    user_id: int,
    message: str,
    timezone: str | None,
    *,
    now: datetime | None = None,
    checkin_sent_at: datetime | None = None,
    checkin_interval_minutes: int | None = None,
) -> tuple[list[ActivityCreate], str | None]:
    timezone_name, local_zone = _resolve_timezone(timezone)
    categories = list(
        db.scalars(
            select(ActivityCategory)
            .options(selectinload(ActivityCategory.subcategories))
            .where(ActivityCategory.user_id == user_id)
            .order_by(ActivityCategory.name)
        )
    )
    category_data = [
        {
            "name": category.name,
            "subcategories": [subcategory.name for subcategory in category.subcategories],
        }
        for category in categories
    ]
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        instant = instant.replace(tzinfo=UTC)
    local_now = instant.astimezone(local_zone)
    checkin_context = None
    if checkin_sent_at is not None:
        sent_at = checkin_sent_at
        if sent_at.tzinfo is None or sent_at.utcoffset() is None:
            sent_at = sent_at.replace(tzinfo=UTC)
        checkin_context = {
            "from_local": sent_at.astimezone(local_zone).isoformat(),
            "to_local": local_now.isoformat(),
            "configured_interval_minutes": checkin_interval_minutes,
        }
    prompt = json.dumps(
        {
            "current_local_datetime": local_now.isoformat(),
            "timezone": timezone_name,
            "allowed_categories": category_data,
            "checkin_context": checkin_context,
            "user_message": message,
        },
        ensure_ascii=False,
    )
    extraction = _call_provider(prompt)
    if extraction.clarification:
        if extraction.activities:
            summaries = []
            for item in extraction.activities:
                category = _infer_category(item, categories, message)
                subcategory = (
                    next(
                        (
                            value.name
                            for value in category.subcategories
                            if value.id == _infer_subcategory(item, category, message)
                        ),
                        None,
                    )
                    if category is not None
                    else None
                )
                summaries.append(
                    _activity_summary(
                        item,
                        category.name if category is not None else None,
                        subcategory,
                    )
                )
            summary = "; ".join(summaries)
            return [], f"{summary} {extraction.clarification}"
        return [], extraction.clarification
    if not extraction.activities:
        return [], "What activity should I record, and when did it start and end?"

    activities: list[ActivityCreate] = []
    for candidate in extraction.activities:
        if candidate.confidence < CONFIDENCE_THRESHOLD:
            question = (
                "Can you confirm that I understood the activity correctly?"
                if candidate.started_at is not None and candidate.ended_at is not None
                else "What were the start and end times?"
            )
            return [], (
                f"{_activity_summary(candidate)} {question}"
            )
        category = _infer_category(candidate, categories, message)
        if category is None:
            return [], (
                f"{_activity_summary(candidate)} Which category should I use? Choose from: "
                + ", ".join(item.name for item in categories)
            )
        subcategory_id = _infer_subcategory(candidate, category, message)
        started_at = candidate.started_at
        ended_at = candidate.ended_at
        if candidate.duration_minutes and (started_at is None) != (ended_at is None):
            duration = timedelta(minutes=candidate.duration_minutes)
            if started_at is not None:
                ended_at = started_at + duration
            elif ended_at is not None:
                started_at = ended_at - duration
        if started_at is None or ended_at is None:
            detail = (
                f"I have: {candidate.title} · {category.name}"
                + (
                    f", duration {candidate.duration_minutes} minutes."
                    if candidate.duration_minutes
                    else "."
                )
            )
            return [], f"{detail} What time did it happen?"
        if ended_at <= started_at:
            return [], (
                f"{_activity_summary(candidate)} Please clarify the start and end times; "
                "the end time must be later."
            )
        try:
            activities.append(
                ActivityCreate(
                    title=candidate.title,
                    category_id=category.id,
                    subcategory_id=subcategory_id,
                    started_at=started_at,
                    ended_at=ended_at,
                    description=candidate.description,
                    notes=candidate.notes,
                    tags=candidate.tags,
                    source="telegram",
                )
            )
        except ValidationError:
            logger.warning("Validated extraction could not be represented as an activity")
            return [], "Please clarify the activity name and exact start and end times."
    return activities, None
