from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.config import Settings, settings
from app.core.security import hash_password, hash_token, new_token
from app.db.session import get_db
from app.main import app
from app.models.activity import (
    Activity,
    ActivityCategory,
    ActivitySubcategory,
    AuthSession,
    User,
)

PASSWORD = "correct horse battery"


def test_production_requires_secure_session_cookies():
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(app_env="Production", session_cookie_secure=False)
    assert Settings(app_env=" Production ", session_cookie_secure=True).app_env == "production"


def create_owner(client):
    response = client.post(
        "/api/auth/setup",
        json={"username": "Owner", "password": PASSWORD},
    )
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


def test_only_first_account_can_be_created_and_password_is_hashed(client, database):
    assert client.get("/api/auth/setup-status").json() == {"setup_required": True}
    for path in ("/api/categories", "/api/activities", "/api/activities/1"):
        assert client.get(path).status_code == 401
    assert client.post("/api/categories", json={"name": "Private"}).status_code == 401

    weak_password = client.post(
        "/api/auth/setup", json={"username": "owner", "password": "short"}
    )
    assert weak_password.status_code == 422

    response = client.post(
        "/api/auth/setup",
        json={"username": "Owner", "password": PASSWORD},
    )
    assert response.status_code == 201
    assert response.json()["username"] == "owner"
    assert response.cookies.get(settings.session_cookie_name)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie

    session_token = response.cookies[settings.session_cookie_name]
    with database() as db:
        user = db.scalar(select(User).where(User.username == "owner"))
        stored_session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        assert user.password_hash.startswith("$argon2id$")
        assert session_token not in user.password_hash
        assert hash_token(session_token) == stored_session.token_hash
        assert session_token != stored_session.token_hash

    assert client.get("/api/auth/setup-status").json() == {"setup_required": False}
    repeated = client.post(
        "/api/auth/setup",
        json={"username": "another", "password": PASSWORD},
    )
    assert repeated.status_code == 409
    with database() as db:
        assert len(list(db.scalars(select(User)))) == 1


