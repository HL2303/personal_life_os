from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.activity import ActivityRead

GoalType = Literal["measurable", "recurring", "milestone"]
RecordStatus = Literal["active", "completed", "paused", "archived"]
RecurringPeriod = Literal["weekly", "monthly"]
Priority = Literal["low", "medium", "high"]


class GoalFields(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    category_id: int | None = Field(default=None, gt=0)
    goal_type: GoalType
    target_value: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    current_value: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    unit: str | None = Field(default=None, max_length=40)
    recurring_period: RecurringPeriod | None = None
    start_date: date
    deadline: date
    status: RecordStatus = "active"

    @model_validator(mode="after")
    def validate_goal(self) -> "GoalFields":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Goal title cannot be blank.")
        if self.description is not None:
            self.description = self.description.strip() or None
        if self.unit is not None:
            self.unit = self.unit.strip() or None
        if self.deadline < self.start_date:
            raise ValueError("Goal deadline cannot be before its start date.")
        if self.goal_type == "milestone":
            if self.target_value is not None or self.current_value not in (None, Decimal(0)):
                raise ValueError(
                    "Milestone goals use milestone completion rather than numeric values."
                )
            if self.recurring_period is not None:
                raise ValueError("Milestone goals cannot have a recurring period.")
            self.target_value = None
            self.current_value = None
            self.unit = None
        else:
            if self.target_value is None:
                raise ValueError("Measurable and recurring goals need a target value.")
            if self.current_value is None:
                self.current_value = Decimal(0)
            if self.current_value > self.target_value:
                raise ValueError("Current progress cannot exceed the target value.")
            if not self.unit:
                raise ValueError("Measurable and recurring goals need a unit.")
            if self.goal_type == "recurring" and self.recurring_period is None:
                raise ValueError("Recurring goals need a weekly or monthly period.")
            if self.goal_type != "recurring" and self.recurring_period is not None:
                raise ValueError("Only recurring goals can have a recurring period.")
            if self.goal_type == "recurring" and self.status == "completed":
                raise ValueError("Recurring goals stay active and reset at the next period.")
        return self


class GoalCreate(GoalFields):
    pass


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    category_id: int | None = Field(default=None, gt=0)
    goal_type: GoalType | None = None
    target_value: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    current_value: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    unit: str | None = Field(default=None, max_length=40)
    recurring_period: RecurringPeriod | None = None
    start_date: date | None = None
    deadline: date | None = None
    status: RecordStatus | None = None


class GoalProgressUpdate(BaseModel):
    current_value: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    note: str | None = Field(default=None, max_length=1000)


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    due_date: date | None = None

    @model_validator(mode="after")
    def normalize_text(self) -> "MilestoneCreate":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Milestone title cannot be blank.")
        if self.description is not None:
            self.description = self.description.strip() or None
        return self


class MilestoneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    due_date: date | None = None
    completed: bool | None = None


class GoalMilestoneRead(BaseModel):
    id: int
    title: str
    description: str | None
    due_date: date | None
    completed: bool
    completed_at: datetime | None


class GoalProgressRead(BaseModel):
    previous_value: Decimal | None
    current_value: Decimal | None
    note: str | None
    recorded_at: datetime


class GoalRead(BaseModel):
    id: int
    title: str
    description: str | None
    category_id: int | None
    category_name: str | None
    goal_type: GoalType
    target_value: Decimal | None
    current_value: Decimal | None
    current_period_start: date | None
    unit: str | None
    recurring_period: RecurringPeriod | None
    start_date: date
    deadline: date
    status: RecordStatus
    progress_percent: int
    remaining_value: Decimal | None
    overdue: bool
    milestones: list[GoalMilestoneRead]
    progress_history: list[GoalProgressRead]


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    category_id: int | None = Field(default=None, gt=0)
    status: RecordStatus = "active"
    priority: Priority = "medium"
    start_date: date
    target_date: date | None = None

    @model_validator(mode="after")
    def validate_project(self) -> "ProjectCreate":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Project title cannot be blank.")
        if self.description is not None:
            self.description = self.description.strip() or None
        if self.target_date is not None and self.target_date < self.start_date:
            raise ValueError("Project target date cannot be before its start date.")
        return self


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    category_id: int | None = Field(default=None, gt=0)
    status: RecordStatus | None = None
    priority: Priority | None = None
    start_date: date | None = None
    target_date: date | None = None
    completed_at: date | None = None


class ProjectMilestoneRead(BaseModel):
    id: int
    title: str
    description: str | None
    due_date: date | None
    completed: bool
    completed_at: datetime | None


class ProjectRead(BaseModel):
    id: int
    title: str
    description: str | None
    category_id: int | None
    category_name: str | None
    status: RecordStatus
    priority: Priority
    start_date: date
    target_date: date | None
    completed_at: date | None
    milestone_count: int
    completed_milestone_count: int
    progress_percent: int
    milestones: list[ProjectMilestoneRead]


class ProjectDetail(ProjectRead):
    model_config = ConfigDict(from_attributes=True)

    activities: list[ActivityRead]
