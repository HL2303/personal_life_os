import json
from datetime import UTC, datetime, time

from sqlalchemy import select

from app.core.config import Settings, settings
from app.models.activity import Activity, User
from app.models.telegram import TelegramIntegration
from app.schemas.activity import ActivityCreate


def create_owner(client):
    response = client.post(
        "/api/auth/setup",
        json={"username": "telegram-owner", "password": "correct horse battery"},
    )
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def create_taxonomy(client):
    existing = {category["name"]: category for category in client.get("/api/categories").json()}
    fitness = existing.get("Fitness") or client.post(
        "/api/categories", json={"name": "Fitness", "color": "#123456"}
    ).json()
    gym = client.post(
        f"/api/categories/{fitness['id']}/subcategories",
        json={"name": "Gym"},
    ).json()
    learning = existing.get("Learning") or client.post(
        "/api/categories", json={"name": "Learning", "color": "#654321"}
    ).json()
    programming = client.post(
        f"/api/categories/{learning['id']}/subcategories",
        json={"name": "Programming"},
    ).json()
    return fitness, gym, learning, programming


def candidate(extraction, title, *, category=None, subcategory=None, **kwargs):
    return extraction.ExtractedActivity(
        title=title,
        category=category,
        subcategory=subcategory,
        confidence=0.95,
        **kwargs,
    )


def test_infers_only_existing_user_taxonomy_and_computes_explicit_duration(
    client, database, monkeypatch
):
    from app.telegram import extraction

    create_owner(client)
    fitness, gym, learning, programming = create_taxonomy(client)
    monkeypatch.setattr(settings, "ai_provider", "openai_compatible")
    monkeypatch.setattr(settings, "default_timezone", "Asia/Kolkata")
    prompt_values = []
    responses = iter(
        [
            extraction.ExtractionResponse(
                activities=[
                    candidate(
                        extraction,
                        "Gym",
                        started_at=datetime.fromisoformat("2026-03-10T09:00:00+05:30"),
                        ended_at=datetime.fromisoformat("2026-03-10T10:00:00+05:30"),
                    )
                ]
            ),
            extraction.ExtractionResponse(
                activities=[
                    candidate(
                        extraction,
                        "Studied Python",
                        started_at=datetime.fromisoformat("2026-03-10T14:00:00+05:30"),
                        duration_minutes=45,
                    )
                ]
            ),
        ]
    )

    def fake_provider(prompt):
        prompt_values.append(json.loads(prompt))
        return next(responses)

    monkeypatch.setattr(extraction, "_call_provider", fake_provider)
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        gym_activities, clarification = extraction.extract_activities(
            db, user.id, "Went to gym", None, now=datetime(2026, 3, 10, 4, tzinfo=UTC)
        )
        assert clarification is None
        assert gym_activities[0].category_id == fitness["id"]
        assert gym_activities[0].subcategory_id == gym["id"]

        study_activities, clarification = extraction.extract_activities(
            db,
            user.id,
            "Studied Python for 45 minutes",
            None,
            now=datetime(2026, 3, 10, 4, tzinfo=UTC),
        )
        assert clarification is None
        assert study_activities[0].category_id == learning["id"]
        assert study_activities[0].subcategory_id == programming["id"]
        duration_seconds = (
            study_activities[0].ended_at - study_activities[0].started_at
        ).total_seconds()
        assert duration_seconds == 2700
        assert study_activities[0].ended_at.isoformat() == "2026-03-10T14:45:00+05:30"

    assert prompt_values[0]["timezone"] == "Asia/Kolkata"
    assert prompt_values[0]["current_local_datetime"] == "2026-03-10T09:30:00+05:30"
    assert {item["name"] for item in prompt_values[0]["allowed_categories"]} >= {
        "Fitness",
        "Learning",
    }


