from datetime import UTC

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity, ActivityCategory, ActivitySubcategory
from app.models.goals_projects import Project
from app.schemas.activity import ActivityCreate


def create_activity_for_user(
    db: Session,
    user_id: int,
    payload: ActivityCreate,
    *,
    source: str | None = None,
) -> Activity:
    category = db.scalar(
        select(ActivityCategory).where(
            ActivityCategory.id == payload.category_id,
            ActivityCategory.user_id == user_id,
        )
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    if payload.subcategory_id is not None:
        subcategory = db.scalar(
            select(ActivitySubcategory).where(
                ActivitySubcategory.id == payload.subcategory_id,
                ActivitySubcategory.category_id == payload.category_id,
                ActivitySubcategory.user_id == user_id,
            )
        )
        if subcategory is None:
            raise HTTPException(
                status_code=422,
                detail="Subcategory must belong to the selected category.",
            )
    if payload.project_id is not None and db.scalar(
        select(Project.id).where(
            Project.id == payload.project_id,
            Project.user_id == user_id,
        )
    ) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    activity_values = payload.model_dump()
    activity_values["started_at"] = payload.started_at.astimezone(UTC)
    activity_values["ended_at"] = payload.ended_at.astimezone(UTC)
    if source is not None:
        activity_values["source"] = source
    activity = Activity(user_id=user_id, **activity_values)
    db.add(activity)
    db.flush()
    return activity
