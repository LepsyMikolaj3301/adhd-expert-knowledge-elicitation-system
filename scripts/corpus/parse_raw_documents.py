"""Parse the raw documents in the S3 (MinIO) documents bucket into structured JSON + Markdown.

Usage: python scripts/corpus/parse_raw_documents.py [--prefix raw/] [--out-prefix parsed/]
                                             [--only ID ...] [--force]

Reads s3://$S3_BUCKET/raw/<source_id>/ (as uploaded by upload_raw_documents.py) and writes, for
every file described by a meta.json, parsed/<source_id>/<stem>.json (normalized sections/blocks,
for chunking and claim extraction) and parsed/<source_id>/<stem>.md (a viewable rendering).
Files without a meta.json (the loose PDFs at raw/ top level) are ignored.

HTML, JATS XML and PDF go through Docling; ICD-API JSON is parsed deterministically. Output
objects carry the raw sha256 and PARSER_VERSION as user metadata, so unchanged files are skipped
unless --force is given. The `documents` row of each file is moved to parsed / failed, and a
per-file report is written to parsed/_parse_report.json.
"""

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlparse

import asyncpg
import pypdfium2
import yaml
from bs4 import BeautifulSoup
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import (
    DoclingDocument,
    InlineGroup,
    ListItem,
    SectionHeaderItem,
    TableItem,
    TitleItem,
)
from lxml import etree

from app.settings import settings
from app.sources import excluded_source_ids
from app.storage import get_s3_client, s3_get, s3_head, s3_put

PARSER_VERSION = "3"
SCHEMA_VERSION = 1

# Only this section of these PDFs is parsed: source_id -> title of its PDF outline bookmark.
# TODO: this is still a problem for big documents of which we only want one section. It relies on
# the PDF having an outline and on a hardcoded section title per source; there is no general way
# yet to say "read only the part about X" (scanned PDFs, no outline, section spread over pages).
PDF_SECTIONS: dict[str, str] = {}

# Docling only treats XML as JATS when the DOCTYPE says so; PMC / Europe PMC files have none.
JATS_DOCTYPE = (
    '<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange '
    'DTD v1.3 20210610//EN" "JATS-archive-oasis-article1.dtd">'
)

