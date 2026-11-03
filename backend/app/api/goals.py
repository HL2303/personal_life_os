from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import AuthContext, require_authenticated_user, require_csrf
from app.db.session import get_db
from app.models.activity import ActivityCategory, User
from app.models.goals_projects import Goal, GoalMilestone, GoalProgressHistory
from app.schemas.goals_projects import (
    GoalCreate,
    GoalMilestoneRead,
    GoalProgressRead,
    GoalProgressUpdate,
    GoalRead,
    GoalUpdate,
    MilestoneCreate,
    MilestoneUpdate,
)

router = APIRouter(
    prefix="/api/goals",
    tags=["goals"],
    dependencies=[Depends(require_authenticated_user)],
)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This goal conflicts with existing data.",
        ) from exc


def _get_goal(db: Session, goal_id: int, user_id: int) -> Goal:
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found.")
    return goal


def _validate_category(db: Session, category_id: int | None, user_id: int) -> None:
    if category_id is not None and db.scalar(
        select(ActivityCategory.id).where(
            ActivityCategory.id == category_id,
            ActivityCategory.user_id == user_id,
        )
    ) is None:
        raise HTTPException(status_code=404, detail="Category not found.")


def _period_start(value: date, period: str) -> date:
    if period == "weekly":
        return value - timedelta(days=value.weekday())
    return value.replace(day=1)


def _effective_current_value(goal: Goal, today: date) -> Decimal | None:
    if goal.goal_type != "recurring":
        return goal.current_value
    expected_period = _period_start(today, goal.recurring_period)
    if goal.current_period_start != expected_period:
        return Decimal(0)
    return goal.current_value


def _goal_reads(db: Session, goals: list[Goal]) -> list[GoalRead]:
    if not goals:
        return []
    goal_ids = [goal.id for goal in goals]
    user_id = goals[0].user_id
    category_ids = {goal.category_id for goal in goals if goal.category_id is not None}
    category_names = dict(
        db.execute(
            select(ActivityCategory.id, ActivityCategory.name).where(
                ActivityCategory.user_id == user_id,
                ActivityCategory.id.in_(category_ids or {-1}),
            )
        ).all()
    )
    milestones_by_goal: dict[int, list[GoalMilestone]] = {goal_id: [] for goal_id in goal_ids}
    for milestone in db.scalars(
        select(GoalMilestone)
        .where(GoalMilestone.user_id == user_id, GoalMilestone.goal_id.in_(goal_ids))
        .order_by(GoalMilestone.due_date, GoalMilestone.id)
    ):
        milestones_by_goal[milestone.goal_id].append(milestone)
    history_by_goal: dict[int, list[GoalProgressHistory]] = {goal_id: [] for goal_id in goal_ids}
    for history in db.scalars(
        select(GoalProgressHistory)
        .where(
            GoalProgressHistory.user_id == user_id,
            GoalProgressHistory.goal_id.in_(goal_ids),
        )
        .order_by(GoalProgressHistory.recorded_at.desc(), GoalProgressHistory.id.desc())
    ):
        if len(history_by_goal[history.goal_id]) < 100:
            history_by_goal[history.goal_id].append(history)

    today = date.today()
    results = []
    for goal in goals:
        milestones = milestones_by_goal[goal.id]
        completed_count = sum(item.completed_at is not None for item in milestones)
        if goal.goal_type == "milestone":
            progress = round(completed_count / len(milestones) * 100) if milestones else 0
            remaining = None
        else:
            current_value = _effective_current_value(goal, today)
            progress = (
                round(float(current_value / goal.target_value * 100))
                if goal.target_value
                else 0
            )
            remaining = max(Decimal(0), goal.target_value - current_value)
        if goal.goal_type == "recurring":
            current_value = _effective_current_value(goal, today)
        else:
            current_value = goal.current_value
        read_status = goal.status
        if goal.goal_type == "recurring" and goal.status == "completed" and progress < 100:
            read_status = "active"
        results.append(
            GoalRead(
                id=goal.id,
                title=goal.title,
                description=goal.description,
                category_id=goal.category_id,
                category_name=category_names.get(goal.category_id),
                goal_type=goal.goal_type,
                target_value=goal.target_value,
                current_value=current_value,
                current_period_start=(
                    _period_start(today, goal.recurring_period)
                    if goal.goal_type == "recurring"
                    else None
                ),
                unit=goal.unit,
                recurring_period=goal.recurring_period,
                start_date=goal.start_date,
                deadline=goal.deadline,
                status=read_status,
                progress_percent=progress,
                remaining_value=remaining,
                overdue=goal.status == "active" and goal.deadline < today and progress < 100,
                milestones=[
                    GoalMilestoneRead(
                        id=item.id,
                        title=item.title,
                        description=item.description,
                        due_date=item.due_date,
                        completed=item.completed_at is not None,
                        completed_at=item.completed_at,
                    )
                    for item in milestones
                ],
                progress_history=[
                    GoalProgressRead(
                        previous_value=item.previous_value,
                        current_value=item.current_value,
                        note=item.note,
                        recorded_at=item.recorded_at,
                    )
                    for item in history_by_goal[goal.id]
                ],
            )
        )
    return results


