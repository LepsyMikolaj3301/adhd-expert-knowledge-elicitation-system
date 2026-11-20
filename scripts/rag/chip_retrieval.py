"""Retrieval over chip units, built on the B1 evaluation blocks (notes/new-chips-knowledge.md).

Reuses Searcher (dense + BM25, RRF), the metrics and the claim/label machinery of
expert_retrieval.py, so chips and B1 are scored on the same questions and the same claims:
  * ChipIndex      units + stored embeddings; Items for I1 / I3 / I1|I3; pack-time merge; the
                   down-weighting of near-duplicate case units; patient mode through the cue keys
  * cover_chip_claims   which units hold a reference claim (same answer, highlight overlaps the
                   claim's quote; otherwise the nearest unit of that answer by bge-m3)
  * b1_baseline    the regex pipeline (B1) on the same session, chips rendered as quotes
"""

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "elicitation"))
import chip_findings as cf  # noqa: E402
from build_chip_units import load_built  # noqa: E402
from chips_schema import ChipDocument, to_legacy  # noqa: E402
from elicitation_units import build_units  # noqa: E402
from expert_metrics import Item  # noqa: E402
from expert_retrieval import LEAN, Searcher, build_indexes, make_embed  # noqa: E402
from make_fixtures import fixture_dir  # noqa: E402
from make_unit_keys import role_for  # noqa: E402
from rag_common import RRF_K  # noqa: E402

