from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, utcnow


class ProofreadRound(Base):
    """One round of the author's edited answers: proofread for round 1, sent back by the admin
    for the later ones. Frozen once `submitted_at` is set: reviewers read exactly that."""

    __tablename__ = "proofread_rounds"

    assignment_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.assignments.id", ondelete="CASCADE"), primary_key=True
    )
    review_round: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Bumped by every save of the author's edits: a stale tab can't overwrite a newer one.
    version: Mapped[int] = mapped_column(Integer, default=1)
    # The expert's citations and the implicit ones (quoted words not cited), as findings records
    # them: [{id, origin, chip, span, text, direction}].
    highlights: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # findings.check() as first shown: ids, kinds and messages.
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Which passes ran: per question, and the tool versions.
    passes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    classifier: Mapped[str | None] = mapped_column(String(64))
    prompt: Mapped[str | None] = mapped_column(String(64))
    # The admin's requests for changes that opened this round: [{question_id, comment}].
    feedback: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class AnswerRevision(Base):
    """One answer in one round: what the expert wrote, what proofreading proposed, and what the
    author made of it. `lines` links each line of `final` to citations."""

    __tablename__ = "answer_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assignment_id", "review_round"],
            ["app.proofread_rounds.assignment_id", "app.proofread_rounds.review_round"],
            ondelete="CASCADE",
        ),
    )

    assignment_id: Mapped[UUID] = mapped_column(primary_key=True)
    review_round: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    original: Mapped[str] = mapped_column(Text)
    proposed: Mapped[str] = mapped_column(Text)
    final: Mapped[str] = mapped_column(Text)
    # [{text, targets, assigned_by}], one per line of `final`. Empty for answers that are not
    # filed (Q4's why).
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Sentences dropped as unreadable.
    dropped: Mapped[list[str]] = mapped_column(JSONB, default=list)