# (host suffix -> CSS selectors of the article content) for pages saved with their site chrome.
HTML_CONTENT = {
    "cambridge.org": ["div.article-abstract", "div.article.research-article"],
    "nice.org.uk": [".chapter", "main"],
}
HTML_JUNK = (
    "script, style, nav, header, footer, form, button, #references-list, .apl-platform-header, "
    ".show-for-sr"  # screen-reader text, e.g. "Reference Smith and Jones" inside citation links
)
# Inline tags unwrapped before Docling, which splits a paragraph into one text item per styled or
# linked run and drops the whitespace between them (citations would become separate blocks).
HTML_INLINE = "a, span, i, em, b, strong, u, sup, sub, small"
JATS_INLINE = (
    "italic",
    "bold",
    "underline",
    "sup",
    "sub",
    "sc",
    "xref",
    "ext-link",
    "named-content",
    "styled-content",
)
# Author / affiliation front matter and back matter of JATS articles: not retrieval content.
JATS_JUNK = (
    "front/article-meta/contrib-group",
    "front/article-meta/aff",
    "front/article-meta/author-notes",
    "front/notes",
    ".//ref-list",
    ".//ack",
    ".//bio",
)
# Sections dropped by heading (and everything under them), whatever the input format. Matched
# against the heading without its leading numbering and trailing colon.
BOILERPLATE_HEADINGS = re.compile(
    r"references?|bibliography|acknowledge?ments?|conflicts? of interests?"
    r"|competing interests?|declarations? of (competing )?interests?|(financial )?disclosures?"
    r"|funding( statement| sources| information)?|authors?'? contributions?|contributors"
    r"|author biograph(y|ies)|about the authors?|supplementa(ry|l) materials?|associated data"
    r"|data availability( statement)?|ethics( statement| approval)?|your responsibility",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- S3 helpers


def list_source_ids(prefix: str) -> list[str]:
    ids = set()
    paginator = get_s3_client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            parts = PurePosixPath(obj["Key"][len(prefix) :]).parts
            if len(parts) == 2 and parts[1] == "meta.json":
                ids.add(parts[0])
    return sorted(ids)


# --------------------------------------------------------------------------- input preparation


def clean_html(raw: bytes, final_url: str | None) -> bytes:
    """Cut a saved web page down to its article content (login alerts, menus, references out)."""
    soup = BeautifulSoup(raw, "lxml")
    host = urlparse(final_url or "").hostname or ""
    selectors = next((s for suffix, s in HTML_CONTENT.items() if host.endswith(suffix)), ["main"])
    parts = [el for sel in selectors if (el := soup.select_one(sel))]
    # Nested hits (e.g. .chapter inside main) would duplicate text: keep the first only for those.
    if len(parts) > 1 and any(a in b.descendants for a in parts for b in parts if a is not b):
        parts = parts[:1]
    body = soup.new_tag("body")
    for el in parts or [soup.body or soup]:
        el.extract()
        for junk in el.select(HTML_JUNK):
            junk.decompose()
        for block in el.select("p, li"):
            for tag in block.select(HTML_INLINE):
                tag.unwrap()
            block.smooth()
        body.append(el)
    title = soup.title.get_text(strip=True) if soup.title else ""
    html = f"<html><head><title>{title}</title></head>{body}</html>"
    return html.encode()


def prepare_jats(raw: bytes) -> bytes:
    """Extract the <article> from an efetch / Europe PMC response and add a JATS DOCTYPE."""
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True
    )
    root = etree.fromstring(raw, parser)
    article = root if etree.QName(root).localname == "article" else root.find(".//article")
    if article is None:
        raise ValueError("no <article> element in XML")
    for path in JATS_JUNK:
        for el in article.findall(path):
            el.getparent().remove(el)
    etree.strip_tags(article, *JATS_INLINE)
    body = etree.tostring(article, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{JATS_DOCTYPE}\n{body}'.encode()


def pdf_section_pages(pdf: bytes, title: str) -> tuple[int, int]:
    """1-based inclusive page range of the outline bookmark `title`, up to and including the page
    of the next bookmark of the same or a higher level. Sections start mid-page, so the first and
    last page are shared with the neighbouring sections and their text is included too."""
    doc = pypdfium2.PdfDocument(pdf)
    marks = [(b.level, b.get_title().strip(), b.get_dest()) for b in doc.get_toc(max_depth=6)]
    for i, (level, name, dest) in enumerate(marks):
        if name == title and dest is not None:
            start = dest.get_index()
            end = len(doc) - 1
            for next_level, _, next_dest in marks[i + 1 :]:
                if next_level <= level and next_dest is not None:
                    end = max(start, next_dest.get_index())
                    break
            return start + 1, end + 1
    raise ValueError(f"no PDF bookmark titled {title!r}")


# --------------------------------------------------------------------------- Docling


_converter: DocumentConverter | None = None


def converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        # OCR only touches bitmap regions; embedded text is kept as is (no force_full_page_ocr,
        # which would replace exact text with recognized text). Accelerator defaults to auto/GPU.
        pdf_options = PdfPipelineOptions(do_ocr=True, do_table_structure=True)
        _converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)}
        )
    return _converter


def docling_to_sections(doc: DoclingDocument) -> list[dict]:
    """Flatten the document into sections, each with its heading path and its blocks."""
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []

    def start(heading: str | None, level: int) -> dict:
        if heading is not None:
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
        section = {
            "id": f"s{len(sections) + 1}",
            "heading": heading,
            "level": level,
            "path": [h for _, h in stack],
            "blocks": [],
        }
        sections.append(section)
        return section

    current = start(None, 0)
    merged: set[str] = set()  # self_refs of items already emitted as part of an inline group
    for item, _level in doc.iterate_items(with_groups=True):
        if item.self_ref in merged:
            continue
        if isinstance(item, InlineGroup):
            # Fallback for inputs not flattened beforehand (PDF): one block per inline group.
            runs = [c for c, _ in doc.iterate_items(root=item) if getattr(c, "text", None)]
            merged.update(c.self_ref for c in runs)
            if runs:
                parent = item.parent.resolve(doc) if item.parent else None
                kind = "list_item" if isinstance(parent, ListItem) else "paragraph"
                text = " ".join(c.text for c in runs)
                current["blocks"].append({"type": kind, "text": text, "page": page_of(runs[0])})
        elif isinstance(item, TitleItem):
            current = start(item.text, 1)
        elif isinstance(item, SectionHeaderItem):
            current = start(item.text, item.level + 1)
        elif isinstance(item, TableItem):
            rows = [[str(c) for c in row] for row in item.export_to_dataframe(doc).values.tolist()]
            block = {"type": "table", "text": item.export_to_markdown(doc), "rows": rows}
            current["blocks"].append(block | {"page": page_of(item)})
        elif getattr(item, "text", None):
            kind = "list_item" if isinstance(item, ListItem) else str(item.label.value)
            kind = {"text": "paragraph"}.get(kind, kind)
            current["blocks"].append({"type": kind, "text": item.text, "page": page_of(item)})
    return [s for s in sections if s["heading"] is not None or s["blocks"]]


