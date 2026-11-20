"""Elicitation-session schema: what the web platform hands to the backend after one expert session.

An ElicitationDocument is the unit the backend ingests (see notes/elicitation-document.md).
ReferenceClaim is fixture-only: it lives next to a document in
data/fixtures/<source>/<tier>/claims/, never inside it (tiers: see notes/fixtures.md).

Validation errors carry a stable snake_case code at the start of the message (e.g.
"vignette_hash_mismatch: ...") so tests and edge-case fixtures can name the error they expect.
"""

import hashlib
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.vignettes.questions import GATE, QUESTIONS, QuestionId

SCHEMA_VERSION = "1.1"  # 1.1: Q4 is a what-if scale (ShiftAnswer), Q1-Q3 gate
MIN_WORDS, MAX_WORDS = 120, 250

Strength = Literal["weak", "moderate", "strong"]
# "general": traits shown through mundane content. "text_analysis": probes how a clinician reads
# traits in a patient's own text - expert knowledge that the RAG corpus (criteria, guidelines,
# discourse reviews) does not contain.
Track = Literal["general", "text_analysis"]
Origin = Literal["llm", "real_text", "hand_written"]
Framing = Literal["forum_post", "personal_journal", "email"]  # where the text "was written"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PlantedCue(_Model):
    quote: str = Field(min_length=1, description="exact substring of the vignette text")
    trait: str
    strength: Strength


class Confounder(_Model):
    quote: str = Field(min_length=1, description="exact substring of the vignette text")
    alternative_explanation: str


