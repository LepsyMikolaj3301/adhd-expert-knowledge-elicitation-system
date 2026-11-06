"""Imports every table so that Base.metadata is complete (Alembic, tests)."""

from app.assignments.models import AnswerDraft, Assignment, Submission
from app.audit.models import AuditEvent
from app.auth.models import AuthSession, Invite
from app.jobs.models import Job
from app.knowledge.models import AnswerFindings, KnowledgeUnit
from app.reviews.models import ReviewParticipant, SubmissionVote, UnitComment, UnitDecision
from app.users.models import User
from app.vignettes.models import Vignette, VignetteVersion

__all__ = [
    "AnswerDraft",
    "AnswerFindings",
    "Assignment",
    "AuditEvent",
    "AuthSession",
    "Invite",
    "Job",
    "KnowledgeUnit",
    "ReviewParticipant",
    "Submission",
    "SubmissionVote",
    "UnitComment",
    "UnitDecision",
    "User",
    "Vignette",
    "VignetteVersion",
]