from expert_knowledge_core.retrieval import (  # noqa: E402
    CONTEXT_BONUS,
    NEAR_DUPLICATE,
    PATIENT_TOP_CUES,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data/fixtures_chips"


# --- fixtures ----------------------------------------------------------------------------------


def load_chip_fixture(tier: str, fixtures: Path = FIXTURES):
    """(vignettes by id, claims by id, chip documents, legacy documents)."""
    vignettes, claims, docs, legacy = {}, {}, [], []
    folder = fixture_dir(tier, "synthetic", fixtures)
    for path in sorted((folder / "documents").glob("DOC-*.json")):
        doc = ChipDocument.model_validate_json(path.read_text())
        docs.append(doc)
        legacy.append(to_legacy(doc))
        vignettes |= {v.id: v for v in doc.vignettes}
        raw = []
        claims_path = folder / "claims" / f"{doc.session_id}.claims.json"
        if claims_path.exists():
            import json

            raw = json.loads(claims_path.read_text())
        claims |= {
            f"{doc.session_id}#{i}": {**c, "session_id": doc.session_id} for i, c in enumerate(raw)
        }
    return vignettes, claims, docs, legacy


def b1_baseline(tier: str, legacy_docs):
    """(B1 units, lean units, indexes A/B/B1/Bs, answers by (session, vignette, question))."""
    units, lean, answers = [], [], {}
    for d in legacy_docs:
        role = role_for(tier, d.session_id, d.expert_id)
        units += build_units(d, role)
        lean += build_units(d, role, **LEAN)
        for r in d.responses:
            answers |= {(d.session_id, r.vignette_id, q): a for q, a in r.answers.items()}
    return units, lean, build_indexes(units, lean, answers, {})


def primed_embed(embedder, primed: dict[str, np.ndarray]):
    """embed(texts): the stored embeddings first, the model only for texts not stored."""
    base = make_embed(embedder)

    def embed(texts: list[str]) -> np.ndarray:
        missing = [t for t in dict.fromkeys(texts) if t not in primed]
        if missing:
            primed.update(zip(missing, base(missing), strict=True))
        return np.stack([primed[t] for t in texts])

    return embed


# --- the chip index ----------------------------------------------------------------------------


def _overlap(a, b) -> bool:
    return a[0] < b[1] and b[0] < a[1]


class ChipIndex:
    def __init__(self, tier: str, tag: str, out: Path | None = None):
        kwargs = {"out": out} if out else {}
        self.built, arrays = load_built(tier, tag, **kwargs)
        self.tag = tag
        self.recs = {(r["session_id"], r["vignette_id"]): r for r in self.built["records"]}
        self.units = [u for r in self.built["records"] for u in r["units"]]
        self.unit = {u["id"]: u for u in self.units}
        self.rec_of = {u["id"]: self.recs[tuple(u["id"].split(":")[:2])] for u in self.units}
        self.vec1 = dict(zip(self.unit, arrays["i1"], strict=True))
        self.primed: dict[str, np.ndarray] = {}
        for name, texts in (
            ("i1", [u["i1"] for u in self.units]),
            ("i3", [u["i3"] for u in self.units]),
            ("i2", [k["text"] for k in self.built["cue_keys"]]),
        ):
            self.primed |= dict(zip(texts, arrays[name], strict=True))
        self.cue_of: dict[str, dict] = defaultdict(lambda: {"cue": None, "context": []})
        for uc in self.built["unit_cues"]:
            if uc["role"] == "cue":
                self.cue_of[uc["unit"]]["cue"] = uc["cue_key"]
            else:
                self.cue_of[uc["unit"]]["context"].append(uc["cue_key"])

    def block(self, uids: list[str]) -> str:
        return cf.pack_block(self.rec_of[uids[0]], uids)

    def items(self, name: str) -> list[Item]:
        """name: I1 | I3 | I1|I3 (searched through both texts, the best one counts)."""
        out = []
        for u in self.units:
            reps = {"I1": [u["i1"]], "I3": [u["i3"]], "I1|I3": [u["i1"], u["i3"]]}[name]
            out.append(Item([u["id"]], self.block([u["id"]]), reps))
        return out

    def merge(self, ranked: list[Item]) -> list[Item]:
        """Units of one session and vignette that share a sentence become one item (one block,
        each sentence once), placed where the first of them was ranked."""
        buckets: dict[tuple, list[tuple[int, str]]] = {}
        for pos, item in enumerate(ranked):
            uid = item.unit_ids[0]
            buckets.setdefault(tuple(uid.split(":")[:2]), []).append((pos, uid))
        merged = []
        for key, members in buckets.items():
            rec = self.recs[key]
            units_by_id = {u["id"]: u for u in rec["units"]}
            pos_of = dict((uid, pos) for pos, uid in members)
            for group in cf.merge_groups(units_by_id, [uid for _, uid in members]):
                first = min(pos_of[g] for g in group)
                reps = ranked[first].reps
                merged.append((first, Item(group, cf.pack_block(rec, group), reps)))
        return [item for _, item in sorted(merged, key=lambda x: x[0])]

    def downweight(self, ranked: list[Item]) -> list[Item]:
        """Case units that are near-duplicates of a better-ranked case unit go to the end."""
        kept, pushed, seen = [], [], []
        for item in ranked:
            u = self.unit[item.unit_ids[0]]
            if u["kind"] != "case":
                kept.append(item)
                continue
            v = self.vec1[u["id"]]
            if any(float(v @ w) >= NEAR_DUPLICATE for w in seen):
                pushed.append(item)
            else:
                seen.append(v)
                kept.append(item)
        return kept + pushed

    def patient_rank(self, cue_searcher: Searcher, query: dict) -> list[Item]:
        """Patient text -> units: every sentence searches the cue keys (dense + BM25, RRF); a unit
        scores its cue key's score plus a bonus for matching co-cited highlights."""
        keys = self.built["cue_keys"]
        allowed = np.array([k["vignette_id"] not in query["exclude"] for k in keys])
        score: dict[int, float] = defaultdict(float)
        for sentence in query["strings"]:
            for rank, i in enumerate(cue_searcher.rank([sentence], allowed)[:PATIENT_TOP_CUES], 1):
                score[i] += 1 / (RRF_K + rank)
        ranked = {}
        for uid, parts in self.cue_of.items():
            if parts["cue"] is None or not score.get(parts["cue"]):
                continue
            bonus = sum(score.get(c, 0.0) for c in parts["context"])
            ranked[uid] = score[parts["cue"]] + CONTEXT_BONUS * bonus
        by_id = {it.unit_ids[0]: it for it in self.items("I1")}
        return [by_id[u] for u in sorted(ranked, key=lambda u: -ranked[u])]

    def cue_items(self) -> list[Item]:
        return [
            Item([f"cue:{k['vignette_id']}:{k['id']}:0"], k["text"], [k["text"]])
            for k in self.built["cue_keys"]
        ]


def postprocess(ci: ChipIndex, ranked: list[Item], mods: set[str]) -> list[Item]:
    if "dw" in mods:
        ranked = ci.downweight(ranked)
    if "merge" in mods:
        ranked = ci.merge(ranked)
    return ranked


def cover_chip_claims(ci: ChipIndex, claims: dict, vignettes: dict, embed) -> dict[str, set[str]]:
    """Units that hold each claim: among the units with a sentence from the claim's answer, those
    whose highlight overlaps the claim's quote; if none, the one nearest to the claim text."""
    ids = list(claims)
    claim_vec = dict(zip(ids, embed([claims[c]["claim_text"] for c in ids]), strict=True))
    covers = {}
    for cid, c in claims.items():
        rec = ci.recs.get((c["session_id"], c["vignette_id"]))
        if rec is None:
            covers[cid] = set()
            continue
        in_answer = {s["id"] for s in rec["sentences"] if s["question_id"] == c["question_id"]}
        candidates = [u for u in rec["units"] if in_answer & set(u["sentences"])]
        span = c.get("quoted_span_text")
        start = vignettes[c["vignette_id"]].text.find(span) if span else -1
        spans = {h["id"]: h["span"] for h in rec["highlights"]}
        hit = {
            u["id"]
            for u in candidates
            if start >= 0
            and u["highlight"]
            and _overlap(spans[u["highlight"]], (start, start + len(span)))
        }
        if not hit and candidates:
            best = max(candidates, key=lambda u: float(ci.vec1[u["id"]] @ claim_vec[cid]))
            hit = {best["id"]}
        covers[cid] = hit
    return covers
