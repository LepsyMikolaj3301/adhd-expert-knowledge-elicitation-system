# ruff: noqa: E501  (long SQL strings)
"""The filled vignettes of tests/fixtures/scale_answers, ingested into a throwaway schema.

Usage: python scripts/db/chips_fixture.py export [--fixtures DIR] [--labels DIR] [--out DIR]
       python scripts/db/chips_fixture.py check
       python scripts/db/chips_fixture.py seed --schema chips_scale [--experts SYN-001 SYN-002]

The fixture holds the answers as they are before ingestion, and nothing derived from them:
  documents/   the 32 chip documents (vignettes, answers, highlights) after proofreading
  labels/      the classifier's links for the sentences without a chip (they are made at proofread,
               before the review, so they are part of the answer that gets approved)
  claims/      the claims each answer makes (relevance labels refer to them: DOC-SYN-0001#12)
  experts.json the role line of every session (it goes into the unit text, so into the vectors)
  questions.json  40 questions with original and pooled claim labels (claims of SYN-001, SYN-002)

Everything else is made at test time, the way the application does it:
  `build`   the units (app.knowledge.findings via chip_findings), cue keys, unit cues
  `ingest`  + bge-m3 vectors (config/indexing.yaml, the embedder of the application), the table rows,
            which units hold each labelled claim (`covers`), the patient-text queries
  `seed`    a schema from chips_schema.sql with those rows, BM25 fitted, agreement groups
So a test needs Postgres with pgvector and Ollama with bge-m3; the vectors are never stored.
"""

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
from langchain_core.embeddings import Embeddings

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("elicitation",):
    if str(ROOT / "scripts" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts" / _sub))

FIXTURE = ROOT / "tests" / "fixtures" / "scale_answers"
DDL = Path(__file__).with_name("chips_schema.sql")
CONFIG = ROOT / "config" / "indexing.yaml"
TIER = "silver"  # namespace of the session and unit ids (silver/DOC-SYN-0001.V001-V001-h1)
SILVER_EXPERTS = ("SYN-001", "SYN-002")  # whose claims label the 40 questions


def session_of(tier: str, session: str, vignette: str) -> str:
    return f"{tier}/{session}.{vignette}"


def local_id(unit: dict) -> str:
    return unit["highlight"] or "case"


def unit_of(sid: str, vignette: str, unit: dict) -> str:
    return f"{sid}-{vignette}-{local_id(unit)}"


def vector_text(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in vector) + "]"


def digest(fixture: Path = FIXTURE) -> str:
    """One digest of every file of the fixture: what a baseline was measured on."""
    h = hashlib.sha256()
    for path in sorted(p for p in fixture.rglob("*") if p.is_file()):
        h.update(str(path.relative_to(fixture)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


# --- the answers -----------------------------------------------------------------------------


@dataclass
class Answers:
    """The fixture, optionally only some experts' documents (and their claims)."""

    docs: list[Any]  # ChipDocument
    vignettes: dict[str, Any]  # id -> Vignette (from the documents)
    claims: dict[str, dict]  # DOC-SYN-0001#12 -> claim (+ session_id)
    labels: dict[str, dict]  # session id -> vignette id -> classifier labels
    roles: dict[str, str | None]  # session id -> role line
    questions: list[dict]  # question, claim_ids, pooled_ids
    manifest: dict = field(default_factory=dict)

    @property
    def experts(self) -> list[str]:
        return [d.expert_id for d in self.docs]


def load(fixture: Path = FIXTURE, experts: list[str] | tuple[str, ...] | None = None) -> Answers:
    from chips_schema import ChipDocument

    docs = [
        ChipDocument.model_validate_json(p.read_text())
        for p in sorted((fixture / "documents").glob("DOC-*.json"))
    ]
    if experts is not None:
        docs = [d for d in docs if d.expert_id in set(experts)]
    sessions = {d.session_id for d in docs}
    vignettes = {v.id: v for d in docs for v in d.vignettes}
    claims = {}
    for sid in sorted(sessions):
        path = fixture / "claims" / f"{sid}.claims.json"
        raw = json.loads(path.read_text()) if path.exists() else []
        claims |= {f"{sid}#{i}": {**c, "session_id": sid} for i, c in enumerate(raw)}
    labels = {
        sid: json.loads((fixture / "labels" / f"{sid}.json").read_text())["responses"]
        for sid in sorted(sessions)
    }
    roles = json.loads((fixture / "experts.json").read_text())
    questions = [
        q
        for q in json.loads((fixture / "questions.json").read_text())["questions"]
        if all(c in claims for c in q["pooled_ids"])
    ]
    manifest = json.loads((fixture / "manifest.json").read_text())
    return Answers(docs, vignettes, claims, labels, roles, questions, manifest)


# --- build: answers -> units, cue keys (no model) --------------------------------------------


def build(answers: Answers) -> dict:
    """Steps 2-7 of notes/new-chips-knowledge.md on every response, with the stored labels."""
    import chip_findings as cf

    records, cue_index, cue_keys, unit_cues = [], {}, [], []
    for doc in answers.docs:
        vignettes = {v.id: v for v in doc.vignettes}
        role = answers.roles.get(doc.session_id)
        for resp in doc.responses:
            v = vignettes[resp.vignette_id]
            labels = answers.labels[doc.session_id][resp.vignette_id]["labels"]
            rec = cf.build_record(
                resp, v.text, doc.session_id, doc.expert_id, role, v.framing,
                v.design.population, labels,
            )  # fmt: skip
            rec |= dict(track=v.design.track, origin=v.design.origin)
            records.append(rec)
            cue_of = {}
            for h in rec["highlights"]:
                key = (v.id, v.version, tuple(h["span"]))
                if key not in cue_index:
                    cue_index[key] = len(cue_keys)
                    cue_keys.append(
                        dict(id=len(cue_keys), vignette_id=v.id, vignette_version=v.version,
                             span=list(h["span"]), text=h["text"])
                    )  # fmt: skip
                cue_of[h["id"]] = cue_index[key]
            for u in rec["units"]:
                if u["highlight"]:
                    unit_cues.append(dict(unit=u["id"], cue_key=cue_of[u["highlight"]], role="cue"))
                unit_cues += [
                    dict(unit=u["id"], cue_key=cue_of[c], role="context") for c in u["context"]
                ]
    return dict(
        findings_version=cf.FINDINGS_VERSION, records=records, cue_keys=cue_keys,
        unit_cues=unit_cues,
        classifier=answers.manifest.get("classifier"), prompt=answers.manifest.get("prompt"),
    )  # fmt: skip


def tables_of(answers: Answers, built: dict, tier: str = TIER) -> tuple[dict, dict[str, str]]:
    """The rows of the chips tables, and build unit id -> database unit id."""
    by_doc = {d.session_id: d for d in answers.docs}
    experts, seen = [], set()
    sessions, highlights, sentences, units, unit_sentences = [], [], [], [], []
    cue_key_of = {
        (k["vignette_id"], k["vignette_version"], tuple(k["span"])): n
        for n, k in enumerate(built["cue_keys"])
    }
    cues_of_unit: dict[str, list[tuple[int, str]]] = {}
    for uc in built["unit_cues"]:
        cues_of_unit.setdefault(uc["unit"], []).append((uc["cue_key"], uc["role"]))
    local_of: dict[str, str] = {}
    segmenter = {k: built[k] for k in ("findings_version", "classifier", "prompt")}
    for rec in built["records"]:
        doc, vid, ver = by_doc[rec["session_id"]], rec["vignette_id"], rec["vignette_version"]
        sid, expert = session_of(tier, rec["session_id"], vid), f"{tier}/{rec['expert_id']}"
        if expert not in seen:
            seen.add(expert)
            experts.append({"id": expert, "role": answers.roles.get(doc.session_id)})
        document = deepcopy(rec)
        document["session_id"], document["expert_id"] = sid, expert
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
                "framing": meta["framing"], "embed_text": u["i1"],
            })  # fmt: skip
            unit_sentences += [[uid, f"{sid}-{vid}-{s}", n] for n, s in enumerate(u["sentences"])]
    unit_cues = [
        [local_of[u], k, role]
        for u, parts in cues_of_unit.items()
        for k, role in sorted(set(parts))
    ]
    vignette_rows = [
        {"id": v.id, "version": v.version, "tier": tier, "text": v.text, "content_hash": v.content_hash,
         "framing": v.framing, "population": v.design.population, "track": v.design.track}
        for v in answers.vignettes.values()
    ]  # fmt: skip
    tables = {
        "tier": tier, "segmenter": segmenter, "experts": experts, "vignettes": vignette_rows,
        "sessions": sessions,
        "cue_keys": [{k: c[k] for k in ("vignette_id", "vignette_version", "span", "text")} for c in built["cue_keys"]],
        "highlights": highlights, "sentences": sentences, "units": units,
        "unit_sentences": unit_sentences, "unit_cues": unit_cues,
    }  # fmt: skip
    return tables, local_of


# --- labels: which units hold a claim, and the patient-text queries --------------------------


def _overlap(a: list[int] | tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def covers_of(
    answers: Answers, built: dict, wanted: set[str], unit_vector: dict[str, np.ndarray], embed
) -> dict[str, set[str]]:
    """Build unit ids that hold each claim: among the units with a sentence from the claim's answer,
    those whose highlight overlaps the claim's quote; if none, the one nearest to the claim text."""
    recs = {(r["session_id"], r["vignette_id"]): r for r in built["records"]}
    covers: dict[str, set[str]] = {}
    nearest: list[tuple[str, list[dict]]] = []
    for cid in sorted(wanted):
        c = answers.claims[cid]
        rec = recs.get((c["session_id"], c["vignette_id"]))
        if rec is None:
            covers[cid] = set()
            continue
        in_answer = {s["id"] for s in rec["sentences"] if s["question_id"] == c["question_id"]}
        candidates = [u for u in rec["units"] if in_answer & set(u["sentences"])]
        span = c.get("quoted_span_text")
        start = answers.vignettes[c["vignette_id"]].text.find(span) if span else -1
        spans = {h["id"]: h["span"] for h in rec["highlights"]}
        hit = {
            u["id"]
            for u in candidates
            if start >= 0
            and u["highlight"]
            and _overlap(spans[u["highlight"]], (start, start + len(span)))
        }
        covers[cid] = hit
        if not hit and candidates:
            nearest.append((cid, candidates))
    if nearest:
        vectors = embed([answers.claims[cid]["claim_text"] for cid, _ in nearest])
        for (cid, candidates), v in zip(nearest, vectors, strict=True):
            v = np.asarray(v, dtype=np.float32)
            best = max(candidates, key=lambda u: float(unit_vector[u["id"]] @ v))
            covers[cid] = {best["id"]}
    return covers


def patient_queries(answers: Answers) -> list[dict]:
    """Each vignette's own text as a patient text; relevant: the claims about its planted traits made
    on other vignettes (not its variant pair), which are excluded from the search."""
    out = []
    vs = answers.vignettes
    for v in vs.values():
        traits = {c.trait for c in v.design.planted_cues}
        siblings = {
            w.id
            for w in vs.values()
            if w.id == v.id or (v.variant and w.variant and w.variant.pair_id == v.variant.pair_id)
        }
        relevant = [
            cid for cid, c in answers.claims.items()
            if c.get("trait") in traits and c["vignette_id"] not in siblings
        ]  # fmt: skip
        if relevant:
            out.append(
                {"id": v.id, "text": v.text, "claim_ids": relevant, "exclude": sorted(siblings)}
            )
    return out


# --- ingest: + vectors -----------------------------------------------------------------------


class IndexEmbeddings(Embeddings):
    """bge-m3 the way the application embeds, units at ingestion and questions at search
    (config/indexing.yaml through app.indexing). Each distinct text is embedded once."""

    def __init__(self, config: Path = CONFIG) -> None:
        from app.indexing import build_embedder, load_indexing_config

        cfg = load_indexing_config(config)
        self.model = cfg.embeddings.model
        self.dimensions = cfg.embeddings.dimensions
        self._embedder = build_embedder(cfg)
        self._seen: dict[str, np.ndarray] = {}

    def matrix(self, texts: list[str]) -> np.ndarray:
        missing = [t for t in dict.fromkeys(texts) if t not in self._seen]
        if missing:
            rows = np.asarray(self._embedder.embed(missing), dtype=np.float32)
            if rows.shape != (len(missing), self.dimensions):
                raise RuntimeError(
                    f"the embedder returned {rows.shape}, wanted {self.dimensions} columns"
                )
            self._seen.update(zip(missing, rows, strict=True))
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        return np.stack([self._seen[t] for t in texts])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.matrix(list(texts)).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.matrix([text])[0].tolist()


class Corpus(NamedTuple):
    tables: dict  # rows of the chips tables
    vectors: dict[str, np.ndarray]  # i1 (one row per unit), cues (one per cue key)
    queries: dict  # questions (+ vignettes), patients, covers (claim -> database unit ids)


def ingest(answers: Answers, embedder: IndexEmbeddings, patients: bool = True) -> Corpus:
    built = build(answers)
    tables, local_of = tables_of(answers, built)
    units = [u for r in built["records"] for u in r["units"]]
    i1 = embedder.matrix([u["i1"] for u in units])
    cues = embedder.matrix([k["text"] for k in built["cue_keys"]])
    unit_vector = {u["id"]: row for u, row in zip(units, i1, strict=True)}
    questions = [
        {**q, "vignettes": sorted({answers.claims[c]["vignette_id"] for c in q["pooled_ids"]})}
        for q in answers.questions
    ]
    patient_rows = patient_queries(answers) if patients else []
    wanted = {c for q in questions for c in q["pooled_ids"]} | {
        c for p in patient_rows for c in p["claim_ids"]
    }
    covers = covers_of(answers, built, wanted, unit_vector, embedder.embed_documents)
    queries = {
        "questions": questions,
        "patients": patient_rows,
        "covers": {c: sorted(local_of[u] for u in covers[c]) for c in sorted(covers)},
    }
    return Corpus(tables, {"i1": i1, "cues": cues}, queries)


# --- seeding ---------------------------------------------------------------------------------


def crowded(
    t: dict, vectors: dict[str, np.ndarray], copies: int, noise: float = 0.002, seed: int = 7
) -> tuple[dict, dict[str, np.ndarray]]:
    """The tables with `copies` more experts for every expert: each copy answers the same vignettes
    in the same words, with its vectors moved a little (`noise`, then normalised, so a copy stays a
    near-duplicate, cosine above 0.99). For testing how the retrievers behave when many experts
    answer one vignette alike. Synthetic by construction: it says nothing about retrieval quality."""
    rng = np.random.default_rng(seed)

    def move(row: np.ndarray) -> np.ndarray:
        moved = row + rng.normal(0, noise, row.shape).astype(np.float32)
        return moved / np.linalg.norm(moved)

    new = {key: list(rows) if isinstance(rows, list) else rows for key, rows in t.items()}
    rows_i1 = list(vectors["i1"])
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
                 "expert_id": u["expert_id"] + suffix, "highlight_id": rename(u["highlight_id"], sessions)}
            )  # fmt: skip
            rows_i1.append(move(vectors["i1"][i]))
        for unit, sentence, order in t["unit_sentences"]:
            new["unit_sentences"].append(
                [rename(unit, sessions), rename(sentence, sessions), order]
            )
        for unit, key, role in t["unit_cues"]:
            new["unit_cues"].append([rename(unit, sessions), key, role])
    return new, {**vectors, "i1": np.stack(rows_i1)}


