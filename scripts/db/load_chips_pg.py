# ruff: noqa: E501  (long SQL strings)
"""Load built chip units into Postgres, schema `chips` (docs/new-chips-knowledge.md "Storage").

Usage: python scripts/db/load_chips_pg.py --tier silver [--classifier qwen3.5:9b] [--schema chips_eval]
       python scripts/db/load_chips_pg.py --tier bronze
       python scripts/db/load_chips_pg.py --check --tier silver     # row counts vs the JSON

Reads what build_chip_units.py wrote (units.json + embeddings.npz) and the chip documents. Creates
the tables from chips_schema.sql, replaces the rows of this tier (a reload is idempotent), then
refits BM25 separately for the units (I1 and I3 each) and for the cue keys, over everything in the
schema. Ids carry the tier (`silver/DOC-SYN-0001`) because the tiers reuse session and expert ids.
Synthetic data: nothing here touches public.chunks or backend/db/init.sql, and it refuses the
schema `chips`, which is where the web application ingests approved answers.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import asyncpg
import numpy as np
from pgvector.asyncpg import register_vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "elicitation"))
from build_chip_units import load_built  # noqa: E402
from classify_sentence_targets import FIXTURES, UNITS, documents, model_tag  # noqa: E402
from make_unit_keys import role_for  # noqa: E402

from app.indexing import bm25, load_indexing_config  # noqa: E402
from app.settings import settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DDL = Path(__file__).with_name("chips_schema.sql")


def pid(session: str, vignette: str, local: str) -> str:
    return f"{session}-{vignette}-{local}"


def rng(span) -> asyncpg.Range:
    return asyncpg.Range(int(span[0]), int(span[1]))


async def refresh_sparse(conn: asyncpg.Connection) -> dict[str, int]:
    """BM25 refit: units (I1 and I3 separately) and cue keys, each over its own corpus."""
    cfg = load_indexing_config(ROOT / "config/indexing.yaml").sparse
    units = await conn.fetch(
        "SELECT id, embed_text, embed_text_combined FROM finding_units ORDER BY id"
    )
    keys = await conn.fetch("SELECT id, text FROM cue_keys ORDER BY id")
    sparse = bm25.fit([r["embed_text"] for r in units], cfg)
    combined = bm25.fit([r["embed_text_combined"] for r in units], cfg)
    cue = bm25.fit([r["text"] for r in keys], cfg)
    async with conn.transaction():
        await conn.executemany(
            "UPDATE finding_units SET sparse = $2, sparse_combined = $3 WHERE id = $1",
            [(r["id"], a, b) for r, a, b in zip(units, sparse, combined, strict=True)],
        )
        await conn.executemany(
            "UPDATE cue_keys SET sparse = $2 WHERE id = $1",
            [(r["id"], v) for r, v in zip(keys, cue, strict=True)],
        )
    return {"finding_units": len(units), "cue_keys": len(keys)}


async def load(args) -> None:
    tag = args.tag or model_tag(args.classifier)
    built, arrays = load_built(args.tier, tag, args.out)
    docs = {d.session_id: d for d in documents(args.tier, args.fixtures)}
    conn = await asyncpg.connect(settings.database_url)
    try:
        await register_vector(conn)
        await conn.execute(DDL.read_text().format(schema=args.schema))
        await conn.execute(f"SET search_path = {args.schema}, public")
        await register_vector(conn)
        key = lambda sid: f"{args.tier}/{sid}"  # noqa: E731
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM elicitation_sessions WHERE id LIKE $1", f"{args.tier}/%"
            )
            await conn.execute("DELETE FROM experts WHERE id LIKE $1", f"{args.tier}/%")
            for doc in docs.values():
                await conn.execute(
                    "INSERT INTO experts VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
                    key(doc.expert_id), role_for(args.tier, doc.session_id, doc.expert_id), doc.is_synthetic,
                )  # fmt: skip
                await conn.execute(
                    "INSERT INTO elicitation_sessions VALUES ($1, $2, $3, $4, $5)",
                    key(doc.session_id), key(doc.expert_id), doc.is_synthetic,
                    json.dumps(doc.model_dump(mode="json")), doc.created_at,
                )  # fmt: skip
                for v in doc.vignettes:
                    await conn.execute(
                        "INSERT INTO vignettes VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                        "ON CONFLICT DO NOTHING",
                        v.id, v.version, args.tier, v.text, v.content_hash, v.framing,
                        v.design.population, v.design.track,
                    )  # fmt: skip

            cue_id = {}  # index in units.json -> database id (shared across tiers and experts)
            for k, vec in zip(built["cue_keys"], arrays["i2"], strict=True):
                cue_id[k["id"]] = await conn.fetchval(
                    "INSERT INTO cue_keys (vignette_id, vignette_version, span, text, embedding) "
                    "VALUES ($1, $2, $3, $4, $5) "
                    "ON CONFLICT (vignette_id, vignette_version, span) DO UPDATE SET text = EXCLUDED.text "
                    "RETURNING id",
                    k["vignette_id"], k["vignette_version"], rng(k["span"]), k["text"], vec,
                )  # fmt: skip
            cue_of_unit = {}
            for uc in built["unit_cues"]:
                cue_of_unit.setdefault(uc["unit"], []).append(uc)

            segmenter = json.dumps(
                {"findings_version": built["findings_version"], "classifier": built["classifier"],
                 "prompt": built["prompt"]}
            )  # fmt: skip
            span_key = {
                (k["vignette_id"], k["vignette_version"], tuple(k["span"])): k["id"]
                for k in built["cue_keys"]
            }
            unit_row = 0
            for rec in built["records"]:
                sid, vid, ver = key(rec["session_id"]), rec["vignette_id"], rec["vignette_version"]
                cue_of_highlight = {}
                for h in rec["highlights"]:
                    cue_of_highlight[h["id"]] = cue_id[span_key[(vid, ver, tuple(h["span"]))]]
                    await conn.execute(
                        "INSERT INTO highlights (id, session_id, vignette_id, vignette_version, chip, "
                        "span, origin, direction, cue_key_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                        pid(sid, vid, h["id"]), sid, vid, ver, h["chip"], rng(h["span"]), h["origin"],
                        h["direction"], cue_of_highlight[h["id"]],
                    )  # fmt: skip
                await conn.executemany(
                    "INSERT INTO answer_sentences (id, session_id, vignette_id, vignette_version, "
                    "question_id, idx, span, targets, assigned_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    [
                        (pid(sid, vid, s["id"]), sid, vid, ver, s["question_id"], s["idx"], rng(s["span"]),
                         [t if t == "case" else pid(sid, vid, t) for t in s["targets"]], s["assigned_by"])
                        for s in rec["sentences"]
                    ],
                )  # fmt: skip
                meta = rec["meta"]
                for u in rec["units"]:
                    uid = f"{sid}-{vid}-{u['highlight'] or 'case'}"
                    await conn.execute(
                        "INSERT INTO finding_units (id, session_id, expert_id, vignette_id, "
                        "vignette_version, kind, highlight_id, direction, population, track, framing, "
                        "is_synthetic, segmenter, embed_text, embedding, embed_text_combined, "
                        "embedding_combined) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,"
                        "$15,$16,$17)",
                        uid, sid, key(rec["expert_id"]), vid, ver, u["kind"],
                        pid(sid, vid, u["highlight"]) if u["highlight"] else None, u["direction"],
                        meta["population"], rec["track"], meta["framing"], rec["is_synthetic"],
                        segmenter, u["i1"], arrays["i1"][unit_row], u["i3"], arrays["i3"][unit_row],
                    )  # fmt: skip
                    unit_row += 1
                    await conn.executemany(
                        "INSERT INTO finding_unit_sentences VALUES ($1, $2, $3)",
                        [(uid, pid(sid, vid, s), n) for n, s in enumerate(u["sentences"])],
                    )
                    cues = {(c["cue_key"], c["role"]) for c in cue_of_unit.get(u["id"], [])}
                    await conn.executemany(
                        "INSERT INTO unit_cues VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                        [(uid, cue_id[ck], role) for ck, role in sorted(cues)],
                    )
            await conn.executemany(
                "INSERT INTO review_events VALUES ($1, $2, $3, $4, $5)",
                [(key(e["session_id"]), e["vignette_id"], e["kind"], json.dumps(e["payload"]),
                  datetime.fromisoformat(e["at"])) for e in built["events"]],
            )  # fmt: skip
        counts = await refresh_sparse(conn)
        print(
            f"loaded {args.tier}/{tag} into schema {args.schema}: {built['stats']}; fitted {counts}"
        )
    finally:
        await conn.close()


async def check(args) -> int:
    tag = args.tag or model_tag(args.classifier)
    built, arrays = load_built(args.tier, tag, args.out)
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(f"SET search_path = {args.schema}, public")
        await register_vector(conn)
        like = f"{args.tier}/%"
        want = {
            "finding_units": len([u for r in built["records"] for u in r["units"]]),
            "answer_sentences": len([s for r in built["records"] for s in r["sentences"]]),
            "highlights": len([h for r in built["records"] for h in r["highlights"]]),
            "review_events": len(built["events"]),
        }
        got = {
            t: await conn.fetchval(f"SELECT count(*) FROM {t} WHERE session_id LIKE $1", like)
            for t in want
        }
        print("rows (database vs json):", {k: (got[k], want[k]) for k in want})
        # a unit queried with its own I1 vector must come back first, with distance ~ 0
        rows = await conn.fetch(
            "SELECT id, embedding <=> $1 AS d FROM finding_units WHERE session_id LIKE $2 "
            "ORDER BY embedding <=> $1 LIMIT 3", arrays["i1"][0], like,
        )  # fmt: skip
        first = built["records"][0]["units"][0]["id"].split(":")
        expect = f"{args.tier}/{first[0]}-{first[1]}-{first[2]}"
        print(
            f"nearest to unit 0: {rows[0]['id']} (distance {rows[0]['d']:.4f}); expected {expect}"
        )
        top = int(np.argmax(arrays["i1"] @ arrays["i1"][0]))
        ok = got == want and rows[0]["id"] == expect and top == 0
        print("OK" if ok else "MISMATCH")
        return 0 if ok else 1
    finally:
        await conn.close()


APP_SCHEMA = "chips"  # approved answers of the web application (backend/app/knowledge/ingest.py)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", required=True, choices=["bronze", "silver"])
    ap.add_argument("--classifier", default="qwen3.5:9b")
    ap.add_argument("--tag", help="default: derived from the classifier")
    ap.add_argument("--schema", default="chips_eval")
    ap.add_argument("--fixtures", type=Path, default=FIXTURES)
    ap.add_argument("--out", type=Path, default=UNITS)
    ap.add_argument("--check", action="store_true", help="compare row counts and one query")
    args = ap.parse_args(argv)
    if args.schema == APP_SCHEMA:
        ap.error(
            f"schema {APP_SCHEMA!r} holds the application's approved answers, not test data: "
            "use another schema (the default is chips_eval)"
        )
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.check:
        return asyncio.run(check(args))
    asyncio.run(load(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
