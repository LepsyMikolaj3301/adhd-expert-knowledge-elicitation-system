# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "beautifulsoup4", "lxml"]
# ///
"""Scrape Wikipedia articles via the REST API and split them into sections.

Usage: uv run scripts/scrape_wikipedia.py [out_dir]   (default: data/raw)
"""

import json
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

REST_URL = "https://en.wikipedia.org/api/rest_v1/page/html/{topic}"
USER_AGENT = "rag-poc/0.1 (mikolaj.lepsy@gmail.com)"
TOPICS = ["Procrastination", "Executive_functions"]
# Non-prose elements to drop before extracting text
NOISE = "style, sup.mw-ref, .mw-empty-elt, [role=note], .hatnote, .reflist, .navbox, .mw-editsection"
SKIP_SECTIONS = {
    "References",
    "External links",
    "Further reading",
    "See also",
    "Notes",
    "Sources",
}
HEADINGS = {"h2": "##", "h3": "###", "h4": "####", "h5": "#####"}


def fetch_html(client: httpx.Client, topic: str) -> str:
    resp = client.get(REST_URL.format(topic=topic))
    resp.raise_for_status()
    return resp.text


def _text(el: Tag) -> str:
    return re.sub(r"\s+", " ", el.get_text()).strip()


def _render(el: Tag) -> str:
    """Render a block element as plain text / light markdown."""
    if el.name in ("ul", "ol"):
        return "\n".join(f"- {_text(li)}" for li in el.find_all("li") if _text(li))
    if el.name == "dl":
        return "\n".join(_text(x) for x in el.find_all(["dt", "dd"]) if _text(x))
    if el.name == "table":
        rows = [
            " | ".join(_text(c) for c in r.find_all(["th", "td"]))
            for r in el.find_all("tr")
        ]
        return "\n".join(r for r in rows if r.strip(" |"))
    return _text(el)


def parse_sections(topic: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    for junk in soup.select(NOISE):
        junk.decompose()
    title = soup.title.get_text() if soup.title else topic
    sections = []
    for sec in soup.find_all("section", attrs={"data-mw-section-id": True}):
        heading = sec.find(list(HEADINGS), recursive=False)
        name = _text(heading) if heading else "Lead"
        if name in SKIP_SECTIONS:
            continue
        level = HEADINGS.get(heading.name, "##") if heading else ""
        blocks = sec.find_all(
            ["p", "ul", "ol", "dl", "blockquote", "table"], recursive=False
        )
        text = "\n\n".join(t for t in (_render(b) for b in blocks) if t)
        if text:
            anchor = f"#{heading['id']}" if heading and heading.get("id") else ""
            sections.append(
                {
                    "topic": topic,
                    "title": title,
                    "section": name,
                    "level": level,
                    "section_id": int(sec["data-mw-section-id"]),
                    "url": f"https://en.wikipedia.org/wiki/{topic}{anchor}",
                    "text": text,
                }
            )
    return sections


def to_markdown(sections: list[dict]) -> str:
    parts = [f"# {sections[0]['title']}"]
    for s in sections:
        if s["level"]:
            parts.append(f"{s['level']} {s['section']}")
        parts.append(s["text"])
    return "\n\n".join(parts) + "\n"


def main(out_dir: str = "data/raw") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        for topic in TOPICS:
            sections = parse_sections(topic, fetch_html(client, topic))
            path = out / f"{topic}.json"
            path.write_text(json.dumps(sections, indent=2, ensure_ascii=False))
            (out / f"{topic}.md").write_text(to_markdown(sections))
            chars = sum(len(s["text"]) for s in sections)
            print(f"{topic}: {len(sections)} sections, {chars} chars -> {path} (+ .md)")


if __name__ == "__main__":
    main(*sys.argv[1:])
