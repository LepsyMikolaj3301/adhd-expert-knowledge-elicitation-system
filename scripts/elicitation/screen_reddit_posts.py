"""Label cleaned r/ADHD posts with a local model and shortlist the good test texts.

Usage: python scripts/elicitation/screen_reddit_posts.py [--n 300] [--model qwen3.5:9b]
                                                         [--min-fit 4] [--seed 1]

Reads the pool (fetch_reddit_pool.py), cleans every post like make_fixtures does (reddit_posts.
clean_post), drops what is obviously advice or about someone else, and asks the model about a
random sample of --n posts (prompt Reddit_post_screen.v1). Wanted: a person's own account that
shows an everyday difficulty without naming it, so a clinician has to weigh other explanations.

Writes data/raw/reddit_screened.jsonl (every labelled post: id, text, screen) and
data/raw/reddit_shortlist.jsonl (own accounts with fit >= --min-fit, in pool format so it can be
passed as --reddit-pool). Resumable: ids already in the screened file are skipped, and model
replies are cached. The labels only select texts; they are never reference answers.
"""

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

from llm_clients import CachedGenerator, Generator, GenRequest, ModelRefused, OllamaGenerator
from make_fixtures import Rejected, parse_json
from prompt_loader import load_prompt
from reddit_posts import TRAIT_LEXICON, load_pool

ROOT = Path(__file__).resolve().parents[2]
PROMPT = "Reddit_post_screen.v1"
KINDS = {
    "own_struggle",
    "seeking_assessment",
    "advice_or_tips",
    "about_someone_else",
    "question_only",
    "other",
}
OWN_KINDS = {"own_struggle", "seeking_assessment"}
TRAITS = set(TRAIT_LEXICON) | {"none"}
OPTIONS = {"temperature": 0.2, "num_predict": 300, "num_ctx": 4096}

# Cheap pre-filter so the GPU is not spent on posts that are plainly not a person's own account.
OTHER_PERSON = re.compile(
    r"\bmy (son|daughter|kid|kids|child|children|husband|wife|boyfriend|girlfriend|partner|"
    r"brother|sister|mom|dad|friend|student|boss)\b",
    re.IGNORECASE,
)
ADVICE = re.compile(
    r"\b(tips|advice|recommend\w*|how do (you|i)|what (do|are) you|does anyone|anyone else|"
    r"do you guys|any suggestions|resources?|apps?|hacks?|megathread)\b",
    re.IGNORECASE,
)


def prefilter(text: str, title: str) -> bool:
    return not (OTHER_PERSON.search(text) or ADVICE.search(title))


def check_screen(raw: str) -> dict:
    data = parse_json(raw)
    if data.get("kind") not in KINDS:
        raise Rejected(f"kind {data.get('kind')!r} is not one of {sorted(KINDS)}")
    if data.get("trait") not in TRAITS:
        raise Rejected(f"trait {data.get('trait')!r} is not one of {sorted(TRAITS)}")
    for name, low, high in (("episodes", 0, 5), ("subtlety", 1, 3), ("fit", 1, 5)):
        value = data.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise Rejected(f"{name} must be an integer {low}..{high}, got {value!r}")
    if not isinstance(data.get("reason"), str) or not data["reason"].strip():
        raise Rejected("reason is missing")
    return {k: data[k] for k in ("kind", "episodes", "subtlety", "trait", "fit", "reason")}


def screen_post(gen: Generator, pid: str, text: str, seed: int, retries: int) -> dict | None:
    prompt = load_prompt(PROMPT).fill(POST_TEXT=text)
    for attempt in range(retries + 1):
        req = GenRequest(
            key=f"screen:{pid}",
            system=prompt.system,
            user=prompt.user,
            json_mode=True,
            seed=seed + attempt,
            options=OPTIONS,
        )
        try:
            return check_screen(gen.generate(req))
        except (Rejected, ModelRefused) as e:
            print(f"  {pid}: attempt {attempt + 1} rejected: {e}", file=sys.stderr)
    return None


def is_shortlisted(screen: dict, min_fit: int) -> bool:
    return screen["kind"] in OWN_KINDS and screen["episodes"] >= 1 and screen["fit"] >= min_fit


def main(argv=None, gen: Generator | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pool", type=Path, default=ROOT / "data/raw/reddit_adhd.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "data/raw/reddit_screened.jsonl")
    ap.add_argument("--shortlist", type=Path, default=ROOT / "data/raw/reddit_shortlist.jsonl")
    ap.add_argument("--cache", type=Path, default=ROOT / "data/cache")
    ap.add_argument(
        "--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--n", type=int, default=300, help="posts to label (random sample)")
    ap.add_argument("--min-fit", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--retries", type=int, default=2)
    args = ap.parse_args(argv)

    titles = {}
    for line in args.pool.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            titles[str(row.get("id"))] = row.get("title") or ""
    posts = [p for p in load_pool(args.pool) if prefilter(p.text, titles.get(p.id, ""))]
    sample = random.Random(args.seed).sample(posts, min(args.n, len(posts)))
    print(f"{len(posts)} posts after the pre-filter; labelling {len(sample)}", file=sys.stderr)

    done: dict[str, dict] = {}
    if args.out.exists():
        for line in args.out.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["id"]] = row
    gen = gen or CachedGenerator(OllamaGenerator(args.base_url, args.model), args.cache)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    with args.out.open("a", encoding="utf-8") as f:
        for i, post in enumerate(sample, 1):
            if post.id in done:
                continue
            screen = screen_post(gen, post.id, post.text, args.seed, args.retries)
            if screen is None:
                failed += 1
                continue
            done[post.id] = dict(id=post.id, text=post.text, model=gen.name, screen=screen)
            f.write(json.dumps(done[post.id], ensure_ascii=False) + "\n")
            f.flush()
            if i % 25 == 0:
                print(f"  {i}/{len(sample)}", file=sys.stderr)

    ranked = sorted(
        (r for r in done.values() if is_shortlisted(r["screen"], args.min_fit)),
        key=lambda r: (-r["screen"]["fit"], -r["screen"]["subtlety"], -r["screen"]["episodes"]),
    )
    with args.shortlist.open("w", encoding="utf-8") as f:
        for r in ranked:
            f.write(json.dumps(dict(id=r["id"], text=r["text"], label="adhd"), ensure_ascii=False))
            f.write("\n")
    kinds: dict[str, int] = {}
    for r in done.values():
        kinds[r["screen"]["kind"]] = kinds.get(r["screen"]["kind"], 0) + 1
    print(f"labelled {len(done)} ({failed} failed): {kinds}")
    print(f"shortlist: {len(ranked)} posts with fit >= {args.min_fit} -> {args.shortlist}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
