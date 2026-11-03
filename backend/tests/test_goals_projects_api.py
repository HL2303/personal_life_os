from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.models.activity import Activity, ActivityCategory, User
from app.models.goals_projects import Goal, GoalProgressHistory, Project


def create_owner(client, username="owner"):
    response = client.post(
        "/api/auth/setup",
        json={"username": username, "password": "correct horse battery"},
    )
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def create_category(client, name="Career"):
    response = client.post(
        "/api/categories",
        json={"name": name, "color": "#123456"},
    )
    assert response.status_code == 201
    return response.json()


def measurable_goal_payload(category_id=None, **changes):
    return {
        "title": "Study 100 hours",
        "description": "Complete the course",
        "category_id": category_id,
        "goal_type": "measurable",
        "target_value": 100,
        "current_value": 0,
        "unit": "hours",
        "recurring_period": None,
        "start_date": "2026-11-01",
        "deadline": "2026-12-31",
        "status": "active",
    } | changes


def project_payload(category_id=None, **changes):
    return {
        "title": "Personal website",
        "description": "Build and publish a portfolio",
        "category_id": category_id,
        "status": "active",
        "priority": "high",
        "start_date": "2026-11-01",
        "target_date": "2026-12-31",
    } | changes


def test_measurable_goal_progress_history_and_lifecycle(client, database):
    create_owner(client)
    category = create_category(client)
    created = client.post(
        "/api/goals",
        json=measurable_goal_payload(category["id"]),
    )
    assert created.status_code == 201
    goal = created.json()
    assert goal["progress_percent"] == 0
    assert Decimal(goal["remaining_value"]) == 100
    assert goal["category_name"] == "Career"

    updated = client.patch(
        f"/api/goals/{goal['id']}/progress",
        json={"current_value": 35, "note": "Finished two lessons"},
    )
    assert updated.status_code == 200
    assert Decimal(updated.json()["current_value"]) == 35
    assert updated.json()["progress_percent"] == 35
    assert Decimal(updated.json()["remaining_value"]) == 65
    assert updated.json()["progress_history"][0]["note"] == "Finished two lessons"

    completed = client.patch(
        f"/api/goals/{goal['id']}/progress",
        json={"current_value": 100},
    )
    assert completed.json()["status"] == "completed"
    assert client.patch(
        f"/api/goals/{goal['id']}/progress",
        json={"current_value": 101},
    ).status_code == 422
    reopened = client.patch(
        f"/api/goals/{goal['id']}/progress",
        json={"current_value": 45},
    )
    assert reopened.json()["status"] == "active"

    edited = client.patch(f"/api/goals/{goal['id']}", json={"title": "Study consistently"})
    assert edited.status_code == 200
    assert edited.json()["title"] == "Study consistently"
    assert client.patch(
        f"/api/goals/{goal['id']}",
        json={"deadline": "2026-10-30"},
    ).status_code == 422

    archived = client.patch(f"/api/goals/{goal['id']}", json={"status": "archived"})
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get("/api/goals").json() == []
    assert len(client.get("/api/goals?include_archived=true").json()) == 1
    with database() as db:
        assert db.scalar(
            select(func.count(GoalProgressHistory.id)).where(
                GoalProgressHistory.goal_id == goal["id"]
            )
        ) == 4
    assert client.delete(f"/api/goals/{goal['id']}").status_code == 204
    assert client.get(f"/api/goals/{goal['id']}").status_code == 404


def test_recurring_goal_progress_resets_at_period_boundaries(client, monkeypatch):
    create_owner(client)
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 4)

    monkeypatch.setattr("app.api.goals.date", FrozenDate)
    created = client.post(
        "/api/goals",
        json=measurable_goal_payload(
            goal_type="recurring",
            title="Exercise 4 times a week",
            target_value=4,
            unit="sessions",
            recurring_period="weekly",
        ),
    )
    assert created.status_code == 201
    goal = created.json()
    assert goal["recurring_period"] == "weekly"
    assert goal["current_period_start"] is not None
    updated = client.patch(
        f"/api/goals/{goal['id']}/progress",
        json={"current_value": 4},
    )
    assert updated.status_code == 200
    assert updated.json()["progress_percent"] == 100
    assert updated.json()["status"] == "active"
    assert Decimal(updated.json()["progress_history"][0]["previous_value"]) == 0

    class FollowingWeek(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 9)

    monkeypatch.setattr("app.api.goals.date", FollowingWeek)
    reset = client.get(f"/api/goals/{goal['id']}").json()
    assert reset["current_value"] == "0"
    assert reset["current_period_start"] == "2026-11-09"
    assert reset["progress_percent"] == 0
    refreshed = client.patch(
        f"/api/goals/{goal['id']}/progress",
        json={"current_value": 1},
    ).json()
    assert refreshed["current_period_start"] == "2026-11-09"
    assert Decimal(refreshed["progress_history"][0]["previous_value"]) == 0
    assert client.post(
        "/api/goals",
        json=measurable_goal_payload(
            goal_type="recurring",
            target_value=4,
            unit="sessions",
            recurring_period=None,
        ),
    ).status_code == 422


