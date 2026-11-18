# ruff: noqa: E501  (long SQL strings)
"""A frozen copy of the silver chip units, for tests: freeze it once, seed a schema from it anywhere.

Usage: python scripts/db/chips_snapshot.py freeze [--tier silver] [--classifier qwen3.5:9b]
       python scripts/db/chips_snapshot.py check

`freeze` needs data/ (gitignored) and Ollama with bge-m3. It writes tests/fixtures/retrieval_silver/:
  tables.json    every row of the chips tables the retrievers read (sessions, units, cue keys, ...)
  vectors.npz    float16: the I1 / I3 vectors of the units, the cue key vectors, and the vectors of
                 every text the tests send as a query (so tests never need Ollama)
  queries.json   the questions and patient texts, their relevance labels (original and pooled), the
                 vignettes the labels come from (the "oracle" filter) and claim -> unit ids
  manifest.json  where it came from

`seed(conn, schema)` builds a schema from the snapshot with the DDL of chips_schema.sql and fits BM25;
it needs only psycopg, numpy and expert_knowledge_core, so the package tests can import it too.

One session per (document, vignette): a findings record covers one vignette (as an assignment does in
the app), whereas a chip document answers 14. Session `silver/DOC-SYN-0001.V001`, unit
`silver/DOC-SYN-0001.V001-V001-h1`, and the record's unit ids are the local `h1` / `case`.
"""

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from langchain_core.embeddings import Embeddings

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "tests" / "fixtures" / "retrieval_silver"
DDL = Path(__file__).with_name("chips_schema.sql")
INBOX = ROOT / "data" / "inbox" / "responses"
VECTOR_SIZE = 1024


def session_of(tier: str, session: str, vignette: str) -> str:
    return f"{tier}/{session}.{vignette}"


def local_id(unit: dict) -> str:
    return unit["highlight"] or "case"


def unit_of(sid: str, vignette: str, unit: dict) -> str:
    return f"{sid}-{vignette}-{local_id(unit)}"


# --- seeding ---------------------------------------------------------------------------------


def load_snapshot(snapshot: Path = SNAPSHOT) -> tuple[dict, dict[str, np.ndarray], dict]:
    tables = json.loads((snapshot / "tables.json").read_text())
    npz = np.load(snapshot / "vectors.npz")
    queries = json.loads((snapshot / "queries.json").read_text())
    return tables, {k: npz[k].astype(np.float32) for k in npz.files}, queries


def vector_text(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in vector) + "]"


def crowded(
    t: dict, vectors: dict[str, np.ndarray], copies: int, noise: float = 0.002, seed: int = 7
) -> tuple[dict, dict[str, np.ndarray]]:
    """The snapshot with `copies` more experts for every expert: each copy answers the same
    vignettes in the same words, with its vectors moved a little (`noise`, then normalised, so a copy
    stays a near-duplicate, cosine above 0.99). This is for testing how the retrievers behave when
    many experts answer one vignette alike; the snapshot itself has only two experts per vignette.
    Synthetic by construction: it says nothing about retrieval quality."""
    rng = np.random.default_rng(seed)

    def move(row: np.ndarray) -> np.ndarray:
        moved = row + rng.normal(0, noise, row.shape).astype(np.float32)
        return moved / np.linalg.norm(moved)

    new = {key: list(rows) if isinstance(rows, list) else rows for key, rows in t.items()}
    rows_i1, rows_i3 = list(vectors["i1"]), list(vectors["i3"])
    for n in range(1, copies + 1):
        suffix = f"~{n}"

        def rename(value: Any, prefixes: list[str], suffix: str = suffix) -> Any:
            if isinstance(value, str):
                for p in prefixes:
                    if value.startswith(p):
                        return p + suffix + value[len(p) :]
            return value

        sessions = [s["id"] for s in t["sessions"]]
        for e in t["experts"]:
            new["experts"].append({**e, "id": e["id"] + suffix})
        for s in t["sessions"]:
            document = {**s["document"], "session_id": s["id"] + suffix}
            document["expert_id"] = s["expert_id"] + suffix
            new["sessions"].append(
                {**s, "id": s["id"] + suffix, "expert_id": s["expert_id"] + suffix, "document": document}
            )  # fmt: skip
        for h in t["highlights"]:
            new["highlights"].append(
                {**h, "id": rename(h["id"], sessions), "session_id": h["session_id"] + suffix}
            )  # fmt: skip
        for s in t["sentences"]:
            targets = [x if x == "case" else rename(x, sessions) for x in s["targets"]]
            new["sentences"].append(
                {**s, "id": rename(s["id"], sessions), "session_id": s["session_id"] + suffix, "targets": targets}
            )  # fmt: skip
        for i, u in enumerate(t["units"]):
            new["units"].append(
                {**u, "id": rename(u["id"], sessions), "session_id": u["session_id"] + suffix,
                 "expert_id": u["expert_id"] + suffix,
                 "highlight_id": rename(u["highlight_id"], sessions)}  # fmt: skip
            )  # fmt: skip
            rows_i1.append(move(vectors["i1"][i]))
            rows_i3.append(move(vectors["i3"][i]))
        for unit, sentence, order in t["unit_sentences"]:
            new["unit_sentences"].append(
                [rename(unit, sessions), rename(sentence, sessions), order]
            )
        for unit, key, role in t["unit_cues"]:
            new["unit_cues"].append([rename(unit, sessions), key, role])
    return new, {**vectors, "i1": np.stack(rows_i1), "i3": np.stack(rows_i3)}