def test_login_logout_csrf_rotation_and_expired_session(client, database):
    create_owner(client)
    assert client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "incorrect password"},
    ).status_code == 401

    login = client.post(
        "/api/auth/login",
        json={"username": "OWNER", "password": PASSWORD},
    )
    assert login.status_code == 200
    csrf_token = login.json()["csrf_token"]
    client.headers["X-CSRF-Token"] = csrf_token
    assert client.get("/api/auth/session").status_code == 200
    refreshed = client.get("/api/auth/session").json()["csrf_token"]
    assert refreshed == csrf_token
    client.headers["X-CSRF-Token"] = refreshed

    client.headers.pop("X-CSRF-Token")
    rejected_logout = client.post("/api/auth/logout")
    assert rejected_logout.status_code == 403
    client.headers["X-CSRF-Token"] = refreshed
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 204
    assert client.get("/api/auth/session").status_code == 401

    login_again = client.post(
        "/api/auth/login",
        json={"username": "owner", "password": PASSWORD},
    )
    client.headers["X-CSRF-Token"] = login_again.json()["csrf_token"]
    expired_token = new_token()
    with database() as db:
        user = db.scalar(select(User).where(User.username == "owner"))
        db.add(
            AuthSession(
                user_id=user.id,
                token_hash=hash_token(expired_token),
                csrf_hash=hash_token(new_token()),
                created_at=datetime.now(UTC) - timedelta(days=2),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        db.commit()
    client.cookies.set(settings.session_cookie_name, expired_token)
    response = client.get("/api/activities")
    assert response.status_code == 401
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_activity_and_category_access_requires_csrf_and_same_origin(client):
    create_owner(client)
    csrf = client.headers["X-CSRF-Token"]
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/categories", json={"name": "Private"}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    client.headers["Origin"] = "https://attacker.example"
    assert client.post("/api/categories", json={"name": "Private"}).status_code == 403


def test_activity_data_is_scoped_to_its_owner(client, database):
    create_owner(client)
    first_category = client.get("/api/categories").json()[0]
    first_subcategory = client.post(
        f"/api/categories/{first_category['id']}/subcategories",
        json={"name": "Private subcategory"},
    ).json()
    first_activity = client.post(
        "/api/activities",
        json={
            "title": "Owner one",
            "category_id": first_category["id"],
            "subcategory_id": first_subcategory["id"],
            "started_at": "2026-11-03T09:00:00+00:00",
            "ended_at": "2026-11-03T10:00:00+00:00",
            "source": "manual",
        },
    )
    assert first_activity.status_code == 201

    second_token = new_token()
    second_csrf = new_token()
    with database() as db:
        second_user = User(
            username="second",
            password_hash=hash_password("another secure password"),
            created_at=datetime.now(UTC),
        )
        db.add(second_user)
        db.flush()
        second_category = ActivityCategory(
            user_id=second_user.id,
            name="Work",
            color="#112233",
        )
        db.add(second_category)
        db.flush()
        second_subcategory = ActivitySubcategory(
            user_id=second_user.id,
            category_id=second_category.id,
            name="Second user's subcategory",
        )
        db.add(second_subcategory)
        db.flush()
        second_activity = Activity(
            user_id=second_user.id,
            title="Owner two",
            category_id=second_category.id,
            subcategory_id=second_subcategory.id,
            started_at=datetime(2026, 11, 3, 11, tzinfo=UTC),
            ended_at=datetime(2026, 11, 3, 12, tzinfo=UTC),
            tags=[],
            source="manual",
        )
        db.add(second_activity)
        db.add(
            AuthSession(
                user_id=second_user.id,
                token_hash=hash_token(second_token),
                csrf_hash=hash_token(second_csrf),
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()
        second_activity_id = second_activity.id
        second_category_id = second_category.id
        with pytest.raises(IntegrityError):
            db.add(
                Activity(
                    user_id=second_user.id,
                    title="Cross-owner relationship",
                    category_id=second_category_id,
                    subcategory_id=first_subcategory["id"],
                    started_at=datetime(2026, 11, 3, 13, tzinfo=UTC),
                    ended_at=datetime(2026, 11, 3, 14, tzinfo=UTC),
                    tags=[],
                    source="manual",
                )
            )
            db.commit()
        db.rollback()

    client.cookies.set(settings.session_cookie_name, second_token)
    client.headers["X-CSRF-Token"] = second_csrf
    categories = client.get("/api/categories").json()
    assert [category["id"] for category in categories] == [second_category_id]
    activities = client.get("/api/activities").json()
    assert [activity["title"] for activity in activities] == ["Owner two"]

    assert client.get(f"/api/activities/{first_activity.json()['id']}").status_code == 404
    assert client.patch(
        f"/api/subcategories/{first_subcategory['id']}", json={"name": "stolen"}
    ).status_code == 404
    assert client.delete(f"/api/subcategories/{first_subcategory['id']}").status_code == 404
    assert client.patch(
        f"/api/activities/{first_activity.json()['id']}", json={"title": "stolen"}
    ).status_code == 404
    assert client.delete(f"/api/activities/{first_activity.json()['id']}").status_code == 404
    assert client.patch(
        f"/api/categories/{first_category['id']}", json={"name": "stolen"}
    ).status_code == 404
    assert client.delete(f"/api/categories/{first_category['id']}").status_code == 404
    assert client.post(
        "/api/activities",
        json={
            "title": "Wrong category owner",
            "category_id": first_category["id"],
            "started_at": "2026-11-03T12:00:00+00:00",
            "ended_at": "2026-11-03T13:00:00+00:00",
            "source": "manual",
        },
    ).status_code == 404
    assert client.post(
        "/api/activities",
        json={
            "title": "Wrong subcategory owner",
            "category_id": second_category_id,
            "subcategory_id": first_subcategory["id"],
            "started_at": "2026-11-03T12:00:00+00:00",
            "ended_at": "2026-11-03T13:00:00+00:00",
            "source": "manual",
        },
    ).status_code == 422
    assert client.get(f"/api/activities/{second_activity_id}").status_code == 200


def test_database_errors_return_generic_service_unavailable(client):
    def broken_database():
        raise OperationalError("SELECT 1", {}, RuntimeError("private connection detail"))
        yield

    app.dependency_overrides[get_db] = broken_database
    response = client.get("/api/auth/setup-status")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "The database is temporarily unavailable. Please try again."
    }
