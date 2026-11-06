"""Names of the workflow's states, actions and actors. The rules are in state_machine.py."""

from enum import StrEnum


class State(StrEnum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    PROCESSING = "processing"
    PROCESSING_FAILED = "processing_failed"
    EXPERT_CHECK = "expert_check"
    BUILDING_UNITS = "building_units"
    PEER_REVIEW = "peer_review"
    INGESTING = "ingesting"
    INGESTION_FAILED = "ingestion_failed"
    INGESTED = "ingested"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset({State.INGESTED, State.REJECTED, State.CANCELLED})
# States a background job is working on: the frontend polls while it sees one of these.
JOB_STATES = frozenset({State.PROCESSING, State.BUILDING_UNITS, State.INGESTING})


class Actor(StrEnum):
    ASSIGNEE = "assignee"
    ADMIN = "admin"
    REVIEWER = "reviewer"
    SYSTEM = "system"


class Action(StrEnum):
    START = "start"
    CANCEL = "cancel"
    SUBMIT = "submit"
    PROCESSING_SUCCEEDED = "processing_succeeded"
    PROCESSING_FAILED = "processing_failed"
    COMPLETE_EXPERT_CHECK = "complete_expert_check"
    SKIP_EXPERT_CHECK = "skip_expert_check"
    UNITS_BUILT = "units_built"
    UNITS_FAILED = "units_failed"
    RETRY_PROCESSING = "retry_processing"
    RETRY_UNITS = "retry_units"
    RETRY_INGESTION = "retry_ingestion"
    APPROVE_UNITS = "approve_units"
    REQUEST_CHANGES = "request_changes"
    REJECT_ALL_UNITS = "reject_all_units"
    INGESTION_SUCCEEDED = "ingestion_succeeded"
    INGESTION_FAILED = "ingestion_failed"
