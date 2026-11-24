import json
import logging
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import ceil
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
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
    category: Annotated[str, Field(min_length=1, max_length=80)]
    subcategory: Annotated[str | None, Field(max_length=80)] = None
    started_at: datetime | None
    ended_at: datetime | None
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
                            "a title, category, start/end time, date, duration, or timezone. "
                            "Return one JSON object with keys activities and clarification. "
                            "activities is an array of objects with title, category (one exact "
                            "provided category), subcategory (provided subcategory or null), "
                            "started_at and ended_at as ISO-8601 datetimes including timezone "
                            "offsets, description, notes, tags, and confidence from 0 to 1. "
                            "If a time, category, or activity meaning is unclear, omit uncertain "
                            "activities and provide a concise clarification question. If the "
                            "message has multiple activities, extract each separately. Use the "
                            "given local date/time and timezone to resolve relative dates. "
                            "Do not create overlapping or guessed intervals."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.ai_api_key.get_secret_value()}",
            "Content-Type": "application/json",
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
    timezone: str,
    *,
    now: datetime | None = None,
) -> tuple[list[ActivityCreate], str | None]:
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
    local_now = (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone))
    prompt = json.dumps(
        {
            "current_local_datetime": local_now.isoformat(),
            "timezone": timezone,
            "allowed_categories": category_data,
            "user_message": message,
        },
        ensure_ascii=False,
    )
    extraction = _call_provider(prompt)
    if extraction.clarification:
        return [], extraction.clarification
    if not extraction.activities:
        return [], "What activity should I record, and when did it start and end?"

    categories_by_name = {category.name.casefold(): category for category in categories}
    activities: list[ActivityCreate] = []
    for candidate in extraction.activities:
        if (
            candidate.confidence < CONFIDENCE_THRESHOLD
            or candidate.started_at is None
            or candidate.ended_at is None
        ):
            return [], (
                "I need a bit more detail before logging that. What was the activity, "
                "and what were its start and end times?"
            )
        category = categories_by_name.get(candidate.category.casefold())
        if category is None:
            return [], (
                f"Which category should I use for “{candidate.title}”? Choose from: "
                + ", ".join(item.name for item in categories)
            )
        subcategory_id = None
        if candidate.subcategory:
            subcategory = next(
                (
                    item
                    for item in category.subcategories
                    if item.name.casefold() == candidate.subcategory.casefold()
                ),
                None,
            )
            if subcategory is None:
                options = ", ".join(item.name for item in category.subcategories) or "none"
                return [], (
                    f"Which subcategory should I use for “{candidate.title}”? "
                    f"Available under {category.name}: {options}."
                )
            subcategory_id = subcategory.id
        if candidate.ended_at <= candidate.started_at:
            return [], (
                f"Please clarify the start and end times for “{candidate.title}”; "
                "the end time must be later."
            )
        try:
            activities.append(
                ActivityCreate(
                    title=candidate.title,
                    category_id=category.id,
                    subcategory_id=subcategory_id,
                    started_at=candidate.started_at,
                    ended_at=candidate.ended_at,
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
