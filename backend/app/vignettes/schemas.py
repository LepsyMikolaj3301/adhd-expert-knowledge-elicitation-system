"""Admin views of a vignette. Other audiences have their own views, without `design`."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.vignettes.models import VersionStatus
from app.vignettes.questions import QuestionId

Framing = Literal["forum_post", "personal_journal", "email"]
Strength = Literal["weak", "moderate", "strong"]
Track = Literal["general", "text_analysis"]
Origin = Literal["llm", "real_text", "hand_written"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlantedCue(_Strict):
    quote: str = Field(min_length=1)
    trait: str
    strength: Strength


class Confounder(_Strict):
    quote: str = Field(min_length=1)
    alternative_explanation: str


class VignetteDesign(_Strict):
    purpose: str
    planted_cues: list[PlantedCue] = []
    confounders: list[Confounder] = []
    is_control: bool = False
    track: Track = "general"
    knowledge_target: str | None = None
    origin: Origin = "llm"
    population: str = "adult"
    source_ref: str | None = None


class VariantInfo(_Strict):
    pair_id: str
    arm: Literal["A", "B"]
    change: str | None = None


class VersionContent(_Strict):
    text: str = Field(min_length=1, max_length=20_000)
    framing: Framing
    question_ids: list[QuestionId] = Field(min_length=1)
    q4_whatif: str | None = Field(default=None, max_length=1_000)
    variant: VariantInfo | None = None
    design: VignetteDesign


class VignetteCreate(VersionContent):
    code: str = Field(pattern=r"^V\d{3,}$", max_length=32)


class VersionUpdate(_Strict):
    text: str | None = Field(default=None, min_length=1, max_length=20_000)
    framing: Framing | None = None
    question_ids: list[QuestionId] | None = Field(default=None, min_length=1)
    q4_whatif: str | None = Field(default=None, max_length=1_000)
    variant: VariantInfo | None = None
    design: VignetteDesign | None = None


class VersionAdminView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vignette_id: UUID
    version: int
    status: VersionStatus
    text: str
    content_hash: str
    framing: Framing
    question_ids: list[QuestionId]
    q4_whatif: str | None
    variant: VariantInfo | None
    design: VignetteDesign
    created_at: datetime
    published_at: datetime | None

    @computed_field
    @property
    def word_count(self) -> int:
        return len(self.text.split())


class VignetteAdminView(BaseModel):
    id: UUID
    code: str
    created_at: datetime
    versions: list[VersionAdminView]
