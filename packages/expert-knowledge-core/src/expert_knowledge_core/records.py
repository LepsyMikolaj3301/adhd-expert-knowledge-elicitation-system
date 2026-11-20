"""The findings record stored in `chips.elicitation_sessions.document`.

Plain dicts (JSON in, JSON out); these TypedDicts only describe them. The web application builds
them (app.knowledge.findings), the retrieval package reads them. A record with another `version`
is not read: bump FINDINGS_VERSION when a field changes meaning.
"""

from typing import Any, Literal, TypedDict

FINDINGS_VERSION = 1
CASE = "case"  # the target of a sentence that is about the text as a whole

Direction = Literal["toward", "away", "neutral", "unclear"]


class Highlight(TypedDict):
    id: str  # h1.. (expert) | i1.. (implicit: a quote that matches the vignette but no highlight)
    origin: Literal["expert", "implicit"]
    chip: int | None
    span: list[int]  # [start, end) in the vignette
    text: str
    direction: Direction | None


class Sentence(TypedDict):
    id: str  # Q2.3
    question_id: str
    idx: int
    span: list[int]  # offsets into the stored answer, chip tokens included
    text: str
    targets: list[str]  # highlight ids and/or "case"
    assigned_by: Literal["chip", "quote", "llm", "expert"] | None


class Unit(TypedDict):
    id: str  # the highlight id, or "case"
    kind: Literal["fragment", "case"]
    highlight: str | None
    direction: Direction | None
    sentences: list[str]
    context: list[str]  # co-cited highlights
    body: str
    i1: str


class Meta(TypedDict):
    role: str | None
    framing: str
    population: str
    rating: int | None
    insufficient: bool


class Record(TypedDict, total=False):
    version: int
    session_id: str
    expert_id: str
    vignette_id: str
    vignette_version: int
    meta: Meta
    highlights: list[Highlight]
    sentences: list[Sentence]
    units: list[Unit]
    flags: list[dict[str, Any]]


def is_readable(document: Any) -> bool:
    """Whether `document` is a findings record this version can pack."""
    return (
        isinstance(document, dict)
        and document.get("version") == FINDINGS_VERSION
        and all(key in document for key in ("meta", "highlights", "sentences", "units"))
    )
