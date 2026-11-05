"""Building blocks shared by eval_expert_units.py and eval_expert_generation.py.

Fixture loading, the clinician questions (written by a Claude agent through the inbox), which units
hold which reference claim, the candidate representations of the expert answers, and a hybrid
searcher over them (docs/expert-knowledge.md).
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "elicitation"))
from chips_schema import load_document  # noqa: E402
from expert_metrics import Item  # noqa: E402
from llm_clients import AwaitingResponse, GenRequest, InboxGenerator  # noqa: E402
from make_fixtures import fixture_dir  # noqa: E402
from make_unit_keys import ROOT  # noqa: E402
from prompt_loader import load_prompt  # noqa: E402
from rag_common import FUSION_DEPTH, RRF_K  # noqa: E402

from app.elicitation.units import ExpertUnit, render_unit, sentences  # noqa: E402
from app.indexing import bm25  # noqa: E402

N_QUERIES = 40
LEAN = {"context_words": 30, "max_context": 1}  # B1: one short vignette sentence per unit
MMR_POOL, MMR_LAMBDA = 30, 0.7
POOL_DEPTH, POOL_PART = 8, 10  # claims pooled per system and question; questions per agent request


# --- fixtures ----------------------------------------------------------------------------------


def load_fixture(tier: str, source: str = "synthetic"):
    """(vignettes by id, claims by id, answers by (session, vignette, question))."""
    vignettes, claims, answers = {}, {}, {}
    for path in sorted((fixture_dir(tier, source) / "documents").glob("DOC-*.json")):
        doc = load_document(path)
        vignettes |= {v.id: v for v in doc.vignettes}
        for r in doc.responses:
            answers |= {(doc.session_id, r.vignette_id, q): a for q, a in r.answers.items()}
        claims_path = path.parent.parent / "claims" / f"{doc.session_id}.claims.json"
        raw = json.loads(claims_path.read_text()) if claims_path.exists() else []  # gold: pending
        claims |= {
            f"{doc.session_id}#{i}": {**c, "session_id": doc.session_id} for i, c in enumerate(raw)
        }
    return vignettes, claims, answers


def load_keys(tier: str, source: str = "synthetic") -> dict[str, dict]:
    keys: dict[str, dict] = {}
    for path in sorted((ROOT / "data/expert_units" / source / tier).glob("DOC-*.json")):
        keys |= {k: v["keys"] for k, v in json.loads(path.read_text())["keys"].items() if v["keys"]}
    return keys


def make_embed(embedder):
    """embed(texts) with a cache, so the same text is never sent twice."""
    cache: dict[str, np.ndarray] = {}

    def embed(texts: list[str]) -> np.ndarray:
        todo = [t for t in dict.fromkeys(texts) if t not in cache]
        if todo:
            cache.update(zip(todo, embedder.embed(todo), strict=True))
        return np.stack([cache[t] for t in texts])

    return embed


# --- queries -----------------------------------------------------------------------------------


def claim_line(cid: str, c: dict) -> str:
    note = ", ".join(x for x in (c.get("trait"), c.get("direction"), c.get("condition")) if x)
    return f"- {cid}: {c['claim_text']} ({note})"


def vignette_block(vignettes, claims) -> str:
    out = []
    for v in vignettes.values():
        d = v.design
        lines = [f"### {v.id}: {d.knowledge_target or d.purpose}", f'Text: "{v.text}"']
        lines += [claim_line(cid, c) for cid, c in claims.items() if c["vignette_id"] == v.id]
        out.append("\n".join(lines))
    return "\n\n".join(out)


def question_request(tier: str, vignettes, claims) -> GenRequest:
    p = load_prompt("Expert_unit_queries.v1").fill(
        VIGNETTES=vignette_block(vignettes, claims), N=N_QUERIES
    )
    return GenRequest(key=f"queries:{tier}", system=p.system, user=p.user, json_mode=True)


def load_questions(tier: str, vignettes, claims, inbox: Path) -> list[dict]:
    raw = InboxGenerator(inbox).generate(question_request(tier, vignettes, claims))
    queries = json.loads(raw)["queries"]
    for q in queries:
        unknown = [c for c in q["claim_ids"] if c not in claims]
        if unknown:
            raise SystemExit(f"query {q['question']!r}: unknown claim ids {unknown}")
    return [{"strings": [q["question"]], "pooled_ids": q["claim_ids"], **q} for q in queries]


def patient_queries(vignettes, claims) -> list[dict]:
    out = []
    for v in vignettes.values():
        traits = {c.trait for c in v.design.planted_cues}
        siblings = {
            w.id
            for w in vignettes.values()
            if w.id == v.id or (v.variant and w.variant and w.variant.pair_id == v.variant.pair_id)
        }
        relevant = [
            cid
            for cid, c in claims.items()
            if c.get("trait") in traits and c["vignette_id"] not in siblings
        ]
        if relevant:
            out.append(
                {
                    "id": v.id,
                    "strings": sentences(v.text),
                    "claim_ids": relevant,
                    "pooled_ids": relevant,
                    "exclude": siblings,
                }
            )
    return out


# --- pooled relevance labels (fixes labels that one agent left incomplete) ----------------------


def pool_requests(tier: str, questions: list[dict], pooled: list[list[str]], claims) -> list:
    """Requests asking an agent which pooled claims help answer each question, 10 per request."""
    reqs = []
    for part, start in enumerate(range(0, len(questions), POOL_PART), 1):
        blocks = []
        for n in range(start, min(start + POOL_PART, len(questions))):
            ids = sorted(pooled[n], key=lambda c: hashlib.md5(c.encode()).hexdigest())
            lines = [claim_line(c, claims[c]) for c in ids]
            blocks.append(f"Q{n + 1}: {questions[n]['question']}\n" + "\n".join(lines))
        p = load_prompt("Expert_unit_pooling.v1").fill(BLOCK="\n\n".join(blocks))
        reqs.append(
            GenRequest(key=f"pool:{tier}:{part}", system=p.system, user=p.user, json_mode=True)
        )
    return reqs


def load_pool(requests: list, inbox: Path) -> dict[int, set[str]]:
    """{question index: claim ids the agent marked relevant}; raises AwaitingResponse if missing."""
    inbox_gen, labels, missing = InboxGenerator(inbox), {}, []
    for req in requests:
        try:
            part = json.loads(inbox_gen.generate(req))["labels"]
        except AwaitingResponse as e:
            missing.append(str(e))
            continue
        labels |= {int(k.lstrip("Q")) - 1: set(v) for k, v in part.items()}
    if missing:
        raise AwaitingResponse("; ".join(missing))
    return labels


# --- coverage: which units hold a claim --------------------------------------------------------


def cover_claims(units: list[ExpertUnit], claims, vignettes, embed) -> dict[str, set[str]]:
    by_answer: dict[tuple, list[ExpertUnit]] = {}
    for u in units:
        by_answer.setdefault((u.session_id, u.vignette_id, u.question_id), []).append(u)
    ids = list(claims)
    claim_vec = dict(zip(ids, embed([claims[c]["claim_text"] for c in ids]), strict=True))
    unit_vec = dict(
        zip((u.unit_id for u in units), embed([u.text_expanded for u in units]), strict=True)
    )
    covers: dict[str, set[str]] = {}
    for cid, c in claims.items():
        same = by_answer.get((c["session_id"], c["vignette_id"], c["question_id"]), [])
        span = c.get("quoted_span_text")
        start = vignettes[c["vignette_id"]].text.find(span) if span else -1
        hit = {
            u.unit_id
            for u in same
            if start >= 0 and any(a < start + len(span) and start < b for a, b in u.quote_spans)
        }
        if not hit and same:
            best = max(same, key=lambda u: float(unit_vec[u.unit_id] @ claim_vec[cid]))
            hit = {best.unit_id}
        covers[cid] = hit
    return covers


# --- representations ---------------------------------------------------------------------------


def build_indexes(units, lean_units, answers, keys) -> dict[str, list[Item]]:
    """Name -> items. A answers; B units; B1 lean units; Bs searched lean but shown in full;
    C the LLM rule alone; D / D1 = B / B1 searched also through the rule and questions."""

    def rendered(us: list[ExpertUnit]) -> dict[str, str]:
        by_id = {u.unit_id: u for u in us}
        return {u.unit_id: render_unit(u, by_id) for u in us}

    full, lean = rendered(units), rendered(lean_units)
    grouped: dict[tuple, list[ExpertUnit]] = {}
    for u in units:
        grouped.setdefault((u.session_id, u.vignette_id, u.question_id), []).append(u)
    index = {
        "A": [Item([u.unit_id for u in us], answers[k], [answers[k]]) for k, us in grouped.items()],
        "B": [Item([u.unit_id], full[u.unit_id], [full[u.unit_id]]) for u in units],
        "B1": [Item([u.unit_id], lean[u.unit_id], [lean[u.unit_id]]) for u in units],
        "Bs": [Item([u.unit_id], full[u.unit_id], [lean[u.unit_id]]) for u in units],
    }
    keyed = [u for u in units if u.unit_id in keys]
    if not keyed:
        return index

    def key_texts(u: ExpertUnit) -> list[str]:
        return [keys[u.unit_id]["reading_rule"], *keys[u.unit_id]["questions"]]

    index["C"] = [
        Item([u.unit_id], keys[u.unit_id]["reading_rule"], [keys[u.unit_id]["reading_rule"]])
        for u in keyed
    ]
    index["D"] = [
        Item([u.unit_id], full[u.unit_id], [full[u.unit_id], *key_texts(u)]) for u in keyed
    ]
    index["D1"] = [
        Item([u.unit_id], lean[u.unit_id], [lean[u.unit_id], *key_texts(u)]) for u in keyed
    ]
    return index


# --- search ------------------------------------------------------------------------------------


class Searcher:
    """Search over an index: dense + BM25 per query string, max over an item's representations."""

    def __init__(self, items: list[Item], embed, cfg):
        self.items, self.embed, self.cfg = items, embed, cfg
        texts = [r for it in items for r in it.reps]
        self.owner = np.array([i for i, it in enumerate(items) for _ in it.reps])
        self.first_rep = np.array([int(np.argmax(self.owner == i)) for i in range(len(items))])
        self.dense = embed(texts)
        self.sparse = [
            dict(zip(v.indices(), v.values(), strict=True)) for v in bm25.fit(texts, cfg)
        ]

    def _per_item(self, rep_scores: np.ndarray) -> np.ndarray:
        best = np.full(len(self.items), -np.inf)
        np.maximum.at(best, self.owner, rep_scores)
        return best

    def _scores(self, strings: list[str]) -> tuple[np.ndarray, np.ndarray]:
        dense = self._per_item((self.dense @ self.embed(strings).T).max(axis=1))
        sparse = np.zeros(len(self.sparse))
        for s in strings:
            q = bm25.query_vector(s, self.cfg)
            if q is not None:
                qv = dict(zip(q.indices(), q.values(), strict=True))
                sparse = np.maximum(
                    sparse, [sum(w * d.get(t, 0.0) for t, w in qv.items()) for d in self.sparse]
                )
        return dense, self._per_item(sparse)

    def rank(
        self, strings: list[str], allowed: np.ndarray, mode: str = "hybrid", diversity: str = "none"
    ) -> list[int]:
        """Item indices, best first. mode: dense | bm25 | hybrid (RRF). diversity: none | cap
        (one item per vignette and question first) | mmr (maximal marginal relevance)."""
        dense, sparse = self._scores(strings)
        fused: dict[int, float] = {}
        if mode == "dense":
            fused = {int(i): float(dense[i]) for i in np.flatnonzero(allowed)}
        elif mode == "bm25":
            fused = {int(i): float(sparse[i]) for i in np.flatnonzero(allowed) if sparse[i] > 0}
        else:
            for scores, positive_only in ((dense, False), (sparse, True)):
                order = [
                    i
                    for i in np.argsort(-scores)
                    if allowed[i] and (scores[i] > 0 or not positive_only)
                ]
                for rank, i in enumerate(order[:FUSION_DEPTH], 1):
                    fused[int(i)] = fused.get(int(i), 0.0) + 1 / (RRF_K + rank)
        ranked = sorted(fused, key=lambda i: -fused[i])
        if diversity == "cap":
            return self._cap(ranked)
        if diversity == "mmr":
            return self._mmr(ranked, fused)
        return ranked

    def _cap(self, ranked: list[int]) -> list[int]:
        seen: set[tuple[str, str]] = set()
        first, rest = [], []
        for i in ranked:
            _, vignette, question, _ = self.items[i].unit_ids[0].split(":")
            (rest if (vignette, question) in seen else first).append(i)
            seen.add((vignette, question))
        return first + rest

    def _mmr(self, ranked: list[int], fused: dict[int, float]) -> list[int]:
        pool, tail = ranked[:MMR_POOL], ranked[MMR_POOL:]
        if not pool:
            return ranked
        top = max(fused[i] for i in pool) or 1.0
        vec = {i: self.dense[self.first_rep[i]] for i in pool}
        chosen: list[int] = []
        while pool:
            best = max(
                pool,
                key=lambda i: (
                    MMR_LAMBDA * fused[i] / top
                    - (1 - MMR_LAMBDA) * max((float(vec[i] @ vec[j]) for j in chosen), default=0.0)
                ),
            )
            chosen.append(best)
            pool.remove(best)
        return chosen + tail