def test_explicit_pm_range_and_relative_evening_keep_local_date(
    client, database, monkeypatch
):
    from app.telegram import extraction

    create_owner(client)
    create_taxonomy(client)
    monkeypatch.setattr(settings, "ai_provider", "openai_compatible")
    responses = iter(
        [
            extraction.ExtractionResponse(
                activities=[
                    candidate(
                        extraction,
                        "Gym",
                        category="Fitness",
                        subcategory="Gym",
                        started_at=datetime.fromisoformat("2026-03-10T21:00:00+05:30"),
                        ended_at=datetime.fromisoformat("2026-03-10T22:00:00+05:30"),
                    )
                ]
            ),
            extraction.ExtractionResponse(
                activities=[
                    candidate(
                        extraction,
                        "Gym",
                        category="Fitness",
                        subcategory="Gym",
                        started_at=datetime.fromisoformat("2026-03-09T19:00:00+05:30"),
                        ended_at=datetime.fromisoformat("2026-03-09T20:00:00+05:30"),
                    )
                ]
            ),
        ]
    )
    prompts = []
    monkeypatch.setattr(
        extraction,
        "_call_provider",
        lambda prompt: (prompts.append(json.loads(prompt)) or next(responses)),
    )
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        pm_range, clarification = extraction.extract_activities(
            db,
            user.id,
            "Gym 9 to 10 PM",
            "Asia/Kolkata",
            now=datetime(2026, 3, 10, 18, tzinfo=UTC),
        )
        assert clarification is None
        assert pm_range[0].started_at.isoformat() == "2026-03-10T21:00:00+05:30"

        yesterday, clarification = extraction.extract_activities(
            db,
            user.id,
            "Gym yesterday evening",
            "Asia/Kolkata",
            now=datetime(2026, 3, 10, 18, tzinfo=UTC),
        )
        assert clarification is None
        assert yesterday[0].started_at.date().isoformat() == "2026-03-09"
    assert prompts[0]["current_local_datetime"] == "2026-03-10T23:30:00+05:30"
    assert prompts[0]["timezone"] == "Asia/Kolkata"


def test_midnight_uses_fallback_timezone_and_checkin_context(client, database, monkeypatch):
    from app.telegram import extraction

    create_owner(client)
    create_taxonomy(client)
    monkeypatch.setattr(settings, "default_timezone", "America/Los_Angeles")
    prompts = []
    monkeypatch.setattr(
        extraction,
        "_call_provider",
        lambda prompt: (
            prompts.append(json.loads(prompt))
            or extraction.ExtractionResponse(
                activities=[
                    candidate(
                        extraction,
                        "Gym",
                        category="Fitness",
                        subcategory="Gym",
                        started_at=datetime.fromisoformat("2026-01-01T20:00:00-08:00"),
                        ended_at=datetime.fromisoformat("2026-01-01T21:00:00-08:00"),
                    )
                ]
            )
        ),
    )
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        activities, clarification = extraction.extract_activities(
            db,
            user.id,
            "Gym last night",
            None,
            now=datetime(2026, 1, 2, 4, 15, tzinfo=UTC),
            checkin_sent_at=datetime(2026, 1, 2, 3, 45, tzinfo=UTC),
            checkin_interval_minutes=30,
        )
        assert clarification is None
        assert activities[0].started_at.date().isoformat() == "2026-01-01"
    assert prompts[0]["timezone"] == "America/Los_Angeles"
    assert prompts[0]["current_local_datetime"] == "2026-01-01T20:15:00-08:00"
    assert prompts[0]["checkin_context"] == {
        "from_local": "2026-01-01T19:45:00-08:00",
        "to_local": "2026-01-01T20:15:00-08:00",
        "configured_interval_minutes": 30,
    }


def test_ambiguous_time_requests_one_clarification_without_saving(
    client, database, monkeypatch
):
    from app.telegram import extraction

    create_owner(client)
    create_taxonomy(client)
    monkeypatch.setattr(
        extraction,
        "_call_provider",
        lambda _prompt: extraction.ExtractionResponse(
            activities=[
                candidate(
                    extraction,
                    "Gym",
                    category="Fitness",
                    subcategory="Gym",
                )
            ],
            clarification="Was that 9–10 AM or 9–10 PM?",
        ),
    )
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        activities, clarification = extraction.extract_activities(
            db,
            user.id,
            "Gym 9 to 10",
            "Asia/Kolkata",
            now=datetime(2026, 3, 10, 12, tzinfo=UTC),
        )
        assert activities == []
        assert clarification.startswith("I have: Gym · Fitness · Gym.")
        assert "9–10 AM or 9–10 PM" in clarification
        assert db.scalar(select(Activity).where(Activity.user_id == user.id)) is None


