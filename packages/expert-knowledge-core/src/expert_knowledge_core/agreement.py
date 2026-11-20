"""Where clinicians agree: which experts marked the same passage of a text, and how they read it.

Pure functions over the experts' highlights of ONE version of a vignette. Nothing here reads a
database or a model, and nothing decides who is right: it counts. The web application stores the
result (chips.fragment_groups), the retrieval package prints it in a note, and the evaluation
scripts call the same code.

"The same passage" is fuzzy by position, not by meaning: two highlights are linked when their
spans overlap by at least `IOU_THRESHOLD` (intersection over union), and links chain, so
a-b and b-c put all three in one group. Whether two different passages are explained alike is a
separate question that is not answered here.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

IOU_THRESHOLD = 0.5
RULE_VERSION = 1  # bump when the grouping or the labels change meaning
AGREED_SHARE = 0.75  # share of the attending experts in one direction that counts as agreed

DIRECTIONS = ("toward", "away", "neutral", "unclear")
Label = Literal["single", "split", "agreed", "leaning"]


@dataclass(frozen=True)
class Mark:
    """One highlight of one expert: `span` is [start, end) in the vignette."""

    id: str
    expert: str
    span: tuple[int, int]
    direction: str | None


@dataclass(frozen=True)
class Agreement:
    span: tuple[int, int]  # the union of the group's spans
    k: int  # experts who marked the passage (each counted once)
    n: int  # experts who answered this text
    counts: dict[str, int] = field(default_factory=dict)  # direction -> experts; "mixed" too
    label: Label = "single"


def iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def group_marks(marks: Sequence[Mark], threshold: float = IOU_THRESHOLD) -> list[list[Mark]]:
    """Groups the marks of one vignette version: linked when IoU >= threshold, transitively.
    Groups and members keep the order of first appearance in `marks`."""
    parent = list(range(len(marks)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(marks):
        for j in range(i + 1, len(marks)):
            if iou(a.span, marks[j].span) >= threshold:
                parent[find(j)] = find(i)
    groups: dict[int, list[Mark]] = {}
    for i, mark in enumerate(marks):
        groups.setdefault(find(i), []).append(mark)
    return list(groups.values())


def expert_directions(group: Sequence[Mark]) -> dict[str, str]:
    """Each expert's reading of the passage: their direction, or `mixed` when their highlights
    in the group disagree. A highlight without a direction reads as `unclear`."""
    seen: dict[str, set[str]] = {}
    for mark in group:
        seen.setdefault(mark.expert, set()).add(mark.direction or "unclear")
    return {e: next(iter(d)) if len(d) == 1 else "mixed" for e, d in seen.items()}


def summarise(group: Sequence[Mark], n_answered: int) -> Agreement:
    """k of n experts marked the passage; how their directions are spread; one label.

    single   one expert
    split    toward and away are both among the group's highlights
    agreed   at least AGREED_SHARE of the experts read it in the same (non-mixed) direction
    leaning  anything else
    """
    per_expert = expert_directions(group)
    k = len(per_expert)
    counts = Counter(per_expert.values())
    directions = {m.direction or "unclear" for m in group}
    top, top_count = counts.most_common(1)[0]
    if k == 1:
        label: Label = "single"
    elif {"toward", "away"} <= directions:
        label = "split"
    elif top != "mixed" and top_count >= AGREED_SHARE * k:
        label = "agreed"
    else:
        label = "leaning"
    span = (min(m.span[0] for m in group), max(m.span[1] for m in group))
    return Agreement(span=span, k=k, n=max(n_answered, k), counts=dict(counts), label=label)


def agreement_groups(
    marks: Sequence[Mark], n_answered: int, threshold: float = IOU_THRESHOLD
) -> list[tuple[list[Mark], Agreement]]:
    """Every group of one vignette version with its summary, in text order. The marks are sorted
    first, so the same marks give the same groups whatever order they were read in."""
    ordered = sorted(marks, key=lambda m: (m.span, m.expert, m.id))
    groups = group_marks(ordered, threshold)
    return sorted(
        ((g, summarise(g, n_answered)) for g in groups), key=lambda x: (x[1].span, x[0][0].id)
    )


def render_agreement(a: Agreement) -> str:
    """The line a note carries. The numbers come from here, never from the model."""
    parts = [f"{a.counts[d]} {d}" for d in (*DIRECTIONS, "mixed") if a.counts.get(d)]
    who = "clinician" if a.n == 1 else "clinicians"
    return (
        f"Agreement: {a.k} of {a.n} {who} who answered this text cited it; "
        f"{', '.join(parts)} ({a.label})."
    )
