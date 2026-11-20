from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.assignments.states import State
from app.reviews.schemas import ReviewItem, Speaker

NextAction = Literal["start", "continue", "check", "retry"]
ActivityKind = Literal[
    "case_assigned",
    "check_ready",
    "review_opened",
    "review_closed",
    "comment_on_mine",
    "reply",
    "job_failed",
]
Outcome = Literal["accepted", "rejected", "sent_back"]


class NextUpItem(BaseModel):
    """Something waiting for the viewer. `action` is decided here, so the page has no copy of the
    workflow's rules."""

    assignment_id: UUID
    vignette_code: str
    vignette_version: int
    state: State
    action: NextAction
    # Only the admin knows whose case it is.
    expert_pseudonym: str | None
    updated_at: datetime


class ActivityItem(BaseModel):
    kind: ActivityKind
    assignment_id: UUID
    vignette_code: str
    at: datetime
    unread: bool
    # The answer a comment is under.
    question_id: str | None = None
    comment_id: UUID | None = None
    speaker: Speaker | None = None
    # The first words of a comment.
    excerpt: str | None = None
    outcome: Outcome | None = None


class ComputeStatus(BaseModel):
    # What the PC with the models doesn't offer ("ollama", "languagetool", "model X"); empty: ready.
    missing: list[str]
    checked_seconds_ago: int


class SystemStatus(BaseModel):
    """For the admin: is the background work moving?"""

    # None: the PC isn't checked here (REQUIRE_COMPUTE off).
    compute: ComputeStatus | None
    # Queued, or running on a lease that ran out.
    waiting: int
    # Of those: the PC can't run them now.
    waiting_for_pc: int
    oldest_waiting_minutes: int | None
    # A job that could run has waited for minutes: the worker isn't taking jobs.
    stuck: bool
    failed_last_day: int


class HomeView(BaseModel):
    next_up: list[NextUpItem]
    next_up_total: int
    # Open reviews the viewer has yet to vote on every answer of (for the admin: every open one).
    reviews_waiting: list[ReviewItem]
    # All of them: `reviews_waiting` stops at the first few.
    reviews_waiting_total: int
    recent_reviews: list[ReviewItem]
    activity: list[ActivityItem]
    # Counted among the items in `activity`.
    unread_activity: int
    # Only for the admin.
    system: SystemStatus | None = None


class ActivitySeen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The time of the newest item the page showed. Without it, everything up to now counts as seen,
    # which would hide what arrived while the page was loading.
    until: AwareDatetime | None = None