def drop_boilerplate(sections: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split off sections with a boilerplate heading anywhere in their path (references,
    acknowledgements, disclosures...) and renumber the rest."""

    def boilerplate(heading: str) -> bool:
        heading = re.sub(r"^[\d.\s]+", "", heading).rstrip(" :")
        return bool(BOILERPLATE_HEADINGS.fullmatch(heading))

    kept, dropped = [], []
    for section in sections:
        if any(boilerplate(h) for h in section["path"]):
            words = sum(len(b["text"].split()) for b in section["blocks"])
            dropped.append({"heading": section["heading"], "path": section["path"], "words": words})
        else:
            kept.append(section)
    return [{**s, "id": f"s{i}"} for i, s in enumerate(kept, 1)], dropped


def sections_markdown(title: str, sections: list[dict]) -> str:
    out = [f"# {title}", ""] if title else []
    for section in sections:
        if section["heading"]:
            out += ["#" * min(section["level"] + 1, 6) + " " + section["heading"], ""]
        for block in section["blocks"]:
            prefix = "- " if block["type"] == "list_item" else ""
            out += [prefix + block["text"], ""]
    return "\n".join(out)


def page_of(item) -> int | None:
    return item.prov[0].page_no if getattr(item, "prov", None) else None


def parse_docling(raw: bytes, name: str, source_id: str) -> tuple[dict, str]:
    page_range = None
    kwargs = {}
    if name.endswith(".pdf") and source_id in PDF_SECTIONS:
        page_range = pdf_section_pages(raw, PDF_SECTIONS[source_id])
        kwargs["page_range"] = page_range
    result = converter().convert(DocumentStream(name=name, stream=BytesIO(raw)), **kwargs)
    doc = result.document
    sections, dropped = drop_boilerplate(docling_to_sections(doc))
    parsed = {
        "parser": {"name": "docling"},
        "document": {"title": doc.name, "page_range": list(page_range) if page_range else None},
        "sections": sections,
        "dropped_sections": dropped,
    }
    return parsed, sections_markdown("", sections)


# --------------------------------------------------------------------------- ICD-API JSON


def lang_value(value: object) -> str:
    """ICD strings arrive as plain strings or {"@language", "@value"} objects."""
    if isinstance(value, dict):
        value = value.get("@value", "")
    return value if isinstance(value, str) else ""


def labels(entries: list[dict] | None) -> list[str]:
    return [lang_value(e.get("label")) for e in entries or []]


def split_markdown_sections(markdown: str) -> list[dict]:
    """Split diagnostic-criteria Markdown on its ##/### headings (text before the first one gets
    a heading-less section)."""
    markdown = markdown.removeprefix("!markdown").strip()
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []
    heading, level, lines = None, 0, []

    def flush() -> None:
        blocks = [
            {
                "type": "list_item" if line.startswith("- ") else "paragraph",
                "text": line.removeprefix("- ").strip(),
                "page": None,
            }
            for line in lines
            if line.strip()
        ]
        if heading is not None or blocks:
            sections.append(
                {
                    "id": f"s{len(sections) + 1}",
                    "heading": heading,
                    "level": level,
                    "path": [h for _, h in stack],
                    "blocks": blocks,
                }
            )

    for line in markdown.splitlines():
        if m := re.match(r"(#{1,6})\s+(.*?):?\s*$", line):
            flush()
            lines = []
            level, heading = len(m[1]), m[2]
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
        else:
            lines.append(line)
    flush()
    return sections


def icd_entity_files(meta: dict) -> dict[str, dict]:
    """name -> JSON for the entity files of an ICD source (releases/codeinfo are lookups)."""
    return {
        f["name"]: json.loads(s3_get(f["key"]))
        for f in meta["files"]
        if f["name"] not in ("releases.json", "codeinfo.json")
    }


def parse_icd(entity: dict, siblings: dict[str, dict], release: str | None) -> tuple[dict, str]:
    by_uri = {e["@id"].replace("http://", "https://"): e for e in siblings.values() if "@id" in e}

    def ref(uri: str) -> dict:
        e = by_uri.get(uri.replace("http://", "https://"), {})
        return {"uri": uri, "code": e.get("code"), "title": lang_value(e.get("title")) or None}

    title = lang_value(entity.get("title"))
    criteria = lang_value(entity.get("diagnosticCriteria"))
    icd = {
        "code": entity.get("code"),
        "uri": entity.get("@id"),
        "foundation_uri": entity.get("source"),
        "class_kind": entity.get("classKind"),
        "browser_url": entity.get("browserUrl"),
        "release": release,
        "definition": lang_value(entity.get("definition")) or None,
        "inclusions": labels(entity.get("inclusion")),
        "exclusions": labels(entity.get("exclusion")),
        "synonyms": labels(entity.get("synonym")) or labels(entity.get("indexTerm")),
        "parents": [ref(u) for u in entity.get("parent", [])],
        "children": [ref(u) for u in entity.get("child", [])],
    }
    sections = icd_sections(title, icd, criteria)
    parsed = {
        "parser": {"name": "icd"},
        "document": {"title": title, "page_range": None},
        "sections": sections,
        "icd": icd,
    }
    return parsed, icd_markdown(title, icd, criteria)


def icd_sections(title: str, icd: dict, criteria: str) -> list[dict]:
    """The structured fields and the diagnostic criteria as sections, all under one root heading
    ("<code> <title>") so every chunk keeps the entity it came from."""
    root = f"{icd['code']} {title}" if icd["code"] else title
    # Children not among the fetched entities (all of them for the Foundation) are bare URIs.
    subcategories = [
        f"{c['code'] or ''} {c['title']}".strip() for c in icd["children"] if c["title"]
    ]
    fields = [
        ("Definition", "paragraph", [icd["definition"]] if icd["definition"] else []),
        ("Inclusions", "list_item", icd["inclusions"]),
        ("Exclusions", "list_item", icd["exclusions"]),
        ("Synonyms", "list_item", icd["synonyms"]),
        ("Subcategories", "list_item", subcategories),
    ]
    sections = [
        {
            "heading": heading,
            "level": 2,
            "path": [root, heading],
            "blocks": [{"type": kind, "text": text, "page": None} for text in texts],
        }
        for heading, kind, texts in fields
        if texts
    ]
    if criteria:
        sections += [
            {
                "heading": s["heading"],
                "level": s["level"],
                "path": [root, *s["path"]],
                "blocks": s["blocks"],
            }
            for s in split_markdown_sections(criteria)
        ]
    # Renumbered: the criteria sections come with ids of their own, starting at s1.
    return [{"id": f"s{i}", **s} for i, s in enumerate(sections, 1)]


def icd_markdown(title: str, icd: dict, criteria: str) -> str:
    out = [f"# {icd['code'] + ' ' if icd['code'] else ''}{title}", ""]
    if icd["definition"]:
        out += ["## Definition", "", icd["definition"], ""]
    for heading, key in (
        ("Inclusions", "inclusions"),
        ("Exclusions", "exclusions"),
        ("Synonyms", "synonyms"),
    ):
        if icd[key]:
            out += [f"## {heading}", "", *[f"- {x}" for x in icd[key]], ""]
    if icd["children"]:
        out += ["## Subcategories", ""]
        out += [f"- {c['code'] or c['uri']} {c['title'] or ''}".rstrip() for c in icd["children"]]
        out.append("")
    if criteria:
        out += ["## Diagnostic criteria", "", criteria.removeprefix("!markdown").strip(), ""]
    return "\n".join(out)


# --------------------------------------------------------------------------- assembly


def front_matter(source: dict, file: dict, page_range: list[int] | None) -> str:
    meta = source["metadata"]
    data = {
        "source_id": source["source_id"],
        "title": source["title"],
        "doi": source.get("doi"),
        "citation": meta.get("citation"),
        "licence": meta.get("licence"),
        "raw_key": file["key"],
        "sha256": file["sha256"],
        "page_range": page_range,
    }
    data = {k: v for k, v in data.items() if v is not None}
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True) + "---\n\n"


def parse_file(meta: dict, record: dict, raw: bytes) -> tuple[dict, str]:
    name = record["name"]
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == ".json":
        entities = icd_entity_files(meta)
        parsed, markdown = parse_icd(entities[name], entities, meta.get("release_or_version"))
    elif suffix == ".html":
        parsed, markdown = parse_docling(
            clean_html(raw, record.get("final_url")), name, meta["source_id"]
        )
    elif suffix == ".xml":
        parsed, markdown = parse_docling(prepare_jats(raw), name, meta["source_id"])
    elif suffix == ".pdf":
        parsed, markdown = parse_docling(raw, name, meta["source_id"])
    else:
        raise ValueError(f"unsupported file type {suffix}")

    file = {
        "key": record["key"],
        "sha256": record["sha256"],
        **{k: record.get(k) for k in ("url", "final_url", "retrieved_at", "content_type")},
    }
    source = {
        **{k: meta.get(k) for k in ("source_id", "title", "doi", "pmid", "pmcid")},
        "release_or_version": meta.get("release_or_version"),
        "metadata": meta.get("metadata", {}),
        "file": file,
    }
    document = {
        "schema_version": SCHEMA_VERSION,
        "parser": {
            **parsed.pop("parser"),
            "version": PARSER_VERSION,
            "parsed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "source": source,
        **parsed,
    }
    markdown = front_matter(source, file, document["document"]["page_range"]) + markdown
    return document, markdown


async def set_status(conn: asyncpg.Connection, key: str, status: str, detail: str | None) -> None:
    await conn.execute(
        "UPDATE documents SET status = $3, status_detail = $4, updated_at = now() "
        "WHERE s3_bucket = $1 AND s3_key = $2",
        settings.s3_bucket,
        key,
        status,
        detail,
    )


async def run(args: argparse.Namespace) -> int:
    excluded = excluded_source_ids()
    source_ids = list_source_ids(args.prefix)
    for source_id in sorted(excluded & set(source_ids)):
        print(f"exclude {args.prefix}{source_id}/")
    source_ids = [s for s in source_ids if s not in excluded]
    if args.only:
        source_ids = [s for s in source_ids if s in args.only]
    if not source_ids:
        raise SystemExit(f"No sources with a meta.json found under {args.prefix}")

    conn = await asyncpg.connect(settings.database_url)
    report = []
    try:
        for source_id in source_ids:
            meta = json.loads(s3_get(f"{args.prefix}{source_id}/meta.json"))
            # Metadata files of ICD sources are lookups, not documents.
            records = [
                {**r, "key": f"{args.prefix}{source_id}/{r['name']}"}
                for r in meta["files"]
                if r["name"] not in ("releases.json", "codeinfo.json")
            ]
            meta["files"] = [
                {**r, "key": f"{args.prefix}{source_id}/{r['name']}"} for r in meta["files"]
            ]
            for record in records:
                out_base = f"{args.out_prefix}{source_id}/{PurePosixPath(record['name']).stem}"
                entry = {"source_id": source_id, "file": record["name"], "key": out_base + ".json"}
                try:
                    head = s3_head(out_base + ".json")
                    if (
                        not args.force
                        and head
                        and head["Metadata"].get("source-sha256") == record["sha256"]
                        and head["Metadata"].get("parser-version") == PARSER_VERSION
                    ):
                        entry["status"] = "SKIPPED"
                        print(f"skip    {out_base}")
                        report.append(entry)
                        continue

                    await set_status(conn, record["key"], "parsing", None)
                    raw = s3_get(record["key"])
                    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                        raise ValueError("raw object does not match the sha256 in its meta.json")
                    document, markdown = parse_file(meta, record, raw)
                    metadata = {
                        "source-sha256": record["sha256"],
                        "source-key": record["key"],
                        "parser-version": PARSER_VERSION,
                    }
                    s3_put(
                        out_base + ".md",
                        markdown.encode(),
                        "text/markdown; charset=utf-8",
                        metadata,
                    )
                    # JSON last: its metadata is what the skip check reads.
                    s3_put(
                        out_base + ".json",
                        json.dumps(document, ensure_ascii=False, indent=2).encode(),
                        "application/json",
                        metadata,
                    )
                    await set_status(conn, record["key"], "parsed", out_base + ".json")
                    entry["status"] = "PARSED"
                    dropped = len(document.get("dropped_sections", []))
                    entry["dropped_sections"] = dropped
                    print(
                        f"parsed  {out_base}  ({len(document['sections'])} sections, "
                        f"{dropped} dropped)"
                    )
                except Exception as e:  # keep going: one bad file must not stop the run
                    entry |= {"status": "FAILED", "detail": f"{type(e).__name__}: {e}"}
                    print(f"FAILED  {record['key']}: {entry['detail']}")
                    await set_status(conn, record["key"], "failed", entry["detail"][:500])
                report.append(entry)
    finally:
        await conn.close()

    s3_put(
        f"{args.out_prefix}_parse_report.json",
        json.dumps(
            {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "files": report},
            indent=2,
        ).encode(),
        "application/json",
        {},
    )
    return sum(e["status"] == "FAILED" for e in report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", default="raw/", help="key prefix of the raw documents")
    parser.add_argument("--out-prefix", default="parsed/", help="key prefix for the output")
    parser.add_argument("--only", nargs="+", metavar="ID", help="only these source ids")
    parser.add_argument("--force", action="store_true", help="re-parse files already parsed")
    args = parser.parse_args()
    raise SystemExit(1 if asyncio.run(run(args)) else 0)


if __name__ == "__main__":
    main()
