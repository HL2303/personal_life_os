from datetime import UTC, datetime, timedelta


def create_category(client, name="Work"):
    setup_status = client.get("/api/auth/setup-status").json()
    if setup_status["setup_required"]:
        response = client.post(
            "/api/auth/setup",
            json={"username": "owner", "password": "correct horse battery"},
        )
        assert response.status_code == 201
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    categories = client.get("/api/categories").json()
    existing = next((category for category in categories if category["name"] == name), None)
    if existing is not None:
        return existing
    response = client.post(
        "/api/categories",
        json={"name": name, "color": "#123456"},
    )
    assert response.status_code == 201
    return response.json()


def activity_payload(category_id, **overrides):
    payload = {
        "title": "Project planning",
        "description": "Plan the next milestone",
        "category_id": category_id,
        "started_at": "2026-11-03T09:00:00+05:30",
        "ended_at": "2026-11-03T10:30:00+05:30",
        "notes": "Focus block",
        "tags": ["planning", "deep work", "Planning"],
        "source": "manual",
    }
    return payload | overrides


def test_category_and_subcategory_crud(client):
    create_category(client)
    categories = client.get("/api/categories").json()
    assert {category["name"] for category in categories} == {
        "Errands",
        "Health",
        "Learning",
        "Leisure",
        "Personal",
        "Work",
    }

    category = create_category(client)
    assert category["color"] == "#5B6EED"
    renamed = client.patch(f"/api/categories/{category['id']}", json={"name": "Office"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Office"
    assert client.patch(f"/api/categories/{category['id']}", json={"name": None}).status_code == 422

    created = client.post(
        f"/api/categories/{category['id']}/subcategories", json={"name": "Planning"}
    )
    assert created.status_code == 201
    assert created.json()["category_id"] == category["id"]

    category = next(
        entry
        for entry in client.get("/api/categories").json()
        if entry["id"] == category["id"]
    )
    assert category["subcategories"][0]["name"] == "Planning"

    updated = client.patch(f"/api/subcategories/{created.json()['id']}", json={"name": "Strategy"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Strategy"

    deleted = client.delete(f"/api/subcategories/{created.json()['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}


def test_activity_create_read_update_delete_and_category_protection(client):
    category = create_category(client)
    payload = activity_payload(category["id"])
    created = client.post("/api/activities", json=payload)

    assert created.status_code == 201
    body = created.json()
    assert body["title"] == payload["title"]
    assert body["duration_seconds"] == 5400
    assert body["tags"] == ["planning", "deep work"]
    assert body["category"]["name"] == "Work"
    assert client.get(f"/api/activities/{body['id']}").status_code == 200

    assert client.delete(f"/api/categories/{category['id']}").status_code == 409

    updated = client.patch(
        f"/api/activities/{body['id']}",
        json={"title": "Updated planning", "notes": "Revised", "tags": ["review"]},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated planning"
    assert updated.json()["notes"] == "Revised"
    assert updated.json()["tags"] == ["review"]

    deleted = client.delete(f"/api/activities/{body['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/activities/{body['id']}").status_code == 404
    assert client.delete(f"/api/categories/{category['id']}").json() == {"deleted": True}


def test_activity_source_and_subcategory_deletion(client):
    category = create_category(client)
    subcategory = client.post(
        f"/api/categories/{category['id']}/subcategories", json={"name": "Planning"}
    ).json()
    payload = activity_payload(category["id"], subcategory_id=subcategory["id"], source="import")
    activity = client.post("/api/activities", json=payload)

    assert activity.status_code == 201
    assert activity.json()["source"] == "import"
    assert activity.json()["subcategory"]["name"] == "Planning"

    assert client.delete(f"/api/subcategories/{subcategory['id']}").status_code == 200
    refreshed = client.get(f"/api/activities/{activity.json()['id']}").json()
    assert refreshed["subcategory_id"] is None


def test_activity_validation_rejects_bad_interval_and_category_mismatch(client):
    work = create_category(client, "Work")
    health = create_category(client, "Health")
    subcategory = client.post(
        f"/api/categories/{health['id']}/subcategories", json={"name": "Running"}
    ).json()

    invalid_interval = client.post(
        "/api/activities",
        json=activity_payload(
            work["id"],
            started_at="2026-11-03T10:00:00+00:00",
            ended_at="2026-11-03T09:00:00+00:00",
        ),
    )
    assert invalid_interval.status_code == 422

    no_timezone = client.post(
        "/api/activities",
        json=activity_payload(
            work["id"],
            started_at="2026-11-03T09:00:00",
        ),
    )
    assert no_timezone.status_code == 422

    mismatched = client.post(
        "/api/activities",
        json=activity_payload(work["id"], subcategory_id=subcategory["id"]),
    )
    assert mismatched.status_code == 422

    blank_title = client.post("/api/activities", json=activity_payload(work["id"], title=" "))
    assert blank_title.status_code == 422


def test_retrospective_entries_list_by_date_and_summary_clips_to_day(client):
    category = create_category(client)
    previous_day = client.post(
        "/api/activities",
        json=activity_payload(
            category["id"],
            title="Late work",
            started_at="2026-11-02T23:30:00+00:00",
            ended_at="2026-11-03T00:30:00+00:00",
        ),
    )
    same_day = client.post(
        "/api/activities",
        json=activity_payload(
            category["id"],
            title="Morning work",
            started_at="2026-11-03T08:00:00+00:00",
            ended_at="2026-11-03T09:00:00+00:00",
        ),
    )
    assert previous_day.status_code == 201
    assert same_day.status_code == 201

    start = datetime(2026, 11, 3, tzinfo=UTC)
    end = start + timedelta(days=1)
    params = {"start": start.isoformat(), "end": end.isoformat()}
    activities = client.get("/api/activities", params=params).json()
    assert [activity["title"] for activity in activities] == ["Late work", "Morning work"]

    summary = client.get("/api/activities/summary", params=params)
    assert summary.status_code == 200
    assert summary.json()["total_duration_seconds"] == 5400
    assert summary.json()["activity_count"] == 2
    assert summary.json()["categories"][0]["duration_seconds"] == 5400


def test_duplicate_names_and_missing_records_return_useful_errors(client):
    category = create_category(client)
    duplicate = client.post("/api/categories", json={"name": "Work"})
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]

    first = client.post(
        f"/api/categories/{category['id']}/subcategories", json={"name": "Planning"}
    )
    duplicate_subcategory = client.post(
        f"/api/categories/{category['id']}/subcategories", json={"name": "Planning"}
    )
    assert first.status_code == 201
    assert duplicate_subcategory.status_code == 409
    assert client.get("/api/activities/999").status_code == 404


def test_update_rejects_null_required_fields_and_invalid_resulting_interval(client):
    category = create_category(client)
    created = client.post("/api/activities", json=activity_payload(category["id"])).json()
    assert client.patch(f"/api/activities/{created['id']}", json={"title": None}).status_code == 422
    assert (
        client.patch(
            f"/api/activities/{created['id']}",
            json={"ended_at": "2026-11-03T08:00:00+05:30"},
        ).status_code
        == 422
    )
