from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.users.models import Role


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    role: Role
    pseudonym: str
    is_synthetic: bool
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    role: Role
    is_synthetic: bool = False

    @model_validator(mode="after")
    def _synthetic_is_expert(self) -> Self:
        if self.is_synthetic and self.role != Role.EXPERT:
            raise ValueError("only experts can be synthetic")
        return self


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class InvitedUser(BaseModel):
    user: UserView
    # One-time path to hand to the user, e.g. /invite/abc. Never retrievable again.
    invite_path: str


class InviteIssued(BaseModel):
    invite_path: str
