from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ApiModel


class TaskBase(ApiModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = None
    task_type: str = Field(default="task", max_length=80)
    category: str | None = Field(default=None, max_length=80)
    status: str = Field(default="new", max_length=80)
    priority: str | None = Field(default="normal", max_length=80)
    entity_type: str | None = Field(default=None, max_length=120)
    entity_id: str | None = Field(default=None, max_length=120)
    team_id: int | None = None
    assigned_to_id: int | None = None
    delegated_to_user_id: int | None = None
    delegated_to_team_id: int | None = None
    waiting_reason: str | None = Field(default=None, max_length=80)
    waiting_reason_detail: str | None = None
    due_on: date | None = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    task_type: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=80)
    priority: str | None = Field(default=None, max_length=80)
    entity_type: str | None = Field(default=None, max_length=120)
    entity_id: str | None = Field(default=None, max_length=120)
    team_id: int | None = None
    assigned_to_id: int | None = None
    delegated_to_user_id: int | None = None
    delegated_to_team_id: int | None = None
    waiting_reason: str | None = Field(default=None, max_length=80)
    waiting_reason_detail: str | None = None
    due_on: date | None = None


class TaskRead(TaskBase):
    id: int
    created_by_id: int | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskCommentCreate(ApiModel):
    comment: str = Field(min_length=1)


class TaskCommentRead(ApiModel):
    id: int
    task_id: int
    user_id: int | None
    comment: str
    created_at: datetime
