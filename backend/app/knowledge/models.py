from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_column, utcnow


class UnitStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INGESTED = "ingested"
    # Cut in an earlier review round: kept as history, never reviewed again or ingested.
    SUPERSEDED = "superseded"
    # Taken out of the knowledge base by the admin after ingestion: its chips rows are deleted.
    REMOVED = "removed"


class KnowledgeUnit(Base):
    """A reviewable unit of an expert's text. Retrieval must only ever read `ingested` units.

    A unit is a "fragment unit" (everything the expert said about one citation) or the "case unit"
    (everything about the text as a whole): notes/new-chips-knowledge.md.
    """

    # TODO(unit-structure): review whether this is the right way to cut units. Open questions are
    # listed in notes/new-chips-knowledge.md, "To review: the unit structure".

    __tablename__ = "knowledge_units"
    __table_args__ = (UniqueConstraint("assignment_id", "review_round", "ordinal"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("app.assignments.id"))
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("app.submissions.assignment_id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    # Reviewers can send the units back to the author, who corrects the filing, and the units are
    # cut again: a new round. Ordinals start at 1 in each round.
    review_round: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # What a reviewer reads: the unit's sentences verbatim, chips shown as short quotes.
    text: Mapped[str] = mapped_column(Text)
    # Covers the embedded text, so an approval is for exactly what gets embedded.
    content_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str | None] = mapped_column(String(16))  # fragment | case
    highlight_id: Mapped[str | None] = mapped_column(String(16))  # h1, i1; None for the case unit
    direction: Mapped[str | None] = mapped_column(String(16))  # toward | away | neutral | unclear
    patient_words: Mapped[str | None] = mapped_column(Text)  # the highlight, from the vignette
    sentence_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String(16)))
    context: Mapped[list[str] | None] = mapped_column(ARRAY(String(16)))  # co-cited highlights
    embed_text: Mapped[str | None] = mapped_column(Text)  # I1
    status: Mapped[UnitStatus] = mapped_column(
        enum_column(UnitStatus, "status"), default=UnitStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class AnswerFindings(Base):
    """How an answer was cut: sentences filed under citations, flags, the expert's corrections.

    Kept apart from `Submission`, which is immutable. The expert can correct this until they
    approve it (`check_outcome` is set then); the units are built from it.
    """

    __tablename__ = "answer_findings"

    assignment_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.assignments.id", ondelete="CASCADE"), primary_key=True
    )
    # app.knowledge.findings.record_from_lines plus `corrections`: ids and kinds, never answer text.
    record: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    check_outcome: Mapped[str | None] = mapped_column(String(16))  # completed | skipped
    classifier: Mapped[str | None] = mapped_column(String(64))  # None when no sentence needed it
    prompt: Mapped[str | None] = mapped_column(String(64))
    findings_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )
