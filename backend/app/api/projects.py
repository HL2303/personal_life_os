from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import AuthContext, require_authenticated_user, require_csrf
from app.db.session import get_db
from app.models.activity import Activity, ActivityCategory, User
from app.models.goals_projects import Project, ProjectMilestone
from app.schemas.activity import ActivityRead
from app.schemas.goals_projects import (
    MilestoneCreate,
    MilestoneUpdate,
    ProjectCreate,
    ProjectDetail,
    ProjectMilestoneRead,
    ProjectRead,
    ProjectUpdate,
)

router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_authenticated_user)],
)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This project conflicts with existing data.",
        ) from exc


def _get_project(db: Session, project_id: int, user_id: int) -> Project:
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _validate_category(db: Session, category_id: int | None, user_id: int) -> None:
    if category_id is not None and db.scalar(
        select(ActivityCategory.id).where(
            ActivityCategory.id == category_id,
            ActivityCategory.user_id == user_id,
        )
    ) is None:
        raise HTTPException(status_code=404, detail="Category not found.")


def _project_reads(
    db: Session,
    projects: list[Project],
    *,
    include_activities: bool = False,
) -> list[ProjectRead | ProjectDetail]:
    if not projects:
        return []
    project_ids = [project.id for project in projects]
    user_id = projects[0].user_id
    category_ids = {project.category_id for project in projects if project.category_id}
    category_names = dict(
        db.execute(
            select(ActivityCategory.id, ActivityCategory.name).where(
                ActivityCategory.user_id == user_id,
                ActivityCategory.id.in_(category_ids or {-1}),
            )
        ).all()
    )
    milestones_by_project: dict[int, list[ProjectMilestone]] = {
        project_id: [] for project_id in project_ids
    }
    for milestone in db.scalars(
        select(ProjectMilestone)
        .where(
            ProjectMilestone.project_id.in_(project_ids),
            ProjectMilestone.user_id == user_id,
        )
        .order_by(ProjectMilestone.due_date, ProjectMilestone.id)
    ):
        milestones_by_project[milestone.project_id].append(milestone)

    activity_by_project: dict[int, list[ActivityRead]] = {
        project_id: [] for project_id in project_ids
    }
    if include_activities:
        records = db.scalars(
            select(Activity)
            .options(
                selectinload(Activity.category).selectinload(ActivityCategory.subcategories),
                selectinload(Activity.subcategory),
            )
            .where(
                Activity.project_id.in_(project_ids),
                Activity.user_id == user_id,
            )
            .order_by(Activity.started_at.desc(), Activity.id.desc())
            .limit(100)
        )
        for activity in records:
            activity_by_project[activity.project_id].append(ActivityRead.model_validate(activity))

    results: list[ProjectRead | ProjectDetail] = []
    for project in projects:
        milestones = milestones_by_project[project.id]
        completed_count = sum(milestone.completed_at is not None for milestone in milestones)
        values = {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "category_id": project.category_id,
            "category_name": category_names.get(project.category_id),
            "status": project.status,
            "priority": project.priority,
            "start_date": project.start_date,
            "target_date": project.target_date,
            "completed_at": project.completed_at,
            "milestone_count": len(milestones),
            "completed_milestone_count": completed_count,
            "progress_percent": round(completed_count / len(milestones) * 100) if milestones else 0,
            "milestones": [
                ProjectMilestoneRead(
                    id=milestone.id,
                    title=milestone.title,
                    description=milestone.description,
                    due_date=milestone.due_date,
                    completed=milestone.completed_at is not None,
                    completed_at=milestone.completed_at,
                )
                for milestone in milestones
            ],
        }
        if include_activities:
            results.append(ProjectDetail(**values, activities=activity_by_project[project.id]))
        else:
            results.append(ProjectRead(**values))
    return results


