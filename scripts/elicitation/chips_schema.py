"""Chip documents: highlights, direction toggles, `⟦hN⟧` citation chips.

See docs/new-chips-knowledge.md.

Scripts only: the backend schema is untouched. A ChipDocument is an ElicitationDocument whose
responses also carry `highlights`; every rule of the base schema still applies. `to_legacy` turns it
back into a plain ElicitationDocument (chips rendered as quotes) for the B1 baseline, and
`load_document` does so for the tools that read plain documents.

The synthetic chip answers leave Q4 out and always have highlights (make_chip_fixtures.py checks
that). Gold answers from notebooks/answer_vignettes.ipynb have Q4, and may cite nothing.
"""

import json
import re
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from app.elicitation.questions import QUESTIONS_BY_ID
from app.elicitation.schema import ElicitationDocument, Response, _Model

CHIP_VERSION = "1.1-chips"
CHIP_RE = re.compile(r"⟦h(\d+)⟧")
Direction = Literal["toward", "away", "neutral", "unclear"]
DIRECTIONS = ("toward", "away", "neutral", "unclear")
CHIP_QUESTIONS = ("Q1", "Q2", "Q3", "Q5", "Q6")  # no Q4: out of scope for the chip test

# Q1 asks which fragments matter in either direction ("could be ADHD" primes positive readings)
Q1_CHIPS = (
    "Which fragments of the text matter for your reading of ADHD-related traits, in either "
    "direction: pointing toward them, pointing away from them, or just ordinary? For each: what "
    "does it show, and why does this wording suggest it?"
)


def question_text(qid: str) -> str:
    return Q1_CHIPS if qid == "Q1" else QUESTIONS_BY_ID[qid].text


class Highlight(_Model):
    chip: int = Field(ge=1, description="the number shown to the expert; ⟦h<chip>⟧ in answers")
    text: str = Field(min_length=1)
    span: tuple[int, int] = Field(description="[start, end) offsets into the vignette text")
    direction: Direction


class ChipResponse(Response):
    highlights: list[Highlight] = []
    # The first this many were made before the what-if was seen. Gold only.
    locked_highlights: int = Field(default=0, ge=0)


class ChipDocument(ElicitationDocument):
    schema_version: Literal["1.1-chips"] = CHIP_VERSION  # type: ignore[assignment]
    responses: list[ChipResponse]  # type: ignore[assignment]

    @model_validator(mode="after")
    def _chips(self) -> Self:
        shown = {v.id: v for v in self.vignettes}
        for r in self.responses:
            text = shown[r.vignette_id].text
            numbers = [h.chip for h in r.highlights]
            if numbers != list(range(1, len(numbers) + 1)):
                raise ValueError(f"chip_numbers: {r.vignette_id} highlights are {numbers}")
            for h in r.highlights:
                if text[h.span[0] : h.span[1]] != h.text:
                    raise ValueError(f"highlight_not_in_vignette: {h.text!r} in {r.vignette_id}")
            for qid, answer in r.answers.items():
                for n in map(int, CHIP_RE.findall(answer)):
                    if n not in numbers:
                        raise ValueError(f"unknown_chip: ⟦h{n}⟧ in {qid} of {r.vignette_id}")
        return self


def render_chips(answer: str, highlights: list[Highlight], style: str = "quote") -> str:
    """Chips as text: `quote` = the full highlight in double quotes (B1 input), `mask` = 'that'."""
    by_chip = {h.chip: h for h in highlights}

    def one(m: re.Match) -> str:
        if style == "mask":
            return "that"
        return f'"{by_chip[int(m.group(1))].text}"'

    return CHIP_RE.sub(one, answer)


def to_legacy(doc: ChipDocument) -> ElicitationDocument:
    """The same session as a plain ElicitationDocument: chips become quotes of their highlight,
    highlights become `quoted_fragments`. This is what the regex pipeline (B1) gets."""
    data = doc.model_dump(mode="json")
    data["schema_version"] = "1.1"
    for resp, raw in zip(doc.responses, data["responses"], strict=True):
        raw["answers"] = {q: render_chips(a, resp.highlights) for q, a in resp.answers.items()}
        raw["quoted_fragments"] = list(dict.fromkeys(h.text for h in resp.highlights))
        del raw["highlights"], raw["locked_highlights"]
    return ElicitationDocument.model_validate(data)


def load_document(path: Path) -> ElicitationDocument:
    """A document file as a plain ElicitationDocument, whichever kind it is."""
    raw = json.loads(path.read_text())
    if raw.get("schema_version") == CHIP_VERSION:
        return to_legacy(ChipDocument.model_validate(raw))
    return ElicitationDocument.model_validate(raw)
