"""Embed the chunked documents in the S3 (MinIO) documents bucket into the pgvector `chunks` table.

Usage: python scripts/corpus/index_chunks.py [--config config/indexing.yaml] [--prefix chunked/]
                                      [--only ID ...] [--force]

Reads s3://$S3_BUCKET/chunked/<source_id>/<stem>.json (as written by chunk_parsed_documents.py),
embeds each chunk with the model from the indexing config (Ollama) and replaces that document's
rows in the Postgres `chunks` table, then marks the document `indexed`. Run scripts/db/init_db.py
first so the table exists.

Rows carry the chunked file's sha256 and the config hash, so unchanged documents are skipped
unless --force is given. Afterwards the BM25 sparse vectors (chunks.sparse) are refitted over the
whole table, as idf and avgdl are corpus-global. A per-file report is written to
chunked/_index_report.json.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import asyncpg
import numpy as np
from pgvector.asyncpg import register_vector

from app.indexing import IndexingConfig, bm25, build_embedder, load_indexing_config
from app.settings import settings
from app.sources import excluded_source_ids
from app.storage import s3_get, s3_list_keys, s3_put

INSERT_CHUNK = """
INSERT INTO chunks (
    id, document_id, chunk_index, text, contextual_text, heading_path, section_ids, block_types,
    pages, n_tokens, metadata, embedding, embedding_model, chunked_key, chunked_sha256,
    index_config
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
"""


def chunked_keys(prefix: str) -> list[str]:
    """chunked/<source_id>/<stem>.json keys (not the reports at the top level)."""
    return sorted(
        k
        for k in s3_list_keys(prefix)
        if k.endswith(".json") and len(PurePosixPath(k[len(prefix) :]).parts) == 2
    )


async def check_table(conn: asyncpg.Connection, cfg: IndexingConfig) -> None:
    column_type = await conn.fetchval(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = to_regclass('chunks') AND attname = 'embedding'"
    )
    if column_type is None:
        raise SystemExit("No `chunks` table: run scripts/db/init_db.py first")
    expected = f"vector({cfg.embeddings.dimensions})"
    if column_type != expected:
        raise SystemExit(
            f"chunks.embedding is {column_type} but the config wants {expected}: "
            "DROP TABLE chunks, run scripts/db/init_db.py (after updating init.sql) and re-index"
        )


async def check_sparse_column(conn: asyncpg.Connection) -> None:
    width = await conn.fetchval(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = to_regclass('chunks') AND attname = 'sparse'"
    )
    if width != f"sparsevec({bm25.DIMENSIONS})":
        raise SystemExit("chunks.sparse is missing or has the wrong width: run scripts/db/init_db.py")


async def refresh_sparse(conn: asyncpg.Connection, cfg: IndexingConfig) -> int:
    """Refit BM25 over every chunk in the table and store the vectors in chunks.sparse. idf and
    avgdl are corpus-global, so this runs on every index run, also when all documents were
    skipped. Returns the number of chunks."""
    rows = await conn.fetch(f"SELECT id, {cfg.text_field} AS text FROM chunks ORDER BY id")
    vectors = bm25.fit([r["text"] for r in rows], cfg.sparse)
    async with conn.transaction():
        await conn.executemany(
            "UPDATE chunks SET sparse = $2 WHERE id = $1",
            [(r["id"], v) for r, v in zip(rows, vectors, strict=True)],
        )
    return len(rows)


async def document_id_of(conn: asyncpg.Connection, document: dict) -> str | None:
    # Looked up again rather than taken from the chunked JSON: the row may have been
    # registered (or re-registered) after chunking.
    row = await conn.fetchrow(
        "SELECT id FROM documents WHERE s3_bucket = $1 AND s3_key = $2",
        settings.s3_bucket,
        document["source"]["file"]["key"],
    )
    return str(row["id"]) if row else None


def chunk_rows(
    document: dict, vectors: np.ndarray, cfg: IndexingConfig, document_id: str, key: str, sha: str
) -> list[tuple]:
    source = document["source"]
    base_metadata = {
        **{k: source.get(k) for k in ("source_id", "title", "doi", "pmid", "pmcid")},
        "source_metadata": source.get("metadata", {}),
        "chunker_config": document["chunker"]["config_hash"],
    }
    return [
        (
            c["id"],
            document_id,
            c["index"],
            c["text"],
            c["contextual_text"],
            c["heading_path"],
            c["section_ids"],
            c["block_types"],
            c["pages"],
            c["n_tokens"],
            json.dumps({**base_metadata, "breakpoint_distance": c["breakpoint_distance"]}),
            vector,
            cfg.embeddings.model,
            key,
            sha,
            cfg.config_hash(),
        )
        for c, vector in zip(document["chunks"], vectors, strict=True)
    ]


async def run(args: argparse.Namespace) -> int:
    cfg = load_indexing_config(args.config)
    config_hash = cfg.config_hash()
    excluded = excluded_source_ids()
    keys = chunked_keys(args.prefix)
    for key in [k for k in keys if PurePosixPath(k).parts[-2] in excluded]:
        print(f"exclude {key}")
    keys = [k for k in keys if PurePosixPath(k).parts[-2] not in excluded]
    if args.only:
        keys = [k for k in keys if PurePosixPath(k).parts[-2] in args.only]
    if not keys:
        raise SystemExit(f"No chunked documents found under {args.prefix}")

    embedder = build_embedder(cfg)
    conn = await asyncpg.connect(settings.database_url)
    report = []
    try:
        await register_vector(conn)
        await check_table(conn, cfg)
        await check_sparse_column(conn)
        for key in keys:
            entry: dict = {"source_id": PurePosixPath(key).parts[-2], "key": key}
            try:
                raw = s3_get(key)
                chunked_sha = hashlib.sha256(raw).hexdigest()
                document = json.loads(raw)

                document_id = await document_id_of(conn, document)
                if document_id is None:
                    raise ValueError("no `documents` row for the raw file; run the upload first")
                entry["document_id"] = document_id

                indexed = await conn.fetch(
                    "SELECT DISTINCT chunked_sha256, index_config FROM chunks "
                    "WHERE document_id = $1",
                    document_id,
                )
                if (
                    not args.force
                    and len(indexed) == 1
                    and tuple(indexed[0]) == (chunked_sha, config_hash)
                ):
                    entry["status"] = "SKIPPED"
                    print(f"skip    {key}")
                    report.append(entry)
                    continue

                chunks = document["chunks"]
                vectors = embedder.embed([c[cfg.text_field] for c in chunks])
                if chunks and vectors.shape[1] != cfg.embeddings.dimensions:
                    raise ValueError(
                        f"{cfg.embeddings.model} returns {vectors.shape[1]}-dim vectors, "
                        f"config says {cfg.embeddings.dimensions}"
                    )
                rows = chunk_rows(document, vectors, cfg, document_id, key, chunked_sha)
                async with conn.transaction():
                    await conn.execute("DELETE FROM chunks WHERE document_id = $1", document_id)
                    await conn.executemany(INSERT_CHUNK, rows)
                    await conn.execute(
                        "UPDATE documents SET status = 'indexed', status_detail = NULL, "
                        "updated_at = now() WHERE id = $1",
                        document_id,
                    )
                entry |= {"status": "INDEXED", "chunks": len(rows)}
                print(f"indexed {key}  ({len(rows)} chunks)")
            except Exception as e:  # keep going: one bad file must not stop the run
                entry |= {"status": "FAILED", "detail": f"{type(e).__name__}: {e}"}
                print(f"FAILED  {key}: {entry['detail']}")
            report.append(entry)
        sparse_chunks = await refresh_sparse(conn, cfg)
        print(f"bm25    {sparse_chunks} chunks refitted ({cfg.sparse.model_dump()})")
    finally:
        await conn.close()

    s3_put(
        f"{args.prefix}_index_report.json",
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "config_hash": config_hash,
                "embedding_model": cfg.embeddings.model,
                "bm25": {**cfg.sparse.model_dump(), "chunks": sparse_chunks},
                "files": report,
            },
            indent=2,
        ).encode(),
        "application/json",
        {},
    )
    return sum(e["status"] == "FAILED" for e in report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("config/indexing.yaml"))
    parser.add_argument("--prefix", default="chunked/", help="key prefix of the chunked documents")
    parser.add_argument("--only", nargs="+", metavar="ID", help="only these source ids")
    parser.add_argument("--force", action="store_true", help="re-index documents already indexed")
    args = parser.parse_args()
    raise SystemExit(1 if asyncio.run(run(args)) else 0)


if __name__ == "__main__":
    main()
