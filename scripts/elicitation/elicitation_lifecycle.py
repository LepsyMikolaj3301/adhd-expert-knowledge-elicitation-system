"""Backend rules around an ElicitationDocument: record status and the synthetic-data guard."""

from enum import StrEnum

from elicitation_schema import ElicitationDocument


class DocumentStatus(StrEnum):
    SUBMITTED = "submitted"
    EXTRACTED = "extracted"
    MEMBER_CHECKED = "member_checked"
    APPROVED = "approved"
    REJECTED = "rejected"


ALLOWED_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.SUBMITTED: {DocumentStatus.EXTRACTED},
    DocumentStatus.EXTRACTED: {DocumentStatus.MEMBER_CHECKED},
    DocumentStatus.MEMBER_CHECKED: {DocumentStatus.APPROVED, DocumentStatus.REJECTED},
    DocumentStatus.APPROVED: set(),
    DocumentStatus.REJECTED: set(),
}


class SyntheticIngestionError(Exception):
    pass


def check_transition(current: DocumentStatus, new: DocumentStatus) -> None:
    if new not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"illegal transition {current} -> {new}")


def assert_ingestible(doc: ElicitationDocument, *, production: bool) -> None:
    """Synthetic documents may run through tests, never into the production knowledge base."""
    if production and doc.is_synthetic:
        raise SyntheticIngestionError(
            f"synthetic document {doc.session_id} cannot be ingested into production"
        )
