"""Writes an assignment's approved units into the RAG tables (schema `chips`).

The tables and their meaning are in notes/new-chips-knowledge.md ("Storage"); scripts/db/
load_chips_pg.py does the same for the fixture data, and this is the same SQL run inside the
job's transaction, so that the rows, the units' new status and the workflow state commit together.

Two phases, as every job has them (app.jobs.handlers):
  load + embed   no transaction, no lock: reads what was approved, calls the embedding model
  write          under the assignment lock: replaces this assignment's rows, refits BM25

Only approved units go in. The stored `document` is the record cut down to them: their sentences,
their highlights, nothing the reviewers rejected. Vectors travel through SQL casts (`CAST(:v AS
vector)` from text), so no codec has to be registered on the connection.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pgvector import SparseVector
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment
from app.indexing import bm25, load_indexing_config
from app.jobs.errors import NoFindings, NoUnits, UnitsNotEmbeddable
from app.knowledge import embedding
from app.knowledge.findings import CASE
from app.knowledge.models import AnswerFindings, KnowledgeUnit, UnitStatus
from app.settings import settings
from app.users.models import User
from app.vignettes.service import version_and_code

TIER = "app"  # chips.vignettes is keyed by tier; the experiments used bronze and silver
BM25_LOCK = 4_715_331_001  # BM25 weights are corpus-wide, so only one ingestion refits at a time


@dataclass
class Ingestion:
    session_id: str
    expert_id: str
    created_at: datetime
    vignette: dict[str, Any]
    document: dict[str, Any]
    events: list[tuple[str, dict[str, Any], datetime]]
    segmenter: dict[str, Any]
    meta: dict[str, Any]
    track: str
    vectors: dict[str, list[list[float]]] = field(default_factory=dict)

    @property
    def highlights(self) -> list[dict[str, Any]]:
        return self.document["highlights"]

    @property
    def units(self) -> list[dict[str, Any]]:
        return self.document["units"]

    def texts(self) -> list[str]:
        return (
            [u["i1"] for u in self.units]
            + [h["text"] for h in self.highlights]
            + [u["i3"] for u in self.units]
        )


def _as_time(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _events(record: dict, kept_highlights: set[str], kept_sentences: set[str], row: AnswerFindings):
    """What the expert was shown and did on the check screen: ids and kinds, never their words."""
    events: list[tuple[str, dict[str, Any], datetime]] = []
    for flag in record.get("flags_shown", []):
        if flag["highlight"] in kept_highlights:
            events.append(("flag_shown", flag, _as_time(row.created_at)))
    for c in record.get("corrections", []):
        if c["kind"] == "sentence_moved" and c["sentence"] in kept_sentences:
            payload = {k: c[k] for k in ("sentence", "before", "after")}
            events.append(("sentence_moved", payload, _as_time(c["at"])))
        elif c["kind"] == "toggle_changed" and c["highlight"] in kept_highlights:
            payload = {k: c[k] for k in ("highlight", "before", "after", "after_flag")}
            events.append(("toggle_changed", payload, _as_time(c["at"])))
    if row.check_outcome == "skipped":
        events.append(("skipped", {"reason": "the check was skipped"}, _as_time(row.updated_at)))
    return events


async def load(db: AsyncSession, assignment_id: UUID) -> Ingestion:
    """The approved units of an assignment, cut out of its findings. Refuses what can't go in."""
    assignment = await db.get(Assignment, assignment_id)
    assert assignment is not None
    expert = await db.get(User, assignment.expert_id)
    assert expert is not None

    units = list(
        await db.scalars(
            select(KnowledgeUnit)
            .where(
                KnowledgeUnit.assignment_id == assignment_id,
                # INGESTED too, so that running it again replaces the same rows.
                KnowledgeUnit.status.in_([UnitStatus.APPROVED, UnitStatus.INGESTED]),
            )
            .order_by(KnowledgeUnit.ordinal)
        )
    )
    if not units:
        raise NoUnits
    if any(u.embed_text is None or u.embed_text_combined is None for u in units):
        raise UnitsNotEmbeddable
    row = await db.get(AnswerFindings, assignment_id)
    if row is None:
        raise NoFindings
    version, code = await version_and_code(db, assignment.vignette_version_id)

    record = row.record
    kept_highlights = {u.highlight_id for u in units if u.highlight_id} | {
        c for u in units for c in (u.context or [])
    }
    kept_sentences = {s for u in units for s in (u.sentence_ids or [])}
    has_case = any(u.highlight_id is None for u in units)
    document = {
        "version": record["version"],
        "session_id": record["session_id"],
        "expert_id": record["expert_id"],
        "vignette_id": record["vignette_id"],
        "vignette_version": record["vignette_version"],
        "meta": record["meta"],
        "highlights": [h for h in record["highlights"] if h["id"] in kept_highlights],
        "sentences": [
            {
                **s,
                "targets": [
                    t for t in s["targets"] if t in kept_highlights or (t == CASE and has_case)
                ],
            }
            for s in record["sentences"]
            if s["id"] in kept_sentences
        ],
        "units": [
            {
                "id": u.highlight_id or CASE,
                "kind": u.kind,
                "highlight": u.highlight_id,
                "direction": u.direction,
                "sentences": u.sentence_ids or [],
                "context": u.context or [],
                "body": u.text,
                "i1": u.embed_text,
                "i3": u.embed_text_combined,
            }
            for u in units
        ],
    }
    design = version.design
    return Ingestion(
        session_id=str(assignment_id),
        expert_id=str(expert.id),
        created_at=_as_time(assignment.submitted_at or row.created_at),
        vignette={
            "code": code,
            "version": version.version,
            "text": version.text,
            "content_hash": version.content_hash,
            "framing": version.framing,
            "population": design.get("population", "adult"),
        },
        document=document,
        events=_events(record, kept_highlights, kept_sentences, row),
        segmenter={
            "findings_version": row.findings_version,
            "classifier": row.classifier,
            "prompt": row.prompt,
        },
        meta=record["meta"],
        track=design.get("track", "general"),
    )