def seed(
    conn: Any, schema: str, tables: dict, vectors: dict[str, np.ndarray], crowd: int = 0
) -> dict[str, int]:
    """Create `schema` from chips_schema.sql, insert the rows and fit BM25 (psycopg connection).
    `crowd` adds that many synthetic copies of every expert (see `crowded`)."""
    from psycopg import sql

    from expert_knowledge_core import bm25
    from expert_knowledge_core.bm25 import Bm25Config

    t = tables
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
            "population, track, framing, segmenter, embed_text, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, CAST(%s AS vector))",
            (u["id"], u["session_id"], u["expert_id"], u["vignette_id"], u["vignette_version"], u["kind"], u["highlight_id"], u["direction"],
             u["population"], u["track"], u["framing"], json.dumps(t["segmenter"]), u["embed_text"],
             vector_text(vectors["i1"][n])),
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
    fit_agreement(conn)
    return {
        name: len(t[name]) for name in ("sessions", "units", "cue_keys", "highlights", "sentences")
    }


@contextmanager
def seeded_schema(
    dsn: str, name: str, corpus: Corpus, crowd: int = 0, keep: bool = False
) -> Iterator[str]:
    """`name` seeded from `corpus` in one transaction (replacing a schema of that name); dropped on
    exit unless `keep`."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
            seed(conn, name, corpus.tables, corpus.vectors, crowd=crowd)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    try:
        yield name
    finally:
        if not keep:
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name))
                )


def fit_agreement(conn: Any, experts: list[str] | None = None) -> int:
    """Fills fragment_groups from the highlights in the schema, with the code the application
    uses (expert_knowledge_core.agreement). `experts` limits it to a pool of experts: the groups
    and the counts are then those of a corpus that only they answered. Returns the number of
    groups."""
    from expert_knowledge_core.agreement import RULE_VERSION, Mark, agreement_groups

    pool = list(experts) if experts is not None else None
    rows = conn.execute(
        "SELECT h.id, s.expert_id, lower(h.span), upper(h.span), h.direction, "
        "h.vignette_id, h.vignette_version FROM highlights h "
        "JOIN elicitation_sessions s ON s.id = h.session_id WHERE h.origin = 'expert' "
        "AND (%(pool)s::text[] IS NULL OR s.expert_id = ANY(%(pool)s))",
        {"pool": pool},
    ).fetchall()
    answered = dict(
        ((v, ver), n)
        for v, ver, n in conn.execute(
            "SELECT vignette_id, vignette_version, count(DISTINCT expert_id) FROM finding_units "
            "WHERE (%(pool)s::text[] IS NULL OR expert_id = ANY(%(pool)s)) GROUP BY 1, 2",
            {"pool": pool},
        ).fetchall()
    )
    by_version: dict[tuple[str, int], list[Any]] = {}
    for hid, expert, a, b, direction, vid, ver in rows:
        by_version.setdefault((vid, ver), []).append(Mark(hid, expert, (a, b), direction))
    written = 0
    for (vid, ver), marks in by_version.items():
        for members, a in agreement_groups(marks, answered.get((vid, ver), 0)):
            group_id = conn.execute(
                "INSERT INTO fragment_groups (vignette_id, vignette_version, span, n_answered, "
                "n_attending, n_toward, n_away, n_neutral, n_unclear, n_mixed, label, rule_version) "
                "VALUES (%s, %s, int4range(%s, %s), %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (vid, ver, a.span[0], a.span[1], a.n, a.k, a.counts.get("toward", 0),
                 a.counts.get("away", 0), a.counts.get("neutral", 0), a.counts.get("unclear", 0),
                 a.counts.get("mixed", 0), a.label, RULE_VERSION),
            ).fetchone()[0]  # fmt: skip
            for m in members:
                conn.execute(
                    "INSERT INTO fragment_group_members VALUES (%s, %s, %s)",
                    (group_id, m.id, m.expert),
                )
            written += 1
    return written


def refit_agreement(conn: Any, experts: list[str] | None = None) -> int:
    """Replaces the groups (members go with them) by those of the pool `experts` (None: everyone)."""
    conn.execute("DELETE FROM fragment_groups")
    return fit_agreement(conn, experts)


def set_agreement_pool(dsn: str, schema: str, experts: list[str] | None) -> dict[str, int]:
    """Commits the groups of the pool `experts` (None: everyone) into `schema`; returns the group of
    every highlight (a fragment unit's id is its highlight's id)."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("SET search_path = {}, public").format(sql.Identifier(schema)))
        refit_agreement(conn, experts)
        return dict(conn.execute("SELECT highlight_id, group_id FROM fragment_group_members").fetchall())