def test_milestone_goal_progress_history_and_completion(client):
    create_owner(client)
    goal = client.post(
        "/api/goals",
        json=measurable_goal_payload(
            title="Learn a language",
            goal_type="milestone",
            target_value=None,
            current_value=None,
            unit=None,
        ),
    )
    assert goal.status_code == 201
    goal_id = goal.json()["id"]
    first = client.post(
        f"/api/goals/{goal_id}/milestones",
        json={"title": "Finish the basics", "due_date": "2026-11-30"},
    )
    assert first.status_code == 201
    first_milestone = first.json()["milestones"][0]
    assert first.json()["progress_percent"] == 0
    second = client.post(
        f"/api/goals/{goal_id}/milestones",
        json={"title": "Hold a conversation"},
    )
    assert second.json()["progress_percent"] == 0
    halfway = client.patch(
        f"/api/goals/{goal_id}/milestones/{first_milestone['id']}",
        json={"completed": True},
    )
    assert halfway.json()["progress_percent"] == 50
    second_milestone = next(
        milestone
        for milestone in halfway.json()["milestones"]
        if milestone["title"] == "Hold a conversation"
    )
    complete = client.patch(
        f"/api/goals/{goal_id}/milestones/{second_milestone['id']}",
        json={"completed": True},
    )
    assert complete.json()["progress_percent"] == 100
    assert complete.json()["status"] == "completed"
    assert len(complete.json()["progress_history"]) >= 4
    assert client.patch(
        f"/api/goals/{goal_id}/progress",
        json={"current_value": 1},
    ).status_code == 422


def test_projects_milestones_activity_association_and_delete(client, database):
    create_owner(client)
    category = create_category(client)
    created = client.post("/api/projects", json=project_payload(category["id"]))
    assert created.status_code == 201
    project = created.json()
    project_id = project["id"]
    milestone = client.post(
        f"/api/projects/{project_id}/milestones",
        json={"title": "Design", "due_date": "2026-11-30"},
    )
    assert milestone.status_code == 201
    assert milestone.json()["progress_percent"] == 0
    milestone_id = milestone.json()["milestones"][0]["id"]
    finished = client.patch(
        f"/api/projects/{project_id}/milestones/{milestone_id}",
        json={"completed": True},
    )
    assert finished.status_code == 200
    assert finished.json()["progress_percent"] == 100
    assert finished.json()["completed_milestone_count"] == 1
    assert client.patch(
        f"/api/projects/{project_id}/milestones/{milestone_id}",
        json={"due_date": "2027-01-01"},
    ).status_code == 422

    activity = client.post(
        "/api/activities",
        json={
            "title": "Build homepage",
            "category_id": category["id"],
            "project_id": project_id,
            "started_at": "2026-11-03T09:00:00+00:00",
            "ended_at": "2026-11-03T10:00:00+00:00",
        },
    )
    assert activity.status_code == 201
    assert activity.json()["project_id"] == project_id
    detail = client.get(f"/api/projects/{project_id}")
    assert detail.status_code == 200
    assert detail.json()["activities"][0]["title"] == "Build homepage"
    with database() as db:
        row = db.get(Activity, activity.json()["id"])
        assert row.project_id == project_id

    assert client.patch(
        f"/api/projects/{project_id}",
        json={"status": "completed", "completed_at": "2026-10-31"},
    ).status_code == 422
    edited = client.patch(f"/api/projects/{project_id}", json={"title": "Portfolio site"})
    assert edited.status_code == 200
    assert edited.json()["title"] == "Portfolio site"
    assert client.delete(f"/api/projects/{project_id}").status_code == 204
    with database() as db:
        row = db.get(Activity, activity.json()["id"])
        assert row.project_id is None


def test_goal_project_and_activity_references_are_user_scoped(client, database):
    create_owner(client)
    category = create_category(client)
    project = client.post("/api/projects", json=project_payload(category["id"])).json()
    goal = client.post(
        "/api/goals",
        json=measurable_goal_payload(category["id"]),
    ).json()
    foreign_user = User(
        username="second-user",
        password_hash="not-used",
        created_at=datetime.now(UTC),
    )
    with database() as db:
        db.add(foreign_user)
        db.flush()
        foreign_category = ActivityCategory(
            user_id=foreign_user.id,
            name="Private",
            color="#654321",
        )
        db.add(foreign_category)
        db.flush()
        now = datetime.now(UTC)
        foreign_goal = Goal(
            user_id=foreign_user.id,
            title="Private goal",
            description=None,
            category_id=foreign_category.id,
            goal_type="measurable",
            target_value=Decimal(1),
            current_value=Decimal(0),
            current_period_start=None,
            unit="session",
            recurring_period=None,
            start_date=datetime(2026, 11, 1).date(),
            deadline=datetime(2026, 12, 31).date(),
            status="active",
            created_at=now,
            updated_at=now,
        )
        foreign_project = Project(
            user_id=foreign_user.id,
            title="Private project",
            description=None,
            category_id=foreign_category.id,
            status="active",
            priority="medium",
            start_date=datetime(2026, 11, 1).date(),
            target_date=datetime(2026, 12, 31).date(),
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add_all([foreign_goal, foreign_project])
        db.commit()
        foreign_category_id = foreign_category.id
        foreign_goal_id = foreign_goal.id
        foreign_project_id = foreign_project.id
        foreign_user_id = foreign_user.id
    assert foreign_user_id != 1

    assert client.get(f"/api/goals/{foreign_goal_id}").status_code == 404
    assert client.get(f"/api/projects/{foreign_project_id}").status_code == 404
    assert client.post(
        "/api/goals",
        json=measurable_goal_payload(category_id=foreign_category_id),
    ).status_code == 404
    assert client.post(
        "/api/projects",
        json=project_payload(category_id=foreign_category_id),
    ).status_code == 404
    response = client.post(
        "/api/activities",
        json={
            "title": "Cross-owner project reference",
            "category_id": category["id"],
            "project_id": foreign_project_id,
            "started_at": "2026-11-03T09:00:00+00:00",
            "ended_at": "2026-11-03T10:00:00+00:00",
        },
    )
    assert response.status_code == 404
    assert client.get("/api/goals").json()[0]["id"] == goal["id"]
    assert client.get("/api/projects").json()[0]["id"] == project["id"]
