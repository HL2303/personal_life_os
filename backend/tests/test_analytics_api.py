from datetime import UTC, datetime

from sqlalchemy import select

from app.models.activity import Activity, ActivityCategory, User


def create_owner(client):
    response = client.post(
        "/api/auth/setup",
        json={"username": "analytics-owner", "password": "correct horse battery"},
    )
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def create_category(client, name, color):
    response = client.post("/api/categories", json={"name": name, "color": color})
    assert response.status_code == 201
    return response.json()


def create_activity(client, category_id, title, start, end):
    response = client.post(
        "/api/activities",
        json={
            "title": title,
            "category_id": category_id,
            "started_at": start,
            "ended_at": end,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_analytics_clips_local_days_and_allocates_overlaps_once(client):
    create_owner(client)
    work = create_category(client, "Career", "#123456")
    fitness = create_category(client, "Fitness", "#654321")
    create_activity(
        client,
        work["id"],
        "Earlier block",
        "2026-11-03T09:00:00+00:00",
        "2026-11-03T11:00:00+00:00",
    )
    create_activity(
        client,
        fitness["id"],
        "Overlapping block",
        "2026-11-03T10:00:00+00:00",
        "2026-11-03T12:00:00+00:00",
    )

    response = client.get(
        "/api/analytics",
        params={
            "start_date": "2026-11-03",
            "end_date": "2026-11-03",
            "timezone": "UTC",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_tracked_seconds"] == 3 * 3600
    assert body["untracked_seconds"] == 21 * 3600
    assert body["activity_count"] == 2
    assert {
        item["category_name"]: item["duration_seconds"]
        for item in body["categories"]
        if item["duration_seconds"]
    } == {
        "Career": 2 * 3600,
        "Fitness": 3600,
    }
    assert body["days"][0]["tracked_seconds"] == 3 * 3600
    assert body["previous_period"]["total_tracked_seconds"] == 0


def test_analytics_clips_to_timezone_day_and_handles_daylight_saving(client):
    create_owner(client)
    career = create_category(client, "Career", "#123456")
    create_activity(
        client,
        career["id"],
        "Overnight work",
        "2026-11-02T16:00:00+00:00",
        "2026-11-03T04:00:00+00:00",
    )
    selected_day = client.get(
        "/api/analytics",
        params={
            "start_date": "2026-11-03",
            "end_date": "2026-11-03",
            "timezone": "Asia/Kolkata",
        },
    ).json()
    assert selected_day["total_tracked_seconds"] == 9 * 3600 + 30 * 60
    assert selected_day["days"][0]["activity_count"] == 1
    assert selected_day["previous_period"]["total_tracked_seconds"] == 2 * 3600 + 30 * 60

    dst_day = client.get(
        "/api/analytics",
        params={
            "start_date": "2026-03-08",
            "end_date": "2026-03-08",
            "timezone": "America/New_York",
        },
    )
    assert dst_day.status_code == 200
    assert dst_day.json()["available_seconds"] == 23 * 3600
    assert dst_day.json()["untracked_seconds"] == 23 * 3600


def test_analytics_is_authenticated_user_scoped_and_validates_range(client, database):
    assert client.get(
        "/api/analytics",
        params={"start_date": "2026-11-03", "end_date": "2026-11-03"},
    ).status_code == 401
    create_owner(client)
    create_category(client, "Career", "#123456")
    with database() as db:
        other_user = User(
            username="another-owner",
            password_hash="not-used",
            created_at=datetime.now(UTC),
        )
        db.add(other_user)
        db.flush()
        other_category = ActivityCategory(
            user_id=other_user.id,
            name="Private",
            color="#654321",
        )
        db.add(other_category)
        db.flush()
        db.add(
            Activity(
                user_id=other_user.id,
                title="Other user's activity",
                category_id=other_category.id,
                started_at=datetime(2026, 11, 3, 9, tzinfo=UTC),
                ended_at=datetime(2026, 11, 3, 10, tzinfo=UTC),
                notes=None,
                description=None,
                tags=[],
                source="manual",
            )
        )
        db.commit()
        other_user_id = other_user.id
        assert db.scalar(select(User.id).where(User.id == other_user_id)) == other_user_id

    response = client.get(
        "/api/analytics",
        params={
            "start_date": "2026-11-03",
            "end_date": "2026-11-03",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 200
    assert response.json()["total_tracked_seconds"] == 0
    assert {
        category["category_name"] for category in response.json()["categories"]
    } == {"Career", "Errands", "Health", "Learning", "Leisure", "Personal", "Work"}
    assert client.get(
        "/api/analytics",
        params={"start_date": "2026-11-04", "end_date": "2026-11-03"},
    ).status_code == 422
    assert client.get(
        "/api/analytics",
        params={"start_date": "2026-01-01", "end_date": "2027-01-02"},
    ).status_code == 422
    assert client.get(
        "/api/analytics",
        params={
            "start_date": "2026-11-03",
            "end_date": "2026-11-03",
            "timezone": "not/a-timezone",
        },
    ).status_code == 422
