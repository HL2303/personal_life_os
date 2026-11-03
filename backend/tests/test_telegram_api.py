import io
import json
from datetime import UTC, datetime, time, timedelta
from urllib.error import HTTPError

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_token
from app.models.activity import Activity, User
from app.models.telegram import (
    TelegramCheckin,
    TelegramIntegration,
    TelegramLinkToken,
    TelegramOutbox,
    TelegramUpdate,
)
from app.schemas.activity import ActivityCreate

WEBHOOK_SECRET = "test-webhook-secret-with-sufficient-entropy"


def configure_telegram(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("fake-token"))
    monkeypatch.setattr(settings, "telegram_bot_username", "personal_life_os_test_bot")
    monkeypatch.setattr(settings, "telegram_webhook_secret", SecretStr(WEBHOOK_SECRET))


def create_owner(client):
    response = client.post(
        "/api/auth/setup",
        json={"username": "telegram-owner", "password": "correct horse battery"},
    )
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def send_webhook(client, update_id, text, *, secret=WEBHOOK_SECRET, chat_id=90001):
    return client.post(
        "/api/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        json={
            "update_id": update_id,
            "message": {
                "message_id": update_id + 100,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": chat_id},
                "text": text,
            },
        },
    )


def add_integration(database, *, next_checkin_at, timezone="Asia/Kolkata"):
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        integration = TelegramIntegration(
            user_id=user.id,
            telegram_chat_id=90001,
            interval_minutes=30,
            timezone=timezone,
            active_start=time(8),
            active_end=time(22),
            quiet_start=time(22),
            quiet_end=time(8),
            paused=False,
            next_checkin_at=next_checkin_at.astimezone(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(integration)
        db.commit()
        return integration.id


def test_webhook_secret_validation_and_event_deduplication(client, monkeypatch, database):
    configure_telegram(monkeypatch)
    assert send_webhook(client, 1001, "/start", secret="incorrect").status_code == 403
    first = send_webhook(client, 1001, "/start")
    duplicate = send_webhook(client, 1001, "/start")
    assert first.status_code == duplicate.status_code == 200
    with database() as db:
        assert db.scalar(select(func.count(TelegramUpdate.id))) == 1
        assert db.scalar(select(func.count(TelegramOutbox.id))) == 1
        event = db.scalar(select(TelegramUpdate))
        assert event.status == "processed"
        assert db.scalar(select(TelegramOutbox)).text.startswith("Welcome")


def test_account_link_code_is_expiring_and_single_use(client, monkeypatch, database):
    configure_telegram(monkeypatch)
    create_owner(client)
    code_response = client.post("/api/telegram/link-code")
    assert code_response.status_code == 200
    code = code_response.json()["code"]
    assert client.get("/api/telegram/settings").json()["connected"] is False

    linked = send_webhook(client, 2001, f"/link {code}")
    assert linked.status_code == 200
    settings_response = client.get("/api/telegram/settings")
    assert settings_response.status_code == 200
    assert settings_response.json()["connected"] is True
    assert settings_response.json()["interval_minutes"] == 30

    repeated = send_webhook(client, 2002, f"/link {code}")
    assert repeated.status_code == 200
    with database() as db:
        assert db.scalar(select(func.count(TelegramIntegration.id))) == 1
        token = db.scalar(select(TelegramLinkToken))
        assert token.consumed_at is not None
        assert hash_token(code) == token.token_hash
        assert db.scalar(select(func.count(TelegramOutbox.id))) == 2
        latest_reply = db.scalars(
            select(TelegramOutbox.text).order_by(TelegramOutbox.id.desc())
        ).first()
        assert latest_reply.startswith("That link code is invalid")


def test_expired_link_token_is_rejected(client, monkeypatch, database):
    configure_telegram(monkeypatch)
    create_owner(client)
    code = "one-time-expired-link-code"
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        db.add(
            TelegramLinkToken(
                user_id=user.id,
                token_hash=hash_token(code),
                created_at=datetime.now(UTC) - timedelta(minutes=20),
                expires_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
        db.commit()
    assert send_webhook(client, 3001, f"/link {code}").status_code == 200
    with database() as db:
        assert db.scalar(select(func.count(TelegramIntegration.id))) == 0


def test_webhook_reuses_activity_validation_and_deduplicates_activity(
    client, monkeypatch, database
):
    configure_telegram(monkeypatch)
    create_owner(client)
    add_integration(database, next_checkin_at=datetime.now(UTC) + timedelta(hours=1))
    category_id = client.get("/api/categories").json()[0]["id"]

    import app.api.telegram_webhook as webhook

    extracted = ActivityCreate(
        title="Planning",
        category_id=category_id,
        started_at=datetime(2026, 11, 3, 9, tzinfo=UTC),
        ended_at=datetime(2026, 11, 3, 10, tzinfo=UTC),
        source="telegram",
    )
    monkeypatch.setattr(
        webhook,
        "extract_activities",
        lambda *_args, **_kwargs: ([extracted], None),
    )

    assert send_webhook(client, 4001, "I planned the week from 9 to 10").status_code == 200
    assert send_webhook(client, 4001, "I planned the week from 9 to 10").status_code == 200
    with database() as db:
        assert db.scalar(select(func.count(Activity.id))) == 1
        activity = db.scalar(select(Activity))
        assert activity.title == "Planning"
        assert activity.source == "telegram"


def test_commands_pause_resume_skip_and_today(client, monkeypatch, database):
    configure_telegram(monkeypatch)
    create_owner(client)
    integration_id = add_integration(
        database,
        next_checkin_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert send_webhook(client, 5001, "/pause").status_code == 200
    with database() as db:
        integration = db.get(TelegramIntegration, integration_id)
        assert integration.paused is True
    assert send_webhook(client, 5002, "/resume").status_code == 200
    with database() as db:
        integration = db.get(TelegramIntegration, integration_id)
        assert integration.paused is False
        db.add(
            TelegramCheckin(
                integration_id=integration_id,
                scheduled_for=datetime.now(UTC) - timedelta(minutes=30),
                status="sent",
                delivery_attempts=1,
                sent_at=datetime.now(UTC) - timedelta(minutes=30),
                next_attempt_at=datetime.now(UTC),
            )
        )
        db.commit()
    assert send_webhook(client, 5003, "/skip").status_code == 200
    assert send_webhook(client, 5004, "/today").status_code == 200
    with database() as db:
        skipped = db.scalar(
            select(TelegramCheckin).where(TelegramCheckin.status == "skipped")
        )
        assert skipped is not None
        assert db.scalar(select(func.count(TelegramOutbox.id))) == 4


def test_telegram_settings_validate_and_update_preferences(client, monkeypatch, database):
    configure_telegram(monkeypatch)
    create_owner(client)
    assert client.patch(
        "/api/telegram/settings",
        json={
            "interval_minutes": 30,
            "timezone": "Asia/Kolkata",
            "active_start": "08:00",
            "active_end": "22:00",
            "quiet_start": "22:00",
            "quiet_end": "08:00",
        },
    ).status_code == 409
    add_integration(database, next_checkin_at=datetime.now(UTC) + timedelta(hours=1))
    updated = client.patch(
        "/api/telegram/settings",
        json={
            "interval_minutes": 45,
            "timezone": "Asia/Kolkata",
            "active_start": "07:00",
            "active_end": "23:00",
            "quiet_start": "23:00",
            "quiet_end": "07:00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["interval_minutes"] == 45
    assert updated.json()["active_start"] == "07:00:00"
    assert updated.json()["next_checkin_at"] is not None
    invalid = client.patch(
        "/api/telegram/settings",
        json={
            "interval_minutes": 300,
            "timezone": "No/Such_Zone",
            "active_start": "08:00",
            "active_end": "22:00",
            "quiet_start": "22:00",
            "quiet_end": "08:00",
        },
    )
    assert invalid.status_code == 422


def test_webhook_rejects_non_private_chats(client, monkeypatch, database):
    configure_telegram(monkeypatch)
    response = client.post(
        "/api/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        json={
            "update_id": 6001,
            "message": {
                "message_id": 1,
                "chat": {"id": -123, "type": "group"},
                "from": {"id": 90001},
                "text": "/start",
            },
        },
    )
    assert response.status_code == 200
    with database() as db:
        assert db.scalar(select(func.count(TelegramUpdate.id))) == 0


def test_link_code_endpoint_requires_complete_bot_configuration(client, monkeypatch):
    create_owner(client)
    monkeypatch.setattr(settings, "telegram_bot_token", None)
    monkeypatch.setattr(settings, "telegram_bot_username", None)
    monkeypatch.setattr(settings, "telegram_webhook_secret", None)
    assert client.post("/api/telegram/link-code").status_code == 503


def test_telegram_webhook_registration_uses_configured_url_and_secret(monkeypatch):
    import io
    import json

    from app.telegram import configure_webhook

    configure_telegram(monkeypatch)
    monkeypatch.setattr(settings, "telegram_webhook_url", "https://example.test/")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(configure_webhook, "urlopen", fake_urlopen)
    configure_webhook.configure_webhook()
    assert captured["url"] == "https://api.telegram.org/botfake-token/setWebhook"
    assert captured["body"]["url"] == "https://example.test/api/telegram/webhook"
    assert captured["body"]["secret_token"] == WEBHOOK_SECRET
    assert captured["body"]["allowed_updates"] == ["message"]


def test_telegram_webhook_registration_rejects_non_https_url(monkeypatch):
    from app.telegram import configure_webhook

    configure_telegram(monkeypatch)
    monkeypatch.setattr(settings, "telegram_webhook_url", "http://example.test")
    with pytest.raises(RuntimeError, match="HTTPS"):
        configure_webhook.configure_webhook()


def test_activity_extraction_supports_multiple_and_requests_clarification(
    client, database, monkeypatch
):
    from app.telegram import extraction

    create_owner(client)
    category = client.get("/api/categories").json()[0]
    subcategory = client.post(
        f"/api/categories/{category['id']}/subcategories",
        json={"name": "Planning"},
    ).json()
    monkeypatch.setattr(
        settings,
        "ai_provider",
        "openai_compatible",
    )
    monkeypatch.setattr(settings, "ai_api_key", SecretStr("test-ai-key"))
    response = extraction.ExtractionResponse(
        activities=[
            extraction.ExtractedActivity(
                title="Plan sprint",
                category=category["name"],
                subcategory=subcategory["name"],
                started_at=datetime(2026, 11, 3, 9, tzinfo=UTC),
                ended_at=datetime(2026, 11, 3, 10, tzinfo=UTC),
                confidence=0.95,
            ),
            extraction.ExtractedActivity(
                title="Walk",
                category=category["name"],
                subcategory=None,
                started_at=datetime(2026, 11, 3, 10, tzinfo=UTC),
                ended_at=datetime(2026, 11, 3, 10, 30, tzinfo=UTC),
                confidence=0.9,
            ),
        ]
    )
    monkeypatch.setattr(extraction, "_call_provider", lambda _prompt: response)
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        activities, clarification = extraction.extract_activities(
            db, user.id, "I planned then walked", "UTC"
        )
        assert clarification is None
        assert [activity.title for activity in activities] == ["Plan sprint", "Walk"]
        assert activities[0].subcategory_id == subcategory["id"]

    response.activities[0].confidence = 0.4
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        activities, clarification = extraction.extract_activities(
            db, user.id, "I did something", "UTC"
        )
        assert activities == []
        assert clarification and "start and end times" in clarification

    response.activities[0].confidence = 0.95
    response.activities[0].started_at = None
    with database() as db:
        user = db.scalar(select(User).where(User.username == "telegram-owner"))
        activities, clarification = extraction.extract_activities(
            db, user.id, "I did something", "UTC"
        )
        assert activities == []
        assert clarification


def test_activity_extraction_logs_sanitized_http_provider_error(monkeypatch, caplog):
    from app.telegram import extraction

    api_key = "private-test-api-key"
    user_message = "private user message that must never appear in logs"
    provider_body = {
        "error": {
            "message": f"Rejected: {user_message}; credential={api_key}",
            "type": "rate_limit_error",
            "code": "rate_limit_exceeded",
            "authorization": "Bearer private-header",
        }
    }
    error = HTTPError(
        "https://provider.test/v1/chat/completions",
        429,
        "Too Many Requests",
        {},
        io.BytesIO(json.dumps(provider_body).encode()),
    )
    monkeypatch.setattr(settings, "ai_provider", "openai_compatible")
    monkeypatch.setattr(settings, "ai_api_key", SecretStr(api_key))

    def fail_provider_request(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(extraction, "urlopen", fail_provider_request)

    with caplog.at_level("WARNING", logger=extraction.__name__):
        with pytest.raises(extraction.ActivityParsingError, match="try again shortly"):
            extraction._call_provider(
                json.dumps({"user_message": user_message, "api_key": api_key})
            )

    assert "status_code=429" in caplog.text
    assert '"type":"rate_limit_error"' in caplog.text
    assert '"code":"rate_limit_exceeded"' in caplog.text
    assert user_message not in caplog.text
    assert api_key not in caplog.text
    assert "private-header" not in caplog.text
    assert "Rejected:" not in caplog.text


def test_worker_persists_checkins_respects_quiet_hours_and_retries(client, database):
    from app.telegram.bot_api import TelegramAPIError
    from app.telegram.worker import run_once

    def failing_sender(_chat_id, _text):
        raise TelegramAPIError("temporary error", retry_after=10)

    create_owner(client)
    due = datetime.fromisoformat("2026-11-03T09:00:00+05:30")
    add_integration(database, next_checkin_at=due)
    with database() as db:
        db.add(
            TelegramOutbox(
                dedupe_key="worker-reply",
                telegram_chat_id=90001,
                text="Queued reply",
                status="pending",
                delivery_attempts=0,
                next_attempt_at=due.astimezone(UTC),
            )
        )
        db.commit()
    results = run_once(database, now=due, sender=failing_sender)
    assert results["scheduled"] == 1
    with database() as db:
        checkin = db.scalar(select(TelegramCheckin))
        assert checkin.status == "pending"
        assert checkin.delivery_attempts == 1
        retry_at = checkin.next_attempt_at
        outbox = db.scalar(select(TelegramOutbox))
        assert outbox.status == "pending"
        assert outbox.delivery_attempts == 1
    sent = []
    run_once(
        database,
        now=retry_at + timedelta(seconds=1),
        sender=lambda chat_id, text: sent.append((chat_id, text)) or 777,
    )
    assert len(sent) == 2
    assert any(text == "Queued reply" for _chat_id, text in sent)
    with database() as db:
        checkin = db.scalar(select(TelegramCheckin))
        assert checkin.status == "sent"
        assert checkin.delivery_attempts == 2
        outbox = db.scalar(select(TelegramOutbox))
        assert outbox.status == "sent"
        assert outbox.delivery_attempts == 2
        integration = db.scalar(select(TelegramIntegration))
        integration.next_checkin_at = datetime.fromisoformat(
            "2026-11-03T22:30:00+05:30"
        ).astimezone(UTC)
        db.commit()
    quiet = datetime.fromisoformat("2026-11-03T22:31:00+05:30")
    quiet_result = run_once(database, now=quiet, sender=lambda *_: pytest.fail("quiet-hours send"))
    assert quiet_result["scheduled"] == 1
    with database() as db:
        checkins = list(db.scalars(select(TelegramCheckin).order_by(TelegramCheckin.id)))
        assert checkins[-1].status == "skipped"