def refit_sparse(conn: Any, cfg: Any, bm25: Any) -> None:
    """BM25 for the units (I1) and the cue keys, each over its own corpus."""
    units = conn.execute("SELECT id, embed_text FROM finding_units ORDER BY id").fetchall()
    keys = conn.execute("SELECT id, text FROM cue_keys ORDER BY id").fetchall()
    for (uid, _), a in zip(units, bm25.fit([u[1] for u in units], cfg), strict=True):
        conn.execute(
            "UPDATE finding_units SET sparse = CAST(%s AS sparsevec) WHERE id = %s",
            (a.to_text(), uid),
        )
    for (kid, _), v in zip(keys, bm25.fit([k[1] for k in keys], cfg), strict=True):
        conn.execute(
            "UPDATE cue_keys SET sparse = CAST(%s AS sparsevec) WHERE id = %s", (v.to_text(), kid)
        )


# --- the command line ------------------------------------------------------------------------

SCALE_FIXTURES = ROOT / "data" / "fixtures_chips_scale_proofread" / "synthetic" / "silver"
SCALE_LABELS = (
    ROOT
    / "data"
    / "expert_units_chips_scale_proofread"
    / "synthetic"
    / "silver"
    / "qwen3.5-9b"
    / "labels"
)


def export(fixtures: Path, labels: Path, out: Path, questions: list[dict] | None = None) -> dict:
    """Copy the answers (documents, claims), the classifier's labels and the role lines into `out`.
    `questions` default to the ones already in `out`."""
    from chips_schema import ChipDocument
    from make_fixtures import PERSONAS
    from make_scale_fixtures import with_scale_personas
    from make_unit_keys import role_for

    if questions is None:
        questions = json.loads((out / "questions.json").read_text())["questions"]
    with_scale_personas()
    assert PERSONAS["silver"]
    for sub in ("documents", "claims", "labels"):
        shutil.rmtree(out / sub, ignore_errors=True)
        (out / sub).mkdir(parents=True)
    roles, models = {}, set()
    for path in sorted((fixtures / "documents").glob("DOC-*.json")):
        doc = ChipDocument.model_validate_json(path.read_text())
        shutil.copyfile(path, out / "documents" / path.name)
        claims = fixtures / "claims" / f"{doc.session_id}.claims.json"
        if claims.exists():
            shutil.copyfile(claims, out / "claims" / claims.name)
        saved = json.loads((labels / f"{doc.session_id}.json").read_text())
        models.add((saved["model"], saved["prompt"]))
        slim = {"model": saved["model"], "prompt": saved["prompt"],
                "responses": {v: {"labels": r["labels"]} for v, r in saved["responses"].items()}}  # fmt: skip
        dump(out / "labels" / path.name, slim)
        roles[doc.session_id] = role_for(TIER, doc.session_id, doc.expert_id)
    (model, prompt), *rest = sorted(models)
    if rest:
        raise SystemExit(f"labels of several classifiers: {sorted(models)}")
    dump(out / "experts.json", roles)
    dump(out / "questions.json", {"questions": questions})
    manifest = {
        "what": "filled vignettes before ingestion: chip documents after proofreading, their claims, "
        "the classifier's sentence links, the role lines; 40 questions labelled with claims of SYN-001/002",
        "classifier": model, "prompt": prompt,
        "sources": {"documents": str(fixtures.relative_to(ROOT)), "labels": str(labels.relative_to(ROOT))},
        "counts": {"documents": len(roles), "questions": len(questions)},
    }  # fmt: skip
    dump(out / "manifest.json", manifest)
    return manifest


def dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def check(fixture: Path = FIXTURE) -> list[str]:
    """What is wrong with the fixture, without a model: every response builds, every label names a
    claim that exists."""
    answers = load(fixture)
    problems = []
    try:
        built = build(answers)
    except Exception as e:  # noqa: BLE001
        return [f"the answers do not build: {e}"]
    if not built["records"]:
        problems.append("no responses")
    problems += [
        f"question {n}: unknown claim {c}"
        for n, q in enumerate(json.loads((fixture / "questions.json").read_text())["questions"], 1)
        for c in q["pooled_ids"]
        if c not in answers.claims
    ]
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export", help="write the fixture from the scale build under data/")
    ex.add_argument("--fixtures", type=Path, default=SCALE_FIXTURES)
    ex.add_argument("--labels", type=Path, default=SCALE_LABELS)
    ex.add_argument("--out", type=Path, default=FIXTURE)
    sub.add_parser("check")
    sd = sub.add_parser("seed", help="ingest the fixture into a schema (needs Postgres and Ollama)")
    sd.add_argument("--schema", required=True)
    sd.add_argument("--experts", nargs="+", help="only these experts (default: all)")
    args = ap.parse_args(argv)
    if args.command == "export":
        for p in ("rag",):
            sys.path.insert(0, str(ROOT / "scripts" / p))
        args.out.mkdir(parents=True, exist_ok=True)
        print(json.dumps(export(args.fixtures, args.labels, args.out), indent=1))
        return 0
    if args.command == "check":
        problems = check()
        print("\n".join(problems) or "fixture is consistent")
        return 1 if problems else 0
    from app.settings import settings

    corpus = ingest(load(experts=args.experts), IndexEmbeddings())
    with seeded_schema(settings.database_url, args.schema, corpus, keep=True):
        pass
    print(
        f"seeded {args.schema}: {len(corpus.tables['units'])} units, {len(corpus.tables['cue_keys'])} cue keys"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