class VignetteDesign(_Model):
    """Hidden from the expert. Used to score extraction and to audit the design."""

    purpose: str
    planted_cues: list[PlantedCue] = []
    confounders: list[Confounder] = []
    is_control: bool = False
    track: Track = "general"
    knowledge_target: str | None = Field(
        default=None, description="the expert knowledge this vignette is meant to elicit"
    )
    origin: Origin = "llm"
    population: str = Field(default="adult", description="age group of the writer, e.g. 'adult'")
    source_ref: str | None = Field(
        default=None, description="where a real_text came from, e.g. 'reddit:abc123'"
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.is_control and self.planted_cues:
            raise ValueError("control_with_cues: a control vignette cannot have planted_cues")
        if self.track == "text_analysis" and not self.knowledge_target:
            raise ValueError("track_without_target: text_analysis needs a knowledge_target")
        return self


class VariantInfo(_Model):
    """A/B pairs differ in one element: A is the base text, B changes `change`."""

    pair_id: str
    arm: Literal["A", "B"]
    change: str | None = Field(default=None, description="what B changes; required for arm B")

    @model_validator(mode="after")
    def _b_names_change(self) -> Self:
        if self.arm == "B" and not self.change:
            raise ValueError("variant_b_without_change: arm B must say what it changes")
        return self


class Vignette(_Model):
    id: str = Field(pattern=r"^V\d{3,}$")
    version: int = Field(ge=1)
    text: str = Field(min_length=1)
    framing: Framing
    question_ids: list[QuestionId] = Field(min_length=1)
    q4_whatif: str | None = Field(
        default=None,
        min_length=1,
        description="written by the vignette author: a clause completing 'how would your "
        "hypothesis change if ...', e.g. 'the writer had an exam earlier that day'",
    )
    variant: VariantInfo | None = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$", description="sha256 of `text`")
    design: VignetteDesign

    @model_validator(mode="before")
    @classmethod
    def _fill_hash(cls, data):
        if isinstance(data, dict) and "content_hash" not in data and "text" in data:
            data = {**data, "content_hash": content_hash(data["text"])}
        return data

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.content_hash != content_hash(self.text):
            raise ValueError("content_hash_mismatch: content_hash does not match text")
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("duplicate_question_id: question_ids must be unique")
        if "Q4" in self.question_ids and not (self.q4_whatif and self.q4_whatif.strip()):
            raise ValueError("q4_without_whatif: Q4 needs q4_whatif")
        spans = [c.quote for c in self.design.planted_cues]
        spans += [c.quote for c in self.design.confounders]
        for span in spans:
            if span not in self.text:
                raise ValueError(f"span_not_in_text: {span!r} is not a substring of text")
        return self

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def expert_view(self) -> dict:
        """What the platform shows the expert: everything except the hidden design block."""
        return self.model_dump(mode="json", exclude={"design"})


class ShiftAnswer(_Model):
    """Q4: how the expert's hypothesis changes given the vignette's what-if (short SCT item)."""

    hypothesis: str | None = Field(
        default=None, description="the expert's working hypothesis so far, in one sentence"
    )
    shift: int = Field(
        ge=-2, le=2, description="-2 strongly reinforced ... 0 unchanged ... +2 changes completely"
    )
    toward: Literal["more_adhd", "less_adhd", "other"] | None = Field(
        default=None, description="direction of the change; only when shift > 0"
    )
    other_explanation: str | None = Field(
        default=None, description='names the alternative when toward == "other"'
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        for name in ("hypothesis", "other_explanation"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"empty_answer: Q4 {name} is blank")
        if self.toward is not None and self.shift <= 0:
            raise ValueError("toward_without_change: toward needs a shift of +1 or +2")
        if (self.toward == "other") != (self.other_explanation is not None):
            raise ValueError(
                'other_without_name: other_explanation goes with toward="other", and only with it'
            )
        return self


class Response(_Model):
    vignette_id: str
    vignette_version: int = Field(ge=1)
    vignette_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expert_id: str = Field(min_length=1)
    answers: dict[QuestionId, str] = Field(
        description="free-text answers: open questions, and Q4's optional why"
    )
    quoted_fragments: list[str] = Field(
        default=[], description="fragments the expert marked in the text (Q1); exact substrings"
    )
    rating: int | None = Field(default=None, ge=1, le=5, description="Q6")
    insufficient_information: bool = Field(
        default=False, description='Q6 "insufficient information"'
    )
    q4: ShiftAnswer | None = Field(default=None, description="Q4 scale answer")
    started_at: AwareDatetime
    submitted_at: AwareDatetime

    @model_validator(mode="after")
    def _check(self) -> Self:
        for qid, answer in self.answers.items():
            if not answer.strip():
                raise ValueError(f"empty_answer: answer to {qid} is blank")
        if any(not f.strip() for f in self.quoted_fragments):
            raise ValueError("empty_answer: blank quoted fragment")
        if self.rating is not None and self.insufficient_information:
            raise ValueError("rating_conflict: rating and insufficient_information are exclusive")
        if "Q4" in self.answers and (self.q4 is None or self.q4.shift == 0):
            raise ValueError("q4_why_without_shift: a Q4 why needs a non-zero Q4 shift")
        if not (
            self.answers
            or self.rating is not None
            or self.insufficient_information
            or self.q4 is not None
        ):
            raise ValueError("empty_answer: response contains nothing")
        if self.submitted_at < self.started_at:
            raise ValueError("timestamps: submitted_at before started_at")
        return self


class ElicitationDocument(_Model):
    session_id: str = Field(min_length=1)
    expert_id: str = Field(min_length=1)
    created_at: AwareDatetime
    schema_version: Literal["1.1"] = SCHEMA_VERSION
    vignettes: list[Vignette] = Field(min_length=1, description="in the order shown")
    responses: list[Response]

    @model_validator(mode="after")
    def _check(self) -> Self:
        shown = {}
        for v in self.vignettes:
            if v.id in shown:
                raise ValueError(f"duplicate_vignette: {v.id} shown twice")
            shown[v.id] = v

        seen: set[str] = set()
        for r in self.responses:
            v = shown.get(r.vignette_id)
            if v is None:
                raise ValueError(f"unknown_vignette: {r.vignette_id} was not shown")
            if r.vignette_id in seen:
                raise ValueError(f"duplicate_response: {r.vignette_id} answered twice")
            seen.add(r.vignette_id)
            if r.vignette_version != v.version:
                raise ValueError(f"vignette_version_mismatch: {r.vignette_id}")
            if r.vignette_hash != v.content_hash:
                raise ValueError(f"vignette_hash_mismatch: {r.vignette_id}")
            if r.expert_id != self.expert_id:
                raise ValueError(f"expert_mismatch: response to {r.vignette_id} vs document")
            for qid in r.answers:
                if qid not in v.question_ids:
                    raise ValueError(f"question_not_asked: {qid} was not asked for {v.id}")
                if QUESTIONS[qid].kind == "rating_1_5":
                    raise ValueError(f"answer_to_rating_question: {qid} is answered via rating")
            if (r.rating is not None or r.insufficient_information) and "Q6" not in v.question_ids:
                raise ValueError(f"question_not_asked: Q6 was not asked for {v.id}")
            if r.q4 is not None and "Q4" not in v.question_ids:
                raise ValueError(f"question_not_asked: Q4 was not asked for {v.id}")
            after_gate = (
                r.q4 is not None
                or r.rating is not None
                or r.insufficient_information
                or any(q not in GATE for q in r.answers)
            )
            unanswered = [q for q in GATE if q in v.question_ids and q not in r.answers]
            if after_gate and unanswered:
                raise ValueError(
                    f"gate_not_passed: {v.id} has answers after {', '.join(GATE)} "
                    f"but none to {', '.join(unanswered)}"
                )
            for fragment in r.quoted_fragments:
                if fragment not in v.text:
                    raise ValueError(
                        f"quote_not_in_vignette: {fragment!r} is not a substring of {v.id}"
                    )
        return self


class ReferenceClaim(_Model):
    """Fixture-only: a claim an extractor should find in a response. Its trustworthiness depends on
    the fixture tier (bronze: small local model, silver: Claude, gold: human expert)."""

    vignette_id: str
    question_id: QuestionId | None = Field(
        default=None, description="the answer the claim is made in; None in older fixtures"
    )
    claim_text: str = Field(min_length=1)
    quoted_span_text: str | None = Field(
        default=None, description="exact substring of the vignette; None if the claim has no quote"
    )
    trait: str | None = None
    condition: str | None = Field(default=None, description="when the claim holds, if conditional")
    direction: Literal["raises", "lowers", "neutral"] | None = None