def test_duration_without_time_is_preserved_and_requests_timing(
    client, database, monkeypatch
):
    from app.telegram import extraction

    create_owner(client)
    create_taxonomy(client)
    monkeypatch.setattr(
        extraction,
        "_call_provider",
        lambda _prompt: extraction.ExtractionResponse(
            activities=[
                candidate(
                    extraction,
                    "Studied Python",
                    category="Learning",
                    subcategory="Programming",
                    duration_minutes=45,
                )
            ]
        ),
    )
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        activities, clarification = extraction.extract_activities(
            db,
            user.id,
            "Studied Python for 45 minutes",
            "Asia/Kolkata",
            now=datetime(2026, 3, 10, 12, tzinfo=UTC),
        )
        assert activities == []
        assert "45 minutes" in clarification
        assert "What time did it happen?" in clarification
        assert db.scalar(select(Activity).where(Activity.user_id == user.id)) is None


def test_unknown_category_is_not_created_or_used(client, database, monkeypatch):
    from app.telegram import extraction

    create_owner(client)
    categories_before = client.get("/api/categories").json()
    monkeypatch.setattr(
        extraction,
        "_call_provider",
        lambda _prompt: extraction.ExtractionResponse(
            activities=[
                candidate(
                    extraction,
                    "Astronomy",
                    category="Astronomy",
                    started_at=datetime.fromisoformat("2026-03-10T09:00:00+05:30"),
                    ended_at=datetime.fromisoformat("2026-03-10T10:00:00+05:30"),
                )
            ]
        ),
    )
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        activities, clarification = extraction.extract_activities(
            db, user.id, "Astronomy", "Asia/Kolkata"
        )
        assert activities == []
        assert clarification and "Which category should I use?" in clarification
        assert db.scalar(select(Activity).where(Activity.user_id == user.id)) is None
    assert {item["name"] for item in client.get("/api/categories").json()} == {
        item["name"] for item in categories_before
    }


def test_application_default_timezone_must_be_an_iana_zone():
    assert Settings(_env_file=None, APP_DEFAULT_TIMEZONE="Asia/Kolkata").default_timezone == (
        "Asia/Kolkata"
    )


def test_clarification_conversation_keeps_prior_message(client, database, monkeypatch):
    from pydantic import SecretStr

    from app.api import telegram_webhook

    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("fake-token"))
    monkeypatch.setattr(settings, "telegram_webhook_secret", SecretStr("test-webhook-secret"))
    create_owner(client)
    category, *_ = create_taxonomy(client)
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        db.add(
            TelegramIntegration(
                user_id=user.id,
                telegram_chat_id=90001,
                interval_minutes=30,
                timezone="Asia/Kolkata",
                active_start=time(8),
                active_end=time(22),
                quiet_start=time(22),
                quiet_end=time(8),
                paused=False,
                next_checkin_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()
    calls = []

    def fake_extract(db, user_id, message, timezone, **kwargs):
        calls.append((message, timezone, kwargs))
        if len(calls) == 1:
            return [], "What time did the gym session start and end?"
        return (
            [
                ActivityCreate(
                    title="Gym",
                    category_id=category["id"],
                    started_at=datetime.fromisoformat("2026-03-10T09:00:00+05:30"),
                    ended_at=datetime.fromisoformat("2026-03-10T10:00:00+05:30"),
                    source="telegram",
                )
            ],
            None,
        )

    monkeypatch.setattr(telegram_webhook, "extract_activities", fake_extract)
    def send(update_id, text):
        return client.post(
            "/api/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"},
            json={
                "update_id": update_id,
                "message": {
                    "message_id": update_id,
                    "chat": {"id": 90001, "type": "private"},
                    "from": {"id": 90001},
                    "text": text,
                },
            },
        )

    assert send(99001, "Went to gym").status_code == 200
    assert send(99002, "9 to 10").status_code == 200
    assert "Went to gym" in calls[1][0]
    assert "Previous extraction: What time did the gym session start and end?" in calls[1][0]
    assert "Clarification: 9 to 10" in calls[1][0]
    assert calls[1][1] == "Asia/Kolkata"
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        assert db.scalar(select(Activity).where(Activity.user_id == user.id)) is not None
        assert db.scalar(select(TelegramIntegration)).pending_message_text is None