def seed(conn: Any, schema: str, snapshot: Path = SNAPSHOT, crowd: int = 0) -> dict[str, int]:
    """Create `schema` from chips_schema.sql, insert the snapshot and fit BM25 (psycopg connection).
    `crowd` adds that many synthetic copies of every expert (see `crowded`)."""
    from psycopg import sql

    from expert_knowledge_core import bm25
    from expert_knowledge_core.bm25 import Bm25Config

    t, vectors, _ = load_snapshot(snapshot)
    if crowd:
        t, vectors = crowded(t, vectors, crowd)
    conn.execute(DDL.read_text().format(schema=schema))
    conn.execute(sql.SQL("SET search_path = {}, public").format(sql.Identifier(schema)))
    for e in t["experts"]:
        conn.execute("INSERT INTO experts VALUES (%s, %s)", (e["id"], e["role"]))
    for v in t["vignettes"]:
        conn.execute(
            "INSERT INTO vignettes VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (v["id"], v["version"], v["tier"], v["text"], v["content_hash"], v["framing"], v["population"], v["track"]),
        )  # fmt: skip
    for s in t["sessions"]:
        conn.execute(
            "INSERT INTO elicitation_sessions VALUES (%s, %s, %s::jsonb, %s)",
            (s["id"], s["expert_id"], json.dumps(s["document"]), s["created_at"]),
        )  # fmt: skip
    cue_id: dict[int, int] = {}
    for key, k in enumerate(t["cue_keys"]):
        a, b = k["span"]
        row = conn.execute(
            "INSERT INTO cue_keys (vignette_id, vignette_version, span, text, embedding) "
            "VALUES (%s, %s, int4range(%s, %s), %s, CAST(%s AS vector)) RETURNING id",
            (k["vignette_id"], k["vignette_version"], a, b, k["text"], vector_text(vectors["cues"][key])),
        ).fetchone()  # fmt: skip
        assert row is not None
        cue_id[key] = row[0]
    for h in t["highlights"]:
        a, b = h["span"]
        conn.execute(
            "INSERT INTO highlights (id, session_id, vignette_id, vignette_version, chip, span, origin, direction, cue_key_id) "
            "VALUES (%s, %s, %s, %s, %s, int4range(%s, %s), %s, %s, %s)",
            (h["id"], h["session_id"], h["vignette_id"], h["vignette_version"], h["chip"], a, b, h["origin"], h["direction"], cue_id[h["cue_key"]]),
        )  # fmt: skip
    for s in t["sentences"]:
        a, b = s["span"]
        conn.execute(
            "INSERT INTO answer_sentences (id, session_id, vignette_id, vignette_version, question_id, idx, span, targets, assigned_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, int4range(%s, %s), %s, %s)",
            (s["id"], s["session_id"], s["vignette_id"], s["vignette_version"], s["question_id"], s["idx"], a, b, s["targets"], s["assigned_by"]),
        )  # fmt: skip
    for n, u in enumerate(t["units"]):
        conn.execute(
            "INSERT INTO finding_units (id, session_id, expert_id, vignette_id, vignette_version, kind, highlight_id, direction, "
            "population, track, framing, segmenter, embed_text, embedding, embed_text_combined, embedding_combined) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, CAST(%s AS vector), %s, CAST(%s AS vector))",
            (u["id"], u["session_id"], u["expert_id"], u["vignette_id"], u["vignette_version"], u["kind"], u["highlight_id"], u["direction"],
             u["population"], u["track"], u["framing"], json.dumps(t["segmenter"]), u["embed_text"],
             vector_text(vectors["i1"][n]), u["embed_text_combined"], vector_text(vectors["i3"][n])),
        )  # fmt: skip
    for unit, sentence, order in t["unit_sentences"]:
        conn.execute(
            "INSERT INTO finding_unit_sentences VALUES (%s, %s, %s)", (unit, sentence, order)
        )
    for unit, key, role in t["unit_cues"]:
        conn.execute(
            "INSERT INTO unit_cues VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (unit, cue_id[key], role),
        )
    refit_sparse(conn, Bm25Config(), bm25)
    return {
        name: len(t[name]) for name in ("sessions", "units", "cue_keys", "highlights", "sentences")
    }


