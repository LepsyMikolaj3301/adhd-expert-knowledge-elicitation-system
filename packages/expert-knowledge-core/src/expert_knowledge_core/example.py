# ruff: noqa: E501  (the sentence table is data)
"""The worked example of notes/new-chips-knowledge.md (vignette V001) as a findings record.

For tests, the READMEs and smoke scripts: a record shaped like what the web application stores,
one sentence per proofread line, cut into units the way `app.knowledge.findings.build_units` does
(the contract test in tests/test_expert_rag_contract.py checks that they agree).
"""

from copy import deepcopy
from typing import Any, cast

from expert_knowledge_core.notes import by_question, header
from expert_knowledge_core.records import CASE, FINDINGS_VERSION, Record

FRAGMENTS = [
    ("numbers on screen keep looking like they are moving when I blink", "away"),
    ("I haven't slept well since moving into this new flat two months ago", "away"),
    ("every time I try to type a formula my hand starts shaking slightly", "unclear"),
    (
        "the whole thing falls apart again like last week when I forgot to file the forms until "
        "Monday morning",
        "toward",
    ),
]
VIGNETTE = (
    "So here I am staring at the spreadsheet and the "
    f"{FRAGMENTS[0][0]} which is mostly because {FRAGMENTS[1][0]} and {FRAGMENTS[2][0]} so I will "
    f"make coffee but it is due on Friday and if I do not get it right then {FRAGMENTS[3][0]}. "
    "The radiator is new. I will sort it out tomorrow."
)

# (id, text, targets): one sentence per line, as the proofread answers have them.
_SENTENCES: list[tuple[str, str, list[str]]] = [
    ("Q1.1", "⟦h3⟧ could be read as motor restlessness under task difficulty, but it's shaky ground.", ["h3"]),
    ("Q1.2", '⟦h4⟧: the "again" suggests a repeated pattern of disorganisation.', ["h4"]),
    ("Q1.3", "I'm hedging heavily on both: hand shaking is more often anxiety or physiology, and the forgetting could just as well be sleep deprivation.", ["h3", "h4"]),
    ("Q2.1", "⟦h2⟧ explains most of this more parsimoniously: ⟦h1⟧, ⟦h3⟧, the gritty eyes, the fog.", ["h2", "h1", "h3"]),
    ("Q2.2", "The 'falling apart' at work is more likely acute burnout than chronic disorganisation.", ["h4"]),
    ("Q2.3", "What would distinguish them: lapses that also occur when sleep is adequate.", [CASE]),
    ("Q3.1", "I'm missing baseline functioning before the move.", [CASE]),
    ("Q3.2", "Does ⟦h3⟧ happen only when tired?", ["h3"]),
    ("Q5.1", "A less experienced clinician might take ⟦h3⟧ and ⟦h1⟧ as hyperactivity, missing that they follow from insomnia.", ["h3", "h1"]),
    ("Q5.2", "They might also under-read ⟦h4⟧ as a one-off.", ["h4"]),
]  # fmt: skip


def example_record(
    session_id: str = "S1", expert_id: str = "X1", role: str | None = None
) -> Record:
    meta: dict[str, Any] = {
        "role": role,
        "framing": "personal_journal",
        "population": "adult",
        "rating": None,
        "insufficient": True,
    }
    highlights: list[dict[str, Any]] = []
    for chip, (text, direction) in enumerate(FRAGMENTS, 1):
        start = VIGNETTE.index(text)
        highlights.append(
            {
                "id": f"h{chip}",
                "origin": "expert",
                "chip": chip,
                "span": [start, start + len(text)],
                "text": text,
                "direction": direction,
            }
        )
    sentences: list[dict[str, Any]] = [
        {
            "id": sid,
            "question_id": sid.split(".")[0],
            "idx": int(sid.split(".")[1]),
            "span": [0, len(text)],
            "text": text,
            "targets": targets,
            "assigned_by": "chip" if "⟦" in text else "llm",
        }
        for sid, text, targets in _SENTENCES
    ]
    targeted: dict[str, list[dict[str, Any]]] = {}
    context: dict[str, list[str]] = {}
    for s in sentences:
        for t in s["targets"]:
            targeted.setdefault(t, []).append(s)
        cited = [t for t in s["targets"] if t != CASE]
        for t in cited:
            for other in cited:
                if other != t and other not in context.setdefault(t, []):
                    context[t].append(other)
    by_id = {h["id"]: h for h in highlights}
    units: list[dict[str, Any]] = []
    for target in [h["id"] for h in highlights if h["id"] in targeted] + [CASE]:
        h = by_id.get(target)
        unit: dict[str, Any] = {
            "id": target,
            "kind": "case" if target == CASE else "fragment",
            "highlight": None if target == CASE else target,
            "direction": h["direction"] if h else None,
            "sentences": [s["id"] for s in targeted[target]],
            "context": context.get(target, []),
        }
        lines = by_question(targeted[target], highlights)
        head = header(meta, unit)
        unit["body"] = "\n".join(lines)
        unit["i1"] = "\n".join([head, *lines])
        unit["i3"] = "\n".join([head, f'Patient: "{h["text"]}"', *lines]) if h else unit["i1"]
        units.append(unit)
    return cast(
        Record,
        deepcopy(
            {
                "version": FINDINGS_VERSION,
                "session_id": session_id,
                "expert_id": expert_id,
                "vignette_id": "V001",
                "vignette_version": 1,
                "meta": meta,
                "highlights": highlights,
                "sentences": sentences,
                "units": units,
                "flags": [],
            }
        ),
    )
