"""Perplexity-based chunk metrics from MoC (arXiv 2503.09600): Boundary Clarity, Chunk Stickiness.

With q a chunk and d an earlier chunk used as context:
  Boundary Clarity  BC = ppl(q|d) / ppl(q) for adjacent chunks. Near 1: q does not depend on d,
                    so the boundary is clean (higher is better); small: q leans on d (blurred).
  Chunk Stickiness  graph over a document's chunks with edge weight (ppl(q) - ppl(q|d)) / ppl(q),
                    keep edges above K, then CS = structural entropy of the node degrees,
                    -sum(h_i / 2m * log2(h_i / 2m)). Lower is better (chunks are more independent).
"""

import hashlib
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from chunk_common import CHUNKS_DIR

LM_NAME = "Qwen/Qwen2.5-0.5B"


class LMScorer:
    """Mean token NLL of a text q, optionally conditioned on a preceding text d (cached)."""

    def __init__(
        self, name: str = LM_NAME, cache_path: Path = CHUNKS_DIR / ".cache" / "ppl.sqlite"
    ):
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.name = name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForCausalLM.from_pretrained(name, dtype=dtype).to(self.device).eval()
        self.start = self.tok.eos_token_id  # base LMs have no BOS; <|endoftext|> opens the text
        self.sep = self.tok("\n\n", add_special_tokens=False)["input_ids"]
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS nll (key TEXT PRIMARY KEY, val REAL)")

    def _key(self, d: str, q: str) -> str:
        return hashlib.sha1(f"{self.name}\0{d}\0{q}".encode()).hexdigest()

    def nll(self, items: list[tuple[str, str]], batch_size: int = 8) -> list[float]:
        """NLL (nats/token) of q given d for each (d, q); d == "" means no context."""
        keys = [self._key(d, q) for d, q in items]
        unique = dict(zip(keys, items, strict=True))
        have: dict[str, float] = {}
        wanted = list(unique)
        for i in range(0, len(wanted), 500):
            part = wanted[i : i + 500]
            rows = self.db.execute(
                f"SELECT key, val FROM nll WHERE key IN ({','.join('?' * len(part))})", part
            )
            have.update(dict(rows))
        missing = [k for k in unique if k not in have]
        if missing:
            print(
                f"  scoring {len(missing)} texts with {self.name} on {self.device}", file=sys.stderr
            )
        seqs = {}
        for k in missing:
            d, q = unique[k]
            q_ids = self.tok(q, add_special_tokens=False)["input_ids"]
            prefix = [self.start]
            if d:
                prefix += self.tok(d, add_special_tokens=False)["input_ids"][-512:] + self.sep
            seqs[k] = (prefix + q_ids, len(prefix))
        missing.sort(key=lambda k: len(seqs[k][0]))
        with torch.inference_mode():
            for i in range(0, len(missing), batch_size):
                batch = missing[i : i + batch_size]
                width = max(len(seqs[k][0]) for k in batch)
                ids = torch.full((len(batch), width), self.start)
                mask = torch.zeros((len(batch), width), dtype=torch.long)
                for b, k in enumerate(batch):
                    ids[b, : len(seqs[k][0])] = torch.tensor(seqs[k][0])
                    mask[b, : len(seqs[k][0])] = 1
                hidden = self.model.base_model(
                    input_ids=ids.to(self.device), attention_mask=mask.to(self.device)
                ).last_hidden_state
                for b, k in enumerate(batch):
                    token_ids, q_start = seqs[k]
                    # position t predicts token t+1, so q's tokens are predicted from q_start-1 on
                    logits = self.model.get_output_embeddings()(
                        hidden[b, q_start - 1 : len(token_ids) - 1]
                    )
                    logp = torch.log_softmax(logits.float(), dim=-1)
                    target = torch.tensor(token_ids[q_start:], device=self.device)
                    val = -logp.gather(1, target[:, None]).mean().item()
                    have[k] = val
                    self.db.execute("INSERT OR REPLACE INTO nll VALUES (?, ?)", (k, val))
                self.db.commit()
                if (i // batch_size) % 25 == 0:
                    print(
                        f"  scored {min(i + batch_size, len(missing))}/{len(missing)}",
                        file=sys.stderr,
                    )
        return [have[k] for k in keys]


def moc_metrics(children: list[dict], scorer: LMScorer, window: int, k: float) -> list[dict]:
    """Per-document Boundary Clarity values and Chunk Stickiness graph statistics.

    Stickiness edges connect chunk i to each later chunk j within `window` chunks (0 = all
    pairs); the edge weight uses q = chunk j conditioned on d = chunk i."""
    by_doc = defaultdict(list)
    for c in children:
        by_doc[c["doc"]].append(c)
    out = []
    for doc, chunks in by_doc.items():
        n = len(chunks)
        texts = [c["text"] for c in chunks]
        single = scorer.nll([("", t) for t in texts])
        pairs = [
            (i, j)
            for i in range(n)
            for j in range(i + 1, n if window <= 0 else min(n, i + window + 1))
        ]
        cond = scorer.nll([(texts[i], texts[j]) for i, j in pairs])
        degree = np.zeros(n)
        bc, edges = [], 0
        for (i, j), c_nll in zip(pairs, cond, strict=True):
            ratio = math.exp(c_nll - single[j])  # ppl(q|d) / ppl(q)
            if j == i + 1 and chunks[i]["parent_id"] == chunks[j]["parent_id"]:
                bc.append(ratio)
            if 1 - ratio > k:  # edge weight (ppl(q) - ppl(q|d)) / ppl(q)
                degree[i] += 1
                degree[j] += 1
                edges += 1
        p = degree[degree > 0] / (2 * edges) if edges else np.array([])
        cs = float(-(p * np.log2(p)).sum()) if edges else float("nan")
        out.append(
            {
                "doc": doc,
                "source": chunks[0]["source"],
                "bc": bc,
                "cs": cs,
                "cs_norm": cs / math.log2(n) if edges and n > 1 else float("nan"),
                "edges": edges,
                "nodes": n,
            }
        )
    return out