def refit_sparse(conn: Any, cfg: Any, bm25: Any) -> None:
    """BM25 for the units (I1 and I3 each) and the cue keys, every one over its own corpus."""
    units = conn.execute(
        "SELECT id, embed_text, embed_text_combined FROM finding_units ORDER BY id"
    ).fetchall()
    keys = conn.execute("SELECT id, text FROM cue_keys ORDER BY id").fetchall()
    for (uid, _, _), a, b in zip(
        units,
        bm25.fit([u[1] for u in units], cfg),
        bm25.fit([u[2] for u in units], cfg),
        strict=True,
    ):
        conn.execute(
            "UPDATE finding_units SET sparse = CAST(%s AS sparsevec), sparse_combined = CAST(%s AS sparsevec) WHERE id = %s",
            (a.to_text(), b.to_text(), uid),
        )
    for (kid, _), v in zip(keys, bm25.fit([k[1] for k in keys], cfg), strict=True):
        conn.execute(
            "UPDATE cue_keys SET sparse = CAST(%s AS sparsevec) WHERE id = %s", (v.to_text(), kid)
        )


class FrozenEmbeddings(Embeddings):
    """The query embeddings of the snapshot; a text that was not frozen is an error, not a model call."""

    def __init__(self, queries: dict, vectors: dict[str, np.ndarray]) -> None:
        self.vectors = dict(zip(queries["embedded_texts"], vectors["queries"], strict=True))

    @classmethod
    def of(cls, texts: list[str], matrix: np.ndarray) -> "FrozenEmbeddings":
        return cls({"embedded_texts": texts}, {"queries": matrix})

    def _get(self, text: str) -> list[float]:
        if text not in self.vectors:
            raise KeyError(f"text was not frozen into the snapshot: {text!r}")
        return self.vectors[text].tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._get(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._get(t) for t in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return self._get(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


# --- freezing --------------------------------------------------------------------------------


def _half(array: np.ndarray) -> np.ndarray:
    return np.asarray(array, dtype=np.float16)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def snapshot_digest(snapshot: Path) -> str:
    """One digest of a snapshot's rows and vectors: what a frozen question set was built against."""
    digest = hashlib.sha256()
    for name in ("tables.json", "vectors.npz"):
        digest.update((snapshot / name).read_bytes())
    return digest.hexdigest()[:16]


def freeze(args: argparse.Namespace) -> int:
    for sub in ("elicitation", "rag"):
        sys.path.insert(0, str(ROOT / "scripts" / sub))
    from chip_retrieval import ChipIndex, cover_chip_claims, load_chip_fixture, primed_embed
    from classify_sentence_targets import UNITS, model_tag
    from expert_retrieval import patient_queries
    from make_unit_keys import role_for
    from rag_common import query_embedder

    from expert_knowledge_core.notes import split_sentences

    tier, tag = args.tier, model_tag(args.classifier)
    ci = ChipIndex(tier, tag, UNITS)
    vignettes, claims, docs, _ = load_chip_fixture(tier)
    built = ci.built
    arrays = {k: v for k, v in np.load(UNITS / tier / tag / "embeddings.npz").items()}
    by_doc = {d.session_id: d for d in docs}

    # --- rows -------------------------------------------------------------------------------
    experts, seen_experts = [], set()
    sessions, highlights, sentences, units, unit_sentences = [], [], [], [], []
    vec_i1, vec_i3 = [], []
    cue_key_of = {
        (k["vignette_id"], k["vignette_version"], tuple(k["span"])): n
        for n, k in enumerate(built["cue_keys"])
    }
    assert [k["id"] for k in built["cue_keys"]] == list(range(len(built["cue_keys"])))
    cues_of_unit: dict[str, list[tuple[int, str]]] = {}
    for uc in built["unit_cues"]:
        cues_of_unit.setdefault(uc["unit"], []).append((uc["cue_key"], uc["role"]))
    local_of: dict[str, str] = {}  # build unit id -> database unit id
    segmenter = {
        "findings_version": built["findings_version"],
        "classifier": built["classifier"],
        "prompt": built["prompt"],
    }
    row = 0
    for rec in built["records"]:
        doc, vid, ver = by_doc[rec["session_id"]], rec["vignette_id"], rec["vignette_version"]
        sid, expert = session_of(tier, rec["session_id"], vid), f"{tier}/{rec['expert_id']}"
        if expert not in seen_experts:
            seen_experts.add(expert)
            experts.append(
                {
                    "id": expert,
                    "role": role_for(tier, doc.session_id, doc.expert_id),
                }
            )
        document = deepcopy(rec)
        document["session_id"] = sid
        document["expert_id"] = expert
        for u in document["units"]:
            u["id"] = local_id(u)
        meta = rec["meta"]
        sessions.append(
            {
                "id": sid,
                "expert_id": expert,
                "created_at": doc.created_at.isoformat(),
                "document": document,
            }
        )
        for h in rec["highlights"]:
            highlights.append({
                "id": f"{sid}-{vid}-{h['id']}", "session_id": sid, "vignette_id": vid, "vignette_version": ver,
                "chip": h["chip"], "span": h["span"], "origin": h["origin"], "direction": h["direction"],
                "cue_key": cue_key_of[(vid, ver, tuple(h["span"]))],
            })  # fmt: skip
        for s in rec["sentences"]:
            sentences.append({
                "id": f"{sid}-{vid}-{s['id']}", "session_id": sid, "vignette_id": vid, "vignette_version": ver,
                "question_id": s["question_id"], "idx": s["idx"], "span": s["span"],
                "targets": [t if t == "case" else f"{sid}-{vid}-{t}" for t in s["targets"]], "assigned_by": s["assigned_by"],
            })  # fmt: skip
        for u in rec["units"]:
            uid = unit_of(sid, vid, u)
            local_of[u["id"]] = uid
            units.append({
                "id": uid, "session_id": sid, "expert_id": expert, "vignette_id": vid, "vignette_version": ver,
                "kind": u["kind"], "highlight_id": f"{sid}-{vid}-{u['highlight']}" if u["highlight"] else None,
                "direction": u["direction"], "population": meta["population"], "track": rec["track"],
                "framing": meta["framing"], "embed_text": u["i1"], "embed_text_combined": u["i3"],
            })  # fmt: skip
            unit_sentences += [[uid, f"{sid}-{vid}-{s}", n] for n, s in enumerate(u["sentences"])]
            vec_i1.append(arrays["i1"][row])
            vec_i3.append(arrays["i3"][row])
            row += 1
    unit_cues = [
        [local_of[u], k, role]
        for u, parts in cues_of_unit.items()
        for k, role in sorted(set(parts))
    ]
    vignette_rows = [
        {"id": v.id, "version": v.version, "tier": tier, "text": v.text, "content_hash": v.content_hash, "framing": v.framing,
         "population": v.design.population, "track": v.design.track}
        for v in vignettes.values()
    ]  # fmt: skip

    # --- queries and labels ------------------------------------------------------------------
    raw = json.loads((INBOX / f"queries.{tier}.json").read_text())["queries"]
    marks: dict[int, set[str]] = {}
    for part in sorted(INBOX.glob(f"pool.{tier}.*.json")):
        for key, ids in json.loads(part.read_text())["labels"].items():
            marks[int(key.lstrip("Q")) - 1] = set(ids)
    questions = []
    for n, q in enumerate(raw):
        pooled = sorted(set(q["claim_ids"]) | marks.get(n, set()))
        questions.append({
            "question": q["question"], "claim_ids": q["claim_ids"], "pooled_ids": pooled,
            "vignettes": sorted({claims[c]["vignette_id"] for c in pooled}),
        })  # fmt: skip
    patients = [
        {"id": p["id"], "text": vignettes[p["id"]].text, "claim_ids": p["claim_ids"], "exclude": sorted(p["exclude"])}
        for p in patient_queries(vignettes, claims)
    ]  # fmt: skip

    embed_texts = [q["question"] for q in questions]  # embed_query
    for p in patients:  # embed_documents of the sentences PatientTextRetriever cuts
        text = p["text"]
        embed_texts += [text[a:b].strip() for a, b in split_sentences(text) if text[a:b].strip()]
    embed_texts = list(dict.fromkeys(embed_texts))
    embedder = query_embedder()  # bge-m3 through Ollama, as the backend embeds a question
    query_vectors = np.array(embedder.embed(embed_texts), dtype=np.float32)

    embed = primed_embed(query_embedder(), dict(ci.primed))
    covers = cover_chip_claims(ci, claims, vignettes, embed)
    all_claims = {c for q in questions for c in q["pooled_ids"]} | {
        c for p in patients for c in p["claim_ids"]
    }
    queries = {
        "embedded_texts": embed_texts,
        "questions": questions,
        "patients": patients,
        "covers": {c: sorted(local_of[u] for u in covers[c]) for c in sorted(all_claims)},
    }

    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    tables = {
        "tier": tier, "segmenter": segmenter, "experts": experts, "vignettes": vignette_rows, "sessions": sessions,
        "cue_keys": [{k: c[k] for k in ("vignette_id", "vignette_version", "span", "text")} for c in built["cue_keys"]],
        "highlights": highlights, "sentences": sentences, "units": units,
        "unit_sentences": unit_sentences, "unit_cues": unit_cues,
    }  # fmt: skip

    def dump(name: str, data: Any) -> None:
        text = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1)
        (SNAPSHOT / name).write_text(text + "\n")

    dump("tables.json", tables)
    dump("queries.json", queries)
    np.savez_compressed(
        SNAPSHOT / "vectors.npz",
        i1=_half(np.stack(vec_i1)), i3=_half(np.stack(vec_i3)), cues=_half(arrays["i2"]), queries=_half(query_vectors),
    )  # fmt: skip
    dump("manifest.json", {
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"), "tier": tier, "classifier": args.classifier,
        "sources": {"units.json": sha(UNITS / tier / tag / "units.json"), "embeddings.npz": sha(UNITS / tier / tag / "embeddings.npz")},
        "counts": {"sessions": len(sessions), "units": len(units), "cue_keys": len(tables["cue_keys"]), "questions": len(questions),
                   "patients": len(patients), "embedded_texts": len(embed_texts)},
    })  # fmt: skip
    print(f"froze {len(units)} units, {len(tables['cue_keys'])} cue keys, {len(questions)} questions, "
          f"{len(patients)} patient texts, {len(embed_texts)} query vectors into {SNAPSHOT}")  # fmt: skip
    return 0


def check(_: argparse.Namespace) -> int:
    t, vectors, q = load_snapshot()
    ids = {u["id"] for u in t["units"]}
    problems = []
    if len(t["units"]) != len(vectors["i1"]) or len(t["units"]) != len(vectors["i3"]):
        problems.append("unit vectors do not match the units")
    if len(t["cue_keys"]) != len(vectors["cues"]):
        problems.append("cue vectors do not match the cue keys")
    if len(q["embedded_texts"]) != len(vectors["queries"]):
        problems.append("query vectors do not match the texts")
    problems += [
        f"claim {c} is held by unknown unit {u}"
        for c, us in q["covers"].items()
        for u in us
        if u not in ids
    ]
    print("\n".join(problems) or "snapshot is consistent")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    fr = sub.add_parser("freeze")
    fr.add_argument("--tier", default="silver", choices=["bronze", "silver"])
    fr.add_argument("--classifier", default="qwen3.5:9b")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    return freeze(args) if args.command == "freeze" else check(args)


if __name__ == "__main__":
    sys.exit(main())
