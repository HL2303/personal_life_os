import json
import logging
from datetime import UTC, datetime
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
        with urlopen(request, timeout=settings.ai_request_timeout_seconds) as response:
            data = json.loads(response.read())
        content = data["choices"][0]["message"]["content"]
        return ExtractionResponse.model_validate_json(content)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        KeyError,
        IndexError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        logger.warning("Activity extraction provider failed; error_type=%s", type(exc).__name__)
        raise ActivityParsingError(
            "I couldn't process that message right now. Please try again shortly."
        ) from None
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
