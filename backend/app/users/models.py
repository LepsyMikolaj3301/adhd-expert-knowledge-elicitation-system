from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Sequence, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_column, utcnow

PSEUDONYM_SEQUENCE = Sequence("user_pseudonym_seq", metadata=Base.metadata)
SYNTHETIC_PREFIX = "SYN-"


class Role(StrEnum):
    ADMIN = "admin"
    EXPERT = "expert"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            f"is_synthetic = (pseudonym LIKE '{SYNTHETIC_PREFIX}%')", name="synthetic_pseudonym"
        ),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(enum_column(Role, "role"))
    # What leaves the user table: submissions and units carry this, never the email.
    pseudonym: Mapped[str] = mapped_column(String(32), unique=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    # NULL until the invite is accepted.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