@router.get("", response_model=list[GoalRead])
def list_goals(
    include_archived: bool = False,
    user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> list[GoalRead]:
    statement = select(Goal).where(Goal.user_id == user.id)
    if not include_archived:
        statement = statement.where(Goal.status != "archived")
    goals = list(db.scalars(statement.order_by(Goal.deadline, Goal.id)))
    return _goal_reads(db, goals)


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal(
    payload: GoalCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> GoalRead:
    _validate_category(db, payload.category_id, context.user.id)
    values = payload.model_dump()
    if payload.status == "completed" and payload.goal_type == "measurable":
        if payload.current_value != payload.target_value:
            raise HTTPException(
                status_code=422,
                detail="A numeric goal is complete only when its target is reached.",
            )
    goal = Goal(
        user_id=context.user.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        current_period_start=(
            _period_start(date.today(), payload.recurring_period)
            if payload.goal_type == "recurring"
            else None
        ),
        **values,
    )
    db.add(goal)
    db.flush()
    if goal.goal_type != "milestone":
        db.add(
            GoalProgressHistory(
                goal_id=goal.id,
                user_id=context.user.id,
                previous_value=Decimal(0),
                current_value=goal.current_value,
                note="Goal created",
                recorded_at=datetime.now(UTC),
            )
        )
    _commit(db)
    return _goal_reads(db, [goal])[0]


@router.get("/{goal_id}", response_model=GoalRead)
def read_goal(
    goal_id: int,
    user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> GoalRead:
    return _goal_reads(db, [_get_goal(db, goal_id, user.id)])[0]


@router.patch("/{goal_id}", response_model=GoalRead)
def update_goal(
    goal_id: int,
    payload: GoalUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> GoalRead:
    goal = _get_goal(db, goal_id, context.user.id)
    changes = payload.model_dump(exclude_unset=True)
    merged = {
        "title": changes.get("title", goal.title),
        "description": changes.get("description", goal.description),
        "category_id": changes.get("category_id", goal.category_id),
        "goal_type": changes.get("goal_type", goal.goal_type),
        "target_value": changes.get("target_value", goal.target_value),
        "current_value": changes.get("current_value", goal.current_value),
        "unit": changes.get("unit", goal.unit),
        "recurring_period": changes.get("recurring_period", goal.recurring_period),
        "start_date": changes.get("start_date", goal.start_date),
        "deadline": changes.get("deadline", goal.deadline),
        "status": changes.get("status", goal.status),
    }
    if changes.get("goal_type") == "milestone" and goal.goal_type != "milestone":
        merged.update(
            target_value=None,
            current_value=None,
            unit=None,
            recurring_period=None,
        )
    try:
        validated = GoalCreate.model_validate(merged)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _validate_category(db, validated.category_id, context.user.id)
    if goal.goal_type == "milestone" and validated.goal_type != "milestone":
        if db.scalar(
            select(GoalMilestone.id).where(GoalMilestone.goal_id == goal.id).limit(1)
        ):
            raise HTTPException(
                status_code=409,
                detail="Delete goal milestones before changing its type.",
            )
    if "goal_type" in changes and validated.goal_type != goal.goal_type:
        if validated.goal_type == "milestone":
            changes.update(
                current_value=None,
                target_value=None,
                unit=None,
                recurring_period=None,
            )
        elif goal.goal_type == "milestone":
            if "target_value" not in changes or "unit" not in changes:
                raise HTTPException(
                    status_code=422,
                    detail="Changing from milestone goals requires a target and unit.",
                )
            changes.setdefault("current_value", Decimal(0))
    if validated.status == "completed" and validated.goal_type == "measurable":
        if validated.current_value != validated.target_value:
            raise HTTPException(
                status_code=422,
                detail="A numeric goal is complete only when its target is reached.",
            )
    if validated.status == "completed" and validated.goal_type == "milestone":
        milestone_ids = list(
            db.scalars(
                select(GoalMilestone.id).where(
                    GoalMilestone.goal_id == goal.id,
                    GoalMilestone.user_id == context.user.id,
                    GoalMilestone.completed_at.is_(None),
                )
            )
        )
        if not milestone_ids:
            total_milestones = db.scalar(
                select(GoalMilestone.id)
                .where(GoalMilestone.goal_id == goal.id, GoalMilestone.user_id == context.user.id)
                .limit(1)
            )
            if total_milestones is None:
                raise HTTPException(status_code=422, detail="Add and complete milestones first.")
        elif "status" in changes:
            raise HTTPException(
                status_code=422,
                detail="Complete all milestones before completing this goal.",
            )
    previous_value = goal.current_value
    if "current_value" in changes and goal.goal_type == "recurring":
        previous_value = _effective_current_value(goal, date.today())
        goal.current_period_start = _period_start(date.today(), goal.recurring_period)
    for field, value in changes.items():
        setattr(goal, field, value)
    goal.updated_at = datetime.now(UTC)
    if "current_value" in changes and goal.goal_type != "milestone":
        db.add(
            GoalProgressHistory(
                goal_id=goal.id,
                user_id=context.user.id,
                previous_value=previous_value,
                current_value=changes["current_value"],
                note="Progress updated",
                recorded_at=datetime.now(UTC),
            )
        )
    _commit(db)
    return _goal_reads(db, [goal])[0]


@router.patch("/{goal_id}/progress", response_model=GoalRead)
def update_goal_progress(
    goal_id: int,
    payload: GoalProgressUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> GoalRead:
    goal = _get_goal(db, goal_id, context.user.id)
    if goal.goal_type == "milestone":
        raise HTTPException(
            status_code=422,
            detail="Milestone-based progress is updated by completing milestones.",
        )
    if payload.current_value > goal.target_value:
        raise HTTPException(status_code=422, detail="Progress cannot exceed the target value.")
    if goal.status == "archived":
        raise HTTPException(status_code=409, detail="Archived goals cannot be updated.")
    previous_value = goal.current_value
    if goal.goal_type == "recurring":
        previous_value = _effective_current_value(goal, date.today())
        goal.current_period_start = _period_start(date.today(), goal.recurring_period)
    goal.current_value = payload.current_value
    if goal.goal_type == "measurable" and payload.current_value == goal.target_value:
        goal.status = "completed"
    elif goal.status == "completed":
        goal.status = "active"
    goal.updated_at = datetime.now(UTC)
    db.add(
        GoalProgressHistory(
            goal_id=goal.id,
            user_id=context.user.id,
            previous_value=previous_value,
            current_value=payload.current_value,
            note=payload.note.strip() if payload.note else None,
            recorded_at=datetime.now(UTC),
        )
    )
    _commit(db)
    return _goal_reads(db, [goal])[0]


@router.post(
    "/{goal_id}/milestones",
    response_model=GoalRead,
    status_code=status.HTTP_201_CREATED,
)
def create_goal_milestone(
    goal_id: int,
    payload: MilestoneCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> GoalRead:
    goal = _get_goal(db, goal_id, context.user.id)
    if goal.goal_type != "milestone":
        raise HTTPException(status_code=409, detail="This goal is not milestone-based.")
    if goal.status == "archived":
        raise HTTPException(status_code=409, detail="Archived goals cannot be updated.")
    if payload.due_date is not None and not goal.start_date <= payload.due_date <= goal.deadline:
        raise HTTPException(
            status_code=422,
            detail="Milestone due date must be within the goal dates.",
        )
    milestones = list(db.scalars(select(GoalMilestone).where(GoalMilestone.goal_id == goal.id)))
    previous_progress = (
        Decimal(
            round(
                sum(item.completed_at is not None for item in milestones)
                / len(milestones)
                * 100
            )
        )
        if milestones
        else Decimal(0)
    )
    db.add(
        GoalMilestone(
            goal_id=goal.id,
            user_id=context.user.id,
            title=payload.title,
            description=payload.description,
            due_date=payload.due_date,
            created_at=datetime.now(UTC),
        )
    )
    db.flush()
    updated_milestones = list(
        db.scalars(select(GoalMilestone).where(GoalMilestone.goal_id == goal.id))
    )
    current_progress = Decimal(
        round(
            sum(item.completed_at is not None for item in updated_milestones)
            / len(updated_milestones)
            * 100
        )
    )
    db.add(
        GoalProgressHistory(
            goal_id=goal.id,
            user_id=context.user.id,
            previous_value=previous_progress,
            current_value=current_progress,
            note="Milestone added; progress is completed milestones as a percentage",
            recorded_at=datetime.now(UTC),
        )
    )
    if goal.status == "completed":
        goal.status = "active"
    goal.updated_at = datetime.now(UTC)
    _commit(db)
    return _goal_reads(db, [goal])[0]


@router.patch("/{goal_id}/milestones/{milestone_id}", response_model=GoalRead)
def update_goal_milestone(
    goal_id: int,
    milestone_id: int,
    payload: MilestoneUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> GoalRead:
    goal = _get_goal(db, goal_id, context.user.id)
    milestone = db.scalar(
        select(GoalMilestone).where(
            GoalMilestone.id == milestone_id,
            GoalMilestone.goal_id == goal.id,
            GoalMilestone.user_id == context.user.id,
        )
    )
    if milestone is None:
        raise HTTPException(status_code=404, detail="Goal milestone not found.")
    if goal.status == "archived":
        raise HTTPException(status_code=409, detail="Archived goals cannot be updated.")
    changes = payload.model_dump(exclude_unset=True)
    previous_completion = milestone.completed_at
    previous_progress_records = list(
        db.scalars(select(GoalMilestone).where(GoalMilestone.goal_id == goal.id))
    )
    previous_progress = (
        Decimal(
            round(
                sum(item.completed_at is not None for item in previous_progress_records)
                / len(previous_progress_records)
                * 100
            )
        )
        if previous_progress_records
        else Decimal(0)
    )
    if "completed" in changes:
        completed = changes.pop("completed")
        milestone.completed_at = datetime.now(UTC) if completed else None
    for field, value in changes.items():
        if field == "title" and value is not None:
            value = value.strip()
            if not value:
                raise HTTPException(status_code=422, detail="Milestone title cannot be blank.")
        if field == "due_date" and value is not None:
            if not goal.start_date <= value <= goal.deadline:
                raise HTTPException(
                    status_code=422,
                    detail="Milestone due date must be within the goal dates.",
                )
        setattr(milestone, field, value)
    db.flush()
    goal_milestones = list(
        db.scalars(select(GoalMilestone).where(GoalMilestone.goal_id == goal.id))
    )
    current_progress = (
        Decimal(
            round(
                sum(item.completed_at is not None for item in goal_milestones)
                / len(goal_milestones)
                * 100
            )
        )
        if goal_milestones
        else Decimal(0)
    )
    db.add(
        GoalProgressHistory(
            goal_id=goal.id,
            user_id=context.user.id,
            previous_value=previous_progress,
            current_value=current_progress,
            note="Milestone completion changed",
            recorded_at=datetime.now(UTC),
        )
    )
    if current_progress == 100:
        goal.status = "completed"
    elif previous_completion is None and goal.status == "completed":
        goal.status = "active"
    goal.updated_at = datetime.now(UTC)
    _commit(db)
    return _goal_reads(db, [goal])[0]


@router.delete("/{goal_id}/milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal_milestone(
    goal_id: int,
    milestone_id: int,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    goal = _get_goal(db, goal_id, context.user.id)
    milestone = db.scalar(
        select(GoalMilestone).where(
            GoalMilestone.id == milestone_id,
            GoalMilestone.goal_id == goal.id,
            GoalMilestone.user_id == context.user.id,
        )
    )
    if milestone is None:
        raise HTTPException(status_code=404, detail="Goal milestone not found.")
    milestones = list(db.scalars(select(GoalMilestone).where(GoalMilestone.goal_id == goal.id)))
    previous_progress = (
        Decimal(
            round(sum(item.completed_at is not None for item in milestones) / len(milestones) * 100)
        )
        if milestones
        else Decimal(0)
    )
    db.delete(milestone)
    db.flush()
    remaining = list(db.scalars(select(GoalMilestone).where(GoalMilestone.goal_id == goal.id)))
    current_progress = (
        Decimal(
            round(sum(item.completed_at is not None for item in remaining) / len(remaining) * 100)
        )
        if remaining
        else Decimal(0)
    )
    db.add(
        GoalProgressHistory(
            goal_id=goal.id,
            user_id=context.user.id,
            previous_value=previous_progress,
            current_value=current_progress,
            note="Milestone removed; progress is completed milestones as a percentage",
            recorded_at=datetime.now(UTC),
        )
    )
    if goal.status == "completed":
        goal.status = "active"
    goal.updated_at = datetime.now(UTC)
    _commit(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(
    goal_id: int,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    goal = _get_goal(db, goal_id, context.user.id)
    db.delete(goal)
    _commit(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
