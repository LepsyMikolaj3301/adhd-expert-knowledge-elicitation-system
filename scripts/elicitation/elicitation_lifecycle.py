"""Backend rules around an ElicitationDocument: record status."""

from enum import StrEnum


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


def check_transition(current: DocumentStatus, new: DocumentStatus) -> None:
    if new not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"illegal transition {current} -> {new}")
