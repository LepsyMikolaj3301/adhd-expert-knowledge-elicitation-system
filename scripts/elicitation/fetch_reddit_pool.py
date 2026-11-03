"""Download a public r/ADHD post dump as the pool of make_fixtures.py --source reddit.

Usage: python -I scripts/elicitation/fetch_reddit_pool.py [--csv data/raw/reddit/adhd.csv]
                                                           [--out data/raw/reddit_adhd.jsonl]

Source: Hugging Face dataset solomonk/reddit_mental_health_posts, file adhd.csv (r/ADHD posts:
id, title, body, ...). The card states no license and Reddit's API terms apply, so the text stays
in data/ (gitignored) and nothing here is committed. The downloaded CSV is untrusted data: it is
only parsed with `csv`, never executed.

Writes one JSON per line: {id, title, body, label: "adhd"}. [removed]/[deleted]/empty bodies are
dropped. Cleaning (leak terms, URLs, word limits) is done later by reddit_posts.clean_post.
"""

import argparse
import csv
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
URL = "https://huggingface.co/datasets/solomonk/reddit_mental_health_posts/resolve/main/adhd.csv"
DEAD = {"", "[removed]", "[deleted]"}


def convert(csv_path: Path, out: Path) -> tuple[int, int]:
    """(rows read, posts written)."""
    csv.field_size_limit(sys.maxsize)
    rows = kept = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open(newline="", encoding="utf-8") as f, out.open("w", encoding="utf-8") as w:
        for row in csv.DictReader(f):
            rows += 1
            body = (row.get("body") or "").strip()
            if body in DEAD or not row.get("id"):
                continue
            post = dict(id=row["id"], title=(row.get("title") or "").strip(), body=body)
            w.write(json.dumps({**post, "label": "adhd"}, ensure_ascii=False) + "\n")
            kept += 1
    return rows, kept


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--csv", type=Path, default=ROOT / "data/raw/reddit/adhd.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "data/raw/reddit_adhd.jsonl")
    ap.add_argument("--url", default=URL)
    args = ap.parse_args(argv)
    if not args.csv.exists():
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {args.url}", file=sys.stderr)
        urllib.request.urlretrieve(args.url, args.csv)  # noqa: S310 (fixed https URL)
    rows, kept = convert(args.csv, args.out)
    print(f"{rows} rows -> {kept} posts in {args.out}\nsource: {args.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
