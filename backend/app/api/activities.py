from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import AuthContext, require_authenticated_user, require_csrf
from app.db.session import get_db
from app.models.activity import Activity, ActivityCategory, ActivitySubcategory, User
from app.models.goals_projects import Project
from app.schemas.activity import (
    ActivityCreate,
    ActivityRead,
    ActivitySummary,
    ActivityUpdate,
    CategoryCreate,
    CategoryDuration,
    CategoryRead,
    CategoryUpdate,
    DeleteResult,
    SubcategoryCreate,
    SubcategoryRead,
    SubcategoryUpdate,
)
from app.services.activity_service import create_activity_for_user

router = APIRouter(
    prefix="/api",
    tags=["activities"],
    dependencies=[Depends(require_authenticated_user)],
)


def _commit_or_conflict(
    db: Session, message: str = "A record with that name already exists."
) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc


def _activity_query():
    return select(Activity).options(
        selectinload(Activity.category).selectinload(ActivityCategory.subcategories),
        selectinload(Activity.subcategory),
    )


def _get_activity(db: Session, activity_id: int, user_id: int) -> Activity:
    activity = db.scalar(
        _activity_query().where(Activity.id == activity_id, Activity.user_id == user_id)
    )
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found.")
    return activity


def _get_category(db: Session, category_id: int, user_id: int) -> ActivityCategory:
    category = db.scalar(
        select(ActivityCategory).where(
            ActivityCategory.id == category_id,
            ActivityCategory.user_id == user_id,
        )
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return category


def _validate_subcategory(
    db: Session, category_id: int, subcategory_id: int | None, user_id: int
) -> None:
    if subcategory_id is None:
        return
    subcategory = db.scalar(
        select(ActivitySubcategory).where(
            ActivitySubcategory.id == subcategory_id,
            ActivitySubcategory.category_id == category_id,
            ActivitySubcategory.user_id == user_id,
        )
    )
    if subcategory is None:
        raise HTTPException(
            status_code=422,
            detail="Subcategory must belong to the selected category.",
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@router.get("/categories", response_model=list[CategoryRead])
def list_categories(
    user: User = Depends(require_authenticated_user), db: Session = Depends(get_db)
) -> list[ActivityCategory]:
    return list(
        db.scalars(
            select(ActivityCategory)
            .options(selectinload(ActivityCategory.subcategories))
            .where(ActivityCategory.user_id == user.id)
            .order_by(ActivityCategory.name)
        )
    )


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ActivityCategory:
    category = ActivityCategory(
        user_id=context.user.id, name=payload.name, color=payload.color
    )
    db.add(category)
    _commit_or_conflict(db)
    db.refresh(category)
    return category


@router.patch("/categories/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ActivityCategory:
    category = _get_category(db, category_id, context.user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    _commit_or_conflict(db)
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}", response_model=DeleteResult)
def delete_category(
    category_id: int,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> DeleteResult:
    category = _get_category(db, category_id, context.user.id)
    if db.scalar(
        select(Activity.id)
        .where(Activity.category_id == category_id, Activity.user_id == context.user.id)
        .limit(1)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Move or delete activities in this category before deleting it.",
        )
    db.delete(category)
    _commit_or_conflict(db, "Category could not be deleted.")
    return DeleteResult(deleted=True)


@router.post(
    "/categories/{category_id}/subcategories",
    response_model=SubcategoryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_subcategory(
    category_id: int,
    payload: SubcategoryCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ActivitySubcategory:
    _get_category(db, category_id, context.user.id)
    subcategory = ActivitySubcategory(
        user_id=context.user.id, category_id=category_id, name=payload.name
    )
    db.add(subcategory)
    _commit_or_conflict(db)
    db.refresh(subcategory)
    return subcategory


@router.patch("/subcategories/{subcategory_id}", response_model=SubcategoryRead)
def update_subcategory(
    subcategory_id: int,
    payload: SubcategoryUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ActivitySubcategory:
    subcategory = db.scalar(
        select(ActivitySubcategory).where(
            ActivitySubcategory.id == subcategory_id,
            ActivitySubcategory.user_id == context.user.id,
        )
    )
    if subcategory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subcategory not found.")
    subcategory.name = payload.name
    _commit_or_conflict(db)
    db.refresh(subcategory)
    return subcategory


@router.delete("/subcategories/{subcategory_id}", response_model=DeleteResult)
def delete_subcategory(
    subcategory_id: int,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> DeleteResult:
    subcategory = db.scalar(
        select(ActivitySubcategory).where(
            ActivitySubcategory.id == subcategory_id,
            ActivitySubcategory.user_id == context.user.id,
        )
    )
    if subcategory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subcategory not found.")
    db.query(Activity).filter(
        Activity.subcategory_id == subcategory_id,
        Activity.user_id == context.user.id,
    ).update({Activity.subcategory_id: None}, synchronize_session=False)
    db.delete(subcategory)
    _commit_or_conflict(db, "Subcategory could not be deleted.")
    return DeleteResult(deleted=True)


@router.get("/activities", response_model=list[ActivityRead])
def list_activities(
    start: datetime | None = None,
    end: datetime | None = None,
    category_id: int | None = Query(default=None, gt=0),
    user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> list[Activity]:
    if (start is None) != (end is None):
        raise HTTPException(
            status_code=422,
            detail="Both start and end are required for a date range.",
        )
    statement = _activity_query().where(Activity.user_id == user.id)
    if start is not None and end is not None:
        if start.utcoffset() is None or end.utcoffset() is None or end <= start:
            raise HTTPException(
                status_code=422,
                detail="Date range must be timezone-aware and end after start.",
            )
        statement = statement.where(Activity.started_at < end, Activity.ended_at > start)
    if category_id is not None:
        statement = statement.where(Activity.category_id == category_id)
    statement = statement.order_by(Activity.started_at, Activity.id)
    return list(db.scalars(statement))


@router.post("/activities", response_model=ActivityRead, status_code=status.HTTP_201_CREATED)
def create_activity(
    payload: ActivityCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Activity:
    activity = create_activity_for_user(db, context.user.id, payload)
    _commit_or_conflict(db)
    return _get_activity(db, activity.id, context.user.id)


@router.get("/activities/summary", response_model=ActivitySummary)
def activity_summary(
    start: datetime,
    end: datetime,
    user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> ActivitySummary:
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise HTTPException(
            status_code=422,
            detail="Date range must be timezone-aware and end after start.",
        )
    records = db.scalars(
        _activity_query().where(
            Activity.user_id == user.id,
            Activity.started_at < end,
            Activity.ended_at > start,
        )
    )
    range_start = _as_utc(start)
    range_end = _as_utc(end)
    grouped: dict[int, dict[str, int | str]] = defaultdict(
        lambda: {"name": "", "color": "", "duration": 0, "count": 0}
    )
    total_duration = 0
    activity_count = 0
    for activity in records:
        clipped_start = max(_as_utc(activity.started_at), range_start)
        clipped_end = min(_as_utc(activity.ended_at), range_end)
        duration = max(0, int((clipped_end - clipped_start).total_seconds()))
        if duration == 0:
            continue
        total_duration += duration
        activity_count += 1
        category = grouped[activity.category_id]
        category["name"] = activity.category.name
        category["color"] = activity.category.color
        category["duration"] = int(category["duration"]) + duration
        category["count"] = int(category["count"]) + 1
    categories = [
        CategoryDuration(
            category_id=category_id,
            category_name=str(values["name"]),
            color=str(values["color"]),
            duration_seconds=int(values["duration"]),
            activity_count=int(values["count"]),
        )
        for category_id, values in sorted(
            grouped.items(), key=lambda item: int(item[1]["duration"]), reverse=True
        )
    ]
    return ActivitySummary(
        total_duration_seconds=total_duration,
        activity_count=activity_count,
        categories=categories,
    )


@router.get("/activities/{activity_id}", response_model=ActivityRead)
def get_activity(
    activity_id: int,
    user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> Activity:
    return _get_activity(db, activity_id, user.id)


@router.patch("/activities/{activity_id}", response_model=ActivityRead)
def update_activity(
    activity_id: int,
    payload: ActivityUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Activity:
    activity = _get_activity(db, activity_id, context.user.id)
    changes = payload.model_dump(exclude_unset=True)
    category_id = changes.get("category_id", activity.category_id)
    subcategory_id = changes.get("subcategory_id", activity.subcategory_id)
    if "category_id" in changes:
        _get_category(db, category_id, context.user.id)
        if "subcategory_id" not in changes and subcategory_id is not None:
            current_subcategory = db.scalar(
                select(ActivitySubcategory).where(
                    ActivitySubcategory.id == subcategory_id,
                    ActivitySubcategory.user_id == context.user.id,
                )
            )
            if current_subcategory is None or current_subcategory.category_id != category_id:
                subcategory_id = None
                changes["subcategory_id"] = None
    _validate_subcategory(db, category_id, subcategory_id, context.user.id)
    project_id = changes.get("project_id", activity.project_id)
    if project_id is not None and db.scalar(
        select(Project.id).where(
            Project.id == project_id,
            Project.user_id == context.user.id,
        )
    ) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    start = changes.get("started_at", activity.started_at)
    end = changes.get("ended_at", activity.ended_at)
    if _as_utc(end) <= _as_utc(start):
        raise HTTPException(
            status_code=422,
            detail="End time must be after start time.",
        )
    for field, value in changes.items():
        if field in {"started_at", "ended_at"}:
            value = _as_utc(value)
        setattr(activity, field, value)
    _commit_or_conflict(db)
    return _get_activity(db, activity_id, context.user.id)


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(
    activity_id: int,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> None:
    activity = db.scalar(
        select(Activity).where(
            Activity.id == activity_id,
            Activity.user_id == context.user.id,
        )
    )
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found.")
    db.delete(activity)
    db.commit()
