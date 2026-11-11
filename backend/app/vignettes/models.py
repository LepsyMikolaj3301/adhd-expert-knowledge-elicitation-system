from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_column, utcnow


class VersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class Vignette(Base):
    __tablename__ = "vignettes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class VignetteVersion(Base):
    __tablename__ = "vignette_versions"
    __table_args__ = (UniqueConstraint("vignette_id", "version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    vignette_id: Mapped[UUID] = mapped_column(ForeignKey("app.vignettes.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[VersionStatus] = mapped_column(
        enum_column(VersionStatus, "status"), default=VersionStatus.DRAFT
    )
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    framing: Mapped[str] = mapped_column(String(32))
    question_ids: Mapped[list[str]] = mapped_column(ARRAY(String(8)))
    q4_whatif: Mapped[str | None] = mapped_column(Text)
    # A short description of the patient, shown to experts above the text.
    patient_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    variant: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Planted cues and scoring notes. Never reaches experts or peers; see the view schemas.
    design: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
