from datetime import datetime
from typing import Annotated, Literal
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


class UserAdminView(UserView):
    """What the admin sees: also whether the person has yet to accept their invite."""

    invite_pending: bool

    @model_validator(mode="before")
    @classmethod
    def _from_user(cls, value: object) -> object:
        # Built from a User row, which has the password hash instead of the flag.
        if hasattr(value, "password_hash"):
            return {
                **{name: getattr(value, name) for name in UserView.model_fields},
                "invite_pending": value.password_hash is None,
            }
        return value


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    role: Role


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class InvitedUser(BaseModel):
    user: UserAdminView
    # One-time path to hand to the user, e.g. /invite/abc. Never retrievable again.
    invite_path: str


class InviteIssued(BaseModel):
    invite_path: str


class CaseCounts(BaseModel):
    open: int
    in_review: int
    done: int
    stopped: int  # cancelled or rejected


class PersonCard(BaseModel):
    """Who a pseudonym is, for everyone but the admin: no name, no email."""

    audience: Literal["peer"] = "peer"
    pseudonym: str
    role: Role


class PersonAdminCard(BaseModel):
    audience: Literal["admin"] = "admin"
    pseudonym: str
    role: Role
    display_name: str
    email: str
    is_active: bool
    is_synthetic: bool
    cases: CaseCounts


PersonView = Annotated[PersonAdminCard | PersonCard, Field(discriminator="audience")]