@router.get("", response_model=list[ProjectRead])
def list_projects(
    include_archived: bool = False,
    user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> list[ProjectRead]:
    statement = select(Project).where(Project.user_id == user.id)
    if not include_archived:
        statement = statement.where(Project.status != "archived")
    projects = list(
        db.scalars(statement.order_by(Project.status, Project.target_date, Project.id))
    )
    return _project_reads(db, projects)  # type: ignore[return-value]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ProjectRead:
    _validate_category(db, payload.category_id, context.user.id)
    now = datetime.now(UTC)
    project = Project(
        user_id=context.user.id,
        created_at=now,
        updated_at=now,
        completed_at=date.today() if payload.status == "completed" else None,
        **payload.model_dump(),
    )
    db.add(project)
    _commit(db)
    return _project_reads(db, [project])[0]  # type: ignore[return-value]


@router.get("/{project_id}", response_model=ProjectDetail)
def read_project(
    project_id: int,
    user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> ProjectDetail:
    return _project_reads(db, [_get_project(db, project_id, user.id)], include_activities=True)[
        0
    ]  # type: ignore[return-value]


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ProjectRead:
    project = _get_project(db, project_id, context.user.id)
    changes = payload.model_dump(exclude_unset=True)
    _validate_category(db, changes.get("category_id", project.category_id), context.user.id)
    start_date = changes.get("start_date", project.start_date)
    target_date = changes.get("target_date", project.target_date)
    if target_date is not None and target_date < start_date:
        raise HTTPException(
            status_code=422,
            detail="Project target date cannot be before its start date.",
        )
    milestone_due = None
    if target_date is not None:
        milestone_due = db.scalar(
            select(ProjectMilestone.id)
            .where(
                ProjectMilestone.project_id == project.id,
                ProjectMilestone.due_date.is_not(None),
                ProjectMilestone.due_date > target_date,
            )
            .limit(1)
        )
    if milestone_due is not None:
        raise HTTPException(
            status_code=409,
            detail="Update milestone due dates before moving the project target date earlier.",
        )
    new_status = changes.get("status", project.status)
    if new_status == "completed":
        completion_date = changes.get("completed_at") or project.completed_at or date.today()
        if completion_date < start_date:
            raise HTTPException(
                status_code=422,
                detail="Completion date cannot be before project start.",
            )
        changes["completed_at"] = completion_date
    elif "status" in changes and new_status != "completed":
        changes["completed_at"] = None
    elif changes.get("completed_at") is not None and changes["completed_at"] < start_date:
        raise HTTPException(
            status_code=422,
            detail="Completion date cannot be before project start.",
        )
    if "title" in changes and changes["title"] is not None:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise HTTPException(status_code=422, detail="Project title cannot be blank.")
    for field in ("status", "priority", "start_date"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null.")
    if "description" in changes and changes["description"] is not None:
        changes["description"] = changes["description"].strip() or None
    for field, value in changes.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(UTC)
    _commit(db)
    return _project_reads(db, [project])[0]  # type: ignore[return-value]


@router.post(
    "/{project_id}/milestones",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project_milestone(
    project_id: int,
    payload: MilestoneCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ProjectRead:
    project = _get_project(db, project_id, context.user.id)
    if project.status == "archived":
        raise HTTPException(status_code=409, detail="Archived projects cannot be updated.")
    if payload.due_date is not None:
        if payload.due_date < project.start_date or (
            project.target_date is not None and payload.due_date > project.target_date
        ):
            raise HTTPException(
                status_code=422,
                detail="Milestone due date must be within project dates.",
            )
    db.add(
        ProjectMilestone(
            project_id=project.id,
            user_id=context.user.id,
            title=payload.title,
            description=payload.description,
            due_date=payload.due_date,
            completed_at=None,
            created_at=datetime.now(UTC),
        )
    )
    project.updated_at = datetime.now(UTC)
    _commit(db)
    return _project_reads(db, [project])[0]  # type: ignore[return-value]


@router.patch(
    "/{project_id}/milestones/{milestone_id}",
    response_model=ProjectRead,
)
def update_project_milestone(
    project_id: int,
    milestone_id: int,
    payload: MilestoneUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> ProjectRead:
    project = _get_project(db, project_id, context.user.id)
    milestone = db.scalar(
        select(ProjectMilestone).where(
            ProjectMilestone.id == milestone_id,
            ProjectMilestone.project_id == project.id,
            ProjectMilestone.user_id == context.user.id,
        )
    )
    if milestone is None:
        raise HTTPException(status_code=404, detail="Project milestone not found.")
    if project.status == "archived":
        raise HTTPException(status_code=409, detail="Archived projects cannot be updated.")
    changes = payload.model_dump(exclude_unset=True)
    if "completed" in changes:
        milestone.completed_at = datetime.now(UTC) if changes.pop("completed") else None
    if "title" in changes and changes["title"] is not None:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise HTTPException(status_code=422, detail="Milestone title cannot be blank.")
    due_date = changes.get("due_date", milestone.due_date)
    if due_date is not None and (
        due_date < project.start_date
        or (project.target_date is not None and due_date > project.target_date)
    ):
        raise HTTPException(
            status_code=422,
            detail="Milestone due date must be within project dates.",
        )
    for field, value in changes.items():
        if field == "description" and value is not None:
            value = value.strip() or None
        setattr(milestone, field, value)
    project.updated_at = datetime.now(UTC)
    _commit(db)
    return _project_reads(db, [project])[0]  # type: ignore[return-value]


@router.delete(
    "/{project_id}/milestones/{milestone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_milestone(
    project_id: int,
    milestone_id: int,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    project = _get_project(db, project_id, context.user.id)
    milestone = db.scalar(
        select(ProjectMilestone).where(
            ProjectMilestone.id == milestone_id,
            ProjectMilestone.project_id == project.id,
            ProjectMilestone.user_id == context.user.id,
        )
    )
    if milestone is None:
        raise HTTPException(status_code=404, detail="Project milestone not found.")
    db.delete(milestone)
    project.updated_at = datetime.now(UTC)
    _commit(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Response:
    project = _get_project(db, project_id, context.user.id)
    db.execute(
        update(Activity)
        .where(Activity.project_id == project.id, Activity.user_id == context.user.id)
        .values(project_id=None)
    )
    db.delete(project)
    _commit(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