async def embed(data: Ingestion) -> Ingestion:
    """I1 (what was reviewed), I2 (the patient's words of each citation), I3 (I1 with the patient's
    words), in one call. `embedding.embed_texts` is looked up here so that tests can replace it."""
    vectors = await embedding.embed_texts(data.texts())
    n, m = len(data.units), len(data.highlights)
    if len(vectors) != 2 * n + m:
        raise RuntimeError(f"expected {2 * n + m} vectors, got {len(vectors)}")
    data.vectors = {"i1": vectors[:n], "i2": vectors[n : n + m], "i3": vectors[n + m :]}
    return data


# --- writing ----------------------------------------------------------------------------------


def _vec(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in values) + "]"


def _span(span: list[int]) -> dict[str, int]:
    return {"a": int(span[0]), "b": int(span[1])}


async def write(db: AsyncSession, d: Ingestion) -> None:
    """Replaces everything this assignment has in `chips`, then refits BM25. Inside the caller's
    transaction: if anything fails, the tables are as they were."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": BM25_LOCK})
    await db.execute(
        text("DELETE FROM chips.elicitation_sessions WHERE id = :sid"), {"sid": d.session_id}
    )
    v = d.vignette
    await db.execute(
        text("INSERT INTO chips.experts (id, role) VALUES (:id, NULL) ON CONFLICT (id) DO NOTHING"),
        {"id": d.expert_id},
    )
    await db.execute(
        text(
            "INSERT INTO chips.vignettes (id, version, tier, text, content_hash, framing, "
            "population, track) VALUES (:id, :ver, :tier, :text, :hash, :framing, :pop, :track) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "id": v["code"], "ver": v["version"], "tier": TIER, "text": v["text"],
            "hash": v["content_hash"], "framing": v["framing"], "pop": v["population"],
            "track": d.track,
        },
    )  # fmt: skip
    await db.execute(
        text(
            "INSERT INTO chips.elicitation_sessions (id, expert_id, document, created_at) "
            "VALUES (:id, :expert, CAST(:doc AS jsonb), :at)"
        ),
        {
            "id": d.session_id, "expert": d.expert_id,
            "doc": json.dumps(d.document), "at": d.created_at,
        },
    )  # fmt: skip

    def pid(local: str) -> str:
        return f"{d.session_id}-{v['code']}-{local}"

    cue_id: dict[str, int] = {}
    for highlight, vector in zip(d.highlights, d.vectors["i2"], strict=True):
        cue_id[highlight["id"]] = await db.scalar(
            text(
                "INSERT INTO chips.cue_keys (vignette_id, vignette_version, span, text, embedding) "
                "VALUES (:vid, :ver, int4range(:a, :b), :text, CAST(CAST(:emb AS text) AS vector)) "
                "ON CONFLICT (vignette_id, vignette_version, span) "
                "DO UPDATE SET text = EXCLUDED.text RETURNING id"
            ),
            {"vid": v["code"], "ver": v["version"], **_span(highlight["span"]),
             "text": highlight["text"], "emb": _vec(vector)},
        )  # fmt: skip
    for highlight in d.highlights:
        await db.execute(
            text(
                "INSERT INTO chips.highlights (id, session_id, vignette_id, vignette_version, "
                "chip, span, origin, direction, direction_changed_after_flag, cue_key_id) "
                "VALUES (:id, :sid, :vid, :ver, :chip, int4range(:a, :b), :origin, :direction, "
                ":changed, :cue)"
            ),
            {
                "id": pid(highlight["id"]), "sid": d.session_id, "vid": v["code"],
                "ver": v["version"], "chip": highlight["chip"], **_span(highlight["span"]),
                "origin": highlight["origin"], "direction": highlight["direction"],
                "changed": bool(highlight.get("direction_changed_after_flag", False)),
                "cue": cue_id[highlight["id"]],
            },
        )  # fmt: skip
    if d.document["sentences"]:
        await db.execute(
            text(
                "INSERT INTO chips.answer_sentences (id, session_id, vignette_id, "
                "vignette_version, question_id, idx, span, targets, assigned_by) "
                "VALUES (:id, :sid, :vid, :ver, :qid, :idx, int4range(:a, :b), :targets, :by)"
            ),
            [
                {
                    "id": pid(s["id"]), "sid": d.session_id, "vid": v["code"], "ver": v["version"],
                    "qid": s["question_id"], "idx": s["idx"], **_span(s["span"]),
                    "targets": [t if t == CASE else pid(t) for t in s["targets"]],
                    "by": s["assigned_by"],
                }
                for s in d.document["sentences"]
            ],
        )  # fmt: skip

    segmenter = json.dumps(d.segmenter)
    for unit, i1, i3 in zip(d.units, d.vectors["i1"], d.vectors["i3"], strict=True):
        unit_id = pid(unit["id"])
        await db.execute(
            text(
                "INSERT INTO chips.finding_units (id, session_id, expert_id, vignette_id, "
                "vignette_version, kind, highlight_id, direction, population, track, framing, "
                "segmenter, embed_text, embedding, embed_text_combined, "
                "embedding_combined) VALUES (:id, :sid, :expert, :vid, :ver, :kind, :hid, "
                ":direction, :pop, :track, :framing, CAST(:seg AS jsonb), :i1text, "
                "CAST(CAST(:i1 AS text) AS vector), :i3text, CAST(CAST(:i3 AS text) AS vector))"
            ),
            {
                "id": unit_id, "sid": d.session_id, "expert": d.expert_id, "vid": v["code"],
                "ver": v["version"], "kind": unit["kind"],
                "hid": pid(unit["highlight"]) if unit["highlight"] else None,
                "direction": unit["direction"], "pop": v["population"], "track": d.track,
                "framing": v["framing"], "seg": segmenter,
                "i1text": unit["i1"], "i1": _vec(i1), "i3text": unit["i3"], "i3": _vec(i3),
            },
        )  # fmt: skip
        for order, sentence in enumerate(unit["sentences"]):
            await db.execute(
                text("INSERT INTO chips.finding_unit_sentences VALUES (:u, :s, :o)"),
                {"u": unit_id, "s": pid(sentence), "o": order},
            )
        cues = ([(unit["highlight"], "cue")] if unit["highlight"] else []) + [
            (c, "context") for c in unit["context"]
        ]
        for highlight_id, role in cues:
            await db.execute(
                text("INSERT INTO chips.unit_cues VALUES (:u, :c, :r) ON CONFLICT DO NOTHING"),
                {"u": unit_id, "c": cue_id[highlight_id], "r": role},
            )
    if d.events:
        await db.execute(
            text(
                "INSERT INTO chips.review_events (session_id, vignette_id, kind, payload, at) "
                "VALUES (:sid, :vid, :kind, CAST(:payload AS jsonb), :at)"
            ),
            [
                {"sid": d.session_id, "vid": v["code"], "kind": kind,
                 "payload": json.dumps(payload), "at": at}
                for kind, payload, at in d.events
            ],
        )  # fmt: skip
    await refresh_sparse(db)


async def refresh_sparse(db: AsyncSession) -> None:
    """Refits BM25 over everything in `chips`: the units' two texts and the cue keys, each with
    its own statistics, as the experiments did.

    shortcut: this refits the whole corpus on every ingestion. Fine for hundreds of units; at
    thousands, fit incrementally or in a nightly job.
    """
    config = load_indexing_config(settings.project_root / "config" / "indexing.yaml").sparse
    units = (
        await db.execute(
            text("SELECT id, embed_text, embed_text_combined FROM chips.finding_units ORDER BY id")
        )
    ).all()
    keys = (await db.execute(text("SELECT id, text FROM chips.cue_keys ORDER BY id"))).all()

    def sparse(vector: SparseVector) -> str:
        return vector.to_text()

    first = bm25.fit([u.embed_text for u in units], config)
    second = bm25.fit([u.embed_text_combined for u in units], config)
    cues = bm25.fit([k.text for k in keys], config)
    if units:
        await db.execute(
            text(
                "UPDATE chips.finding_units SET sparse = CAST(CAST(:a AS text) AS sparsevec), "
                "sparse_combined = CAST(CAST(:b AS text) AS sparsevec) WHERE id = :id"
            ),
            [
                {"id": u.id, "a": sparse(a), "b": sparse(b)}
                for u, a, b in zip(units, first, second, strict=True)
            ],
        )
    if keys:
        await db.execute(
            text(
                "UPDATE chips.cue_keys SET sparse = CAST(CAST(:a AS text) AS sparsevec) "
                "WHERE id = :id"
            ),
            [{"id": k.id, "a": sparse(c)} for k, c in zip(keys, cues, strict=True)],
        )
