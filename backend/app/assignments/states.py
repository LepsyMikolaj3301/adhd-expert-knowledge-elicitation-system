"""Names of the workflow's states, actions and actors. The rules are in state_machine.py."""

from enum import StrEnum


class State(StrEnum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    # The answers are proofread and their sentences linked to the citations (a job).
    PROOFREADING = "proofreading"
    # The author checks the edited answers and the links, then submits them for review.
    PROOFREAD_CHECK = "proofread_check"
    PEER_REVIEW = "peer_review"
    # The accepted answers are cut into units (a job), then ingested.
    PROCESSING = "processing"
    PROCESSING_FAILED = "processing_failed"
    INGESTING = "ingesting"
    INGESTION_FAILED = "ingestion_failed"
    INGESTED = "ingested"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset({State.INGESTED, State.REJECTED, State.CANCELLED})
# States a background job is working on: the frontend polls while it sees one of these.
JOB_STATES = frozenset({State.PROOFREADING, State.PROCESSING, State.INGESTING})


class Actor(StrEnum):
    ASSIGNEE = "assignee"
    ADMIN = "admin"
    REVIEWER = "reviewer"
    SYSTEM = "system"


class Action(StrEnum):
    START = "start"
    CANCEL = "cancel"
    SUBMIT = "submit"
    PROOFREAD_SUCCEEDED = "proofread_succeeded"
    PROOFREAD_FAILED = "proofread_failed"
    SUBMIT_FOR_REVIEW = "submit_for_review"
    PROCESSING_SUCCEEDED = "processing_succeeded"
    PROCESSING_FAILED = "processing_failed"
    RETRY_PROOFREAD = "retry_proofread"
    RETRY_PROCESSING = "retry_processing"
    RETRY_INGESTION = "retry_ingestion"
    APPROVE_ANSWERS = "approve_answers"
    REQUEST_CHANGES = "request_changes"
    REJECT_ALL_ANSWERS = "reject_all_answers"
    INGESTION_SUCCEEDED = "ingestion_succeeded"
    INGESTION_FAILED = "ingestion_failed"
