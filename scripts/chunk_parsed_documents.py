"""Chunk the parsed documents in the S3 (MinIO) documents bucket into retrieval-sized chunks.

Usage: python scripts/chunk_parsed_documents.py [--config config/chunking.yaml]
                                                [--prefix parsed/] [--out-prefix chunked/]
                                                [--only ID ...] [--force]

Reads s3://$S3_BUCKET/parsed/<source_id>/<stem>.json (as written by parse_raw_documents.py) and
writes chunked/<source_id>/<stem>.json (chunks with their heading path, sections, pages and
token counts) and chunked/<source_id>/<stem>.md (a viewable rendering for tuning). The method
and its hyperparameters come from the chunking config; documents whose source role is listed
under `documents.skip_roles` or whose source id is under `excluded:` in the manifest are not
chunked.

Output objects carry the parsed sha256 and the config hash as user metadata, so unchanged
documents are skipped unless --force is given. A per-file report is written to
chunked/_chunk_report.json. The Postgres `documents` table is only read (for the document id).
"""

import argparse
import asyncio
import hashlib
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import asyncpg

from app.chunking import Chunk, ChunkingConfig, build_chunker, load_chunking_config
from app.settings import settings
from app.sources import excluded_source_ids
from app.storage import s3_get, s3_head, s3_list_keys, s3_put

SCHEMA_VERSION = 1


def parsed_keys(prefix: str) -> list[str]:
    """parsed/<source_id>/<stem>.json keys (not the report at the top level)."""
    return sorted(
        k
        for k in s3_list_keys(prefix)
        if k.endswith(".json") and len(PurePosixPath(k[len(prefix) :]).parts) == 2
    )


def chunk_markdown(document: dict, chunks: list[Chunk]) -> str:
    source = document["source"]
    out = [f"# {source['title'] or source['source_id']}", ""]
    for c in chunks:
        path = " > ".join(c.heading_path) or "(no heading)"
        pages = f", p. {c.pages[0]}-{c.pages[-1]}" if c.pages else ""
        out += [f"## Chunk {c.index + 1} · {path} · {c.n_tokens} tokens{pages}", "", c.text, ""]
        out += ["---", ""]
    return "\n".join(out)


def chunk_document(
    document: dict, chunks: list[Chunk], cfg: ChunkingConfig, document_id: str | None, key: str
) -> dict:
    stem = f"{document['source']['source_id']}/{PurePosixPath(key).stem}"
    out = {
        "schema_version": SCHEMA_VERSION,
        "chunker": {
            "method": cfg.method,
            "config": cfg.method_config().model_dump(mode="json"),
            "embeddings": cfg.embeddings.model_dump(mode="json"),
            "tokenizer": cfg.tokenizer,
            "config_hash": cfg.config_hash(),
            "chunked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "document_id": document_id,
        "parsed_key": key,
        "source": document["source"],
        "document": document["document"],
        "chunks": [
            {
                "id": f"{stem}#{c.index + 1:04d}",
                "index": c.index,
                "text": c.text,
                "contextual_text": c.contextual_text,
                "heading_path": c.heading_path,
                "section_ids": c.section_ids,
                "block_types": c.block_types,
                "pages": c.pages,
                "n_tokens": c.n_tokens,
                "n_units": c.n_units,
                "breakpoint_distance": c.breakpoint_distance,
            }
            for c in chunks
        ],
    }
    if "icd" in document:
        out["icd"] = document["icd"]
    return out


async def document_id_of(conn: asyncpg.Connection, raw_key: str) -> str | None:
    row = await conn.fetchrow(
        "SELECT id FROM documents WHERE s3_bucket = $1 AND s3_key = $2", settings.s3_bucket, raw_key
    )
    return str(row["id"]) if row else None


async def run(args: argparse.Namespace) -> int:
    cfg = load_chunking_config(args.config)
    config_hash = cfg.config_hash()
    excluded = excluded_source_ids()
    keys = parsed_keys(args.prefix)
    if args.only:
        keys = [k for k in keys if PurePosixPath(k).parts[-2] in args.only]
    if not keys:
        raise SystemExit(f"No parsed documents found under {args.prefix}")

    chunker = build_chunker(cfg)
    conn = await asyncpg.connect(settings.database_url)
    report = []
    try:
        for key in keys:
            out_base = args.out_prefix + key[len(args.prefix) :].removesuffix(".json")
            entry = {"source_id": PurePosixPath(key).parts[-2], "key": out_base + ".json"}
            try:
                raw = s3_get(key)
                parsed_sha = hashlib.sha256(raw).hexdigest()
                document = json.loads(raw)

                if (
                    document["source"]["source_id"] in excluded
                    or document["source"]["metadata"].get("role") in cfg.documents.skip_roles
                ):
                    entry["status"] = "EXCLUDED"
                    print(f"exclude {key}")
                    report.append(entry)
                    continue

                head = s3_head(out_base + ".json")
                if (
                    not args.force
                    and head
                    and head["Metadata"].get("parsed-sha256") == parsed_sha
                    and head["Metadata"].get("chunker-config") == config_hash
                ):
                    entry["status"] = "SKIPPED"
                    print(f"skip    {out_base}")
                    report.append(entry)
                    continue

                chunks = chunker.chunk(document)
                document_id = await document_id_of(conn, document["source"]["file"]["key"])
                result = chunk_document(document, chunks, cfg, document_id, key)
                metadata = {
                    "parsed-sha256": parsed_sha,
                    "parsed-key": key,
                    "chunker-config": config_hash,
                }
                s3_put(
                    out_base + ".md",
                    chunk_markdown(document, chunks).encode(),
                    "text/markdown; charset=utf-8",
                    metadata,
                )
                # JSON last: its metadata is what the skip check reads.
                s3_put(
                    out_base + ".json",
                    json.dumps(result, ensure_ascii=False, indent=2).encode(),
                    "application/json",
                    metadata,
                )
                sizes = [c.n_tokens for c in chunks] or [0]
                entry |= {
                    "status": "CHUNKED",
                    "chunks": len(chunks),
                    "tokens": {
                        "min": min(sizes),
                        "p50": int(statistics.median(sizes)),
                        "max": max(sizes),
                    },
                    "document_id": document_id,
                }
                print(f"chunked {out_base}  ({len(chunks)} chunks, tokens {entry['tokens']})")
            except Exception as e:  # keep going: one bad file must not stop the run
                entry |= {"status": "FAILED", "detail": f"{type(e).__name__}: {e}"}
                print(f"FAILED  {key}: {entry['detail']}")
            report.append(entry)
    finally:
        await conn.close()

    s3_put(
        f"{args.out_prefix}_chunk_report.json",
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "config_hash": config_hash,
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
    parser.add_argument("--config", type=Path, default=Path("config/chunking.yaml"))
    parser.add_argument("--prefix", default="parsed/", help="key prefix of the parsed documents")
    parser.add_argument("--out-prefix", default="chunked/", help="key prefix for the output")
    parser.add_argument("--only", nargs="+", metavar="ID", help="only these source ids")
    parser.add_argument("--force", action="store_true", help="re-chunk documents already chunked")
    args = parser.parse_args()
    raise SystemExit(1 if asyncio.run(run(args)) else 0)


if __name__ == "__main__":
    main()
