from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(min_length=1, max_length=80)]
HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


def _trim_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class CategoryCreate(BaseModel):
    name: Name
    color: HexColor = "#64748b"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Category name cannot be blank.")
        return value


class CategoryUpdate(BaseModel):
    name: Name | None = None
    color: HexColor | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Category name cannot be blank.")
        return value

    @model_validator(mode="after")
    def reject_null_values(self) -> "CategoryUpdate":
        for field in ("name", "color"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class SubcategoryCreate(BaseModel):
    name: Name

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Subcategory name cannot be blank.")
        return value


class SubcategoryUpdate(BaseModel):
    name: Name

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Subcategory name cannot be blank.")
        return value


class SubcategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    name: str


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str
    subcategories: list[SubcategoryRead]


class ActivityCreate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str | None, Field(max_length=10000)] = None
    category_id: int = Field(gt=0)
    subcategory_id: int | None = Field(default=None, gt=0)
    project_id: int | None = Field(default=None, gt=0)
    started_at: datetime
    ended_at: datetime
    notes: Annotated[str | None, Field(max_length=10000)] = None
    tags: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=list, max_length=30
    )
    source: Annotated[str, Field(min_length=1, max_length=50)] = "manual"

    @field_validator("title", "source")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("description", "notes")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        return _trim_optional(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        unique: dict[str, str] = {}
        for value in values:
            tag = value.strip()
            if tag:
                unique.setdefault(tag.casefold(), tag)
        return list(unique.values())

    @field_validator("started_at", "ended_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime values must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_activity(self) -> "ActivityCreate":
        if not self.title:
            raise ValueError("Title cannot be blank.")
        if not self.source:
            raise ValueError("Source cannot be blank.")
        if self.ended_at <= self.started_at:
            raise ValueError("End time must be after start time.")
        return self


class ActivityUpdate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    description: Annotated[str | None, Field(max_length=10000)] = None
    category_id: int | None = Field(default=None, gt=0)
    subcategory_id: int | None = Field(default=None, gt=0)
    project_id: int | None = Field(default=None, gt=0)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    notes: Annotated[str | None, Field(max_length=10000)] = None
    tags: list[Annotated[str, Field(min_length=1, max_length=40)]] | None = Field(
        default=None, max_length=30
    )
    source: Annotated[str, Field(min_length=1, max_length=50)] | None = None

    @field_validator("title", "source")
    @classmethod
    def trim_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank.")
        return value

    @field_validator("description", "notes")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        return _trim_optional(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        unique: dict[str, str] = {}
        for value in values:
            tag = value.strip()
            if tag:
                unique.setdefault(tag.casefold(), tag)
        return list(unique.values())

    @field_validator("started_at", "ended_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Datetime values must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_interval(self) -> "ActivityUpdate":
        for field in ("title", "category_id", "started_at", "ended_at", "source"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        if self.started_at is not None and self.ended_at is not None:
            if self.ended_at <= self.started_at:
                raise ValueError("End time must be after start time.")
        return self


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    category_id: int
    subcategory_id: int | None
    project_id: int | None
    started_at: datetime
    ended_at: datetime
    duration_seconds: int
    notes: str | None
    tags: list[str]
    source: str
    category: CategoryRead
    subcategory: SubcategoryRead | None


class CategoryDuration(BaseModel):
    category_id: int
    category_name: str
    color: str
    duration_seconds: int
    activity_count: int


class ActivitySummary(BaseModel):
    total_duration_seconds: int
    activity_count: int
    categories: list[CategoryDuration]


class DeleteResult(BaseModel):
    deleted: bool
