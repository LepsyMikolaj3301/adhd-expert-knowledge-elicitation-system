"""From rows to a ranked list of units: the rules that are not SQL.

Ported from scripts/rag/chip_retrieval.py (`ChipIndex.downweight`, `ChipIndex.patient_rank`).
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from expert_knowledge_core.agreement import DIRECTIONS, Agreement
from expert_knowledge_core.retrieval import CONTEXT_BONUS, NEAR_DUPLICATE


@dataclass(frozen=True)
class UnitHit:
    id: str
    session_id: str
    expert_id: str
    vignette_id: str
    vignette_version: int
    kind: str  # fragment | case
    highlight_id: str | None
    direction: str | None
    embed_text: str  # I1
    score: float
    vector: np.ndarray | None = None  # I1 embedding of case units only

    @classmethod
    def from_row(cls, row: Mapping[str, Any], score: float | None = None) -> "UnitHit":
        text = row.get("vector")
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            expert_id=row["expert_id"],
            vignette_id=row["vignette_id"],
            vignette_version=row["vignette_version"],
            kind=row["kind"],
            highlight_id=row["highlight_id"],
            direction=row["direction"],
            embed_text=row["embed_text"],
            score=float(row["score"] if score is None else score),
            vector=np.asarray(text.strip("[]").split(","), dtype=np.float32) if text else None,
        )


@dataclass(frozen=True)
class Grouping:
    """Which units are one passage read by several clinicians: from `fragment_groups`.

    `of_highlight` maps a stored highlight id to its group, `agreements` holds each group's counts
    (over every clinician, however many are retrieved), `members` its units (all of them, hits
    first is the caller's business).
    """

    of_highlight: Mapping[str, int]
    agreements: Mapping[int, Agreement]
    members: Mapping[int, Sequence[UnitHit]]


def make_grouping(
    group_rows: Sequence[Mapping[str, Any]], unit_rows: Sequence[Mapping[str, Any]]
) -> Grouping:
    of_highlight: dict[str, int] = {}
    agreements: dict[int, Agreement] = {}
    for r in group_rows:
        of_highlight[r["highlight_id"]] = r["group_id"]
        counts = {
            d: r[f"n_{d}"] for d in (*DIRECTIONS, "mixed") if r[f"n_{d}"]
        }  # only the directions someone read it in
        agreements[r["group_id"]] = Agreement(
            span=(r["span_start"], r["span_end"]),
            k=r["n_attending"],
            n=r["n_answered"],
            counts=counts,
            label=r["label"],
        )
    members: dict[int, list[UnitHit]] = {}
    for r in unit_rows:
        members.setdefault(r["group_id"], []).append(UnitHit.from_row(r, score=0.0))
    return Grouping(of_highlight, agreements, members)


def downweight_duplicate_cases(hits: Sequence[UnitHit]) -> list[UnitHit]:
    """Case units that are near-duplicates (cosine >= NEAR_DUPLICATE) of a better-ranked case unit
    go to the end: the generic "longitudinal history, childhood onset" answers repeat across
    sessions and would flood a general question."""
    kept: list[UnitHit] = []
    pushed: list[UnitHit] = []
    seen: list[np.ndarray] = []
    for hit in hits:
        if hit.kind != "case" or hit.vector is None:
            kept.append(hit)
            continue
        v = hit.vector / max(float(np.linalg.norm(hit.vector)), 1e-12)
        if any(float(v @ w) >= NEAR_DUPLICATE for w in seen):
            pushed.append(hit)
        else:
            seen.append(v)
            kept.append(hit)
    return kept + pushed


def cue_scores(rankings: Sequence[Sequence[int]], rrf_k: int) -> dict[int, float]:
    """Each sentence's ranked cue ids -> one score per cue: the sum of 1 / (rrf_k + rank)."""
    score: dict[int, float] = defaultdict(float)
    for ranked in rankings:
        for rank, cue_id in enumerate(ranked, 1):
            score[cue_id] += 1 / (rrf_k + rank)
    return dict(score)


def rank_by_cues(rows: Sequence[Mapping[str, Any]], score: Mapping[int, float]) -> list[UnitHit]:
    """Units whose own cue matched, best first: the cue's score plus CONTEXT_BONUS times the
    scores of the cues cited together with it, so a combination of patient words outranks one."""
    scored = []
    for row in rows:
        own = score.get(row["cue_id"], 0.0)
        if not own:
            continue
        bonus = sum(score.get(c, 0.0) for c in row["context_ids"] or [])
        scored.append(UnitHit.from_row(row, own + CONTEXT_BONUS * bonus))
    return sorted(scored, key=lambda h: (-h.score, h.id))
