"""EXAMPLE-ONLY helper for make_fixtures.py: real r/ADHD posts as vignette texts.

Not production code (nothing in backend/ knows about Reddit). The pool is a file the user
supplies; nothing here downloads data.

Posts are never rewritten: a sentence that names the construct (leak terms), a medication, a URL
or a handle is dropped whole, so every remaining span is still an exact substring of the post.
The Reddit label is a self-reported community label, not a diagnosis.
Pool format: JSONL, one post per line. Text is read from `text`, `selftext` or `body` (plus an
optional `title`), the id from `id`, and an optional `label` ("adhd" / "control") is honoured.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from leak_terms import find_leaks

from app.elicitation.schema import MAX_WORDS, MIN_WORDS

# Stripped from real posts on top of LEAK_TERMS (these would be too strict for model output).
_EXTRA = re.compile(
    r"https?://|www\.|\bu/\w|\br/\w|@\w|\bmeds?\b|\bmedication|\bdx\b|diagnos|\bstimulants?\b"
    r"|neurospicy|\badhders?\b|\bautis|\bocd\b|\bgp\b|\bpsych\w*|\btherapist|\bpills?\b",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")

# Crude trait lexicons used only to *select* posts that fit a vignette's target trait.
TRAIT_LEXICON: dict[str, re.Pattern] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "discourse_tangentiality": r"\b(anyway|rambl\w+|tangent\w*|side ?track\w*|where was i|"
        r"point is|back to|off topic|train of thought)\b",
        "time_estimation": r"\b(late|deadline|time blind\w*|lost track of time|running behind|"
        r"how long|last minute|took (me )?(way )?longer)\b",
        "task_initiation": r"\b(start(ing)?|begin|getting started|procrastinat\w+|putting off|"
        r"put off|avoid\w*|can'?t make myself)\b",
        "distractibility": r"\b(distract\w*|noise|notifications?|squirrel|forgot (what|why)|"
        r"lost my train)\b",
        "emotional_reactivity": r"\b(snapped|overwhelm\w*|furious|cried|crying|meltdown|"
        r"frustrat\w*|angry|burst)\b",
        "retrospective_childhood": r"\b(as a kid|when i was (a kid|little|young|in school)|"
        r"school|teachers?|growing up|report cards?)\b",
    }.items()
}


@dataclass(frozen=True)
class Post:
    id: str
    text: str  # cleaned: whole sentences only, within the word limits


def clean_post(text: str) -> str | None:
    """Keep whole sentences free of leak terms / URLs / handles; cap at MAX_WORDS.

    Returns None if fewer than MIN_WORDS remain.
    """
    kept, words = [], 0
    for sentence in _SENTENCES.split(text.strip()):
        sentence = sentence.strip()
        if not sentence or find_leaks(sentence) or _EXTRA.search(sentence):
            continue
        n = len(sentence.split())
        if words + n > MAX_WORDS:
            break
        kept.append(sentence)
        words += n
    return " ".join(kept) if words >= MIN_WORDS else None


def load_pool(path: Path) -> list[Post]:
    posts = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("label", "adhd") != "adhd":
            continue
        body = row.get("text") or row.get("selftext") or row.get("body") or ""
        text = f"{row['title']}. {body}" if row.get("title") else body
        cleaned = clean_post(text)
        if cleaned:
            pid = str(row.get("id") or hashlib.sha1(text.encode()).hexdigest()[:10])
            posts.append(Post(pid, cleaned))
    return posts


def trait_score(text: str, trait: str) -> int:
    return len(set(m.group(0).lower() for m in TRAIT_LEXICON[trait].finditer(text)))


def pick_posts(posts: list[Post], trait: str, n: int, taken: set[str], seed: int) -> list[Post]:
    """The n best-fitting unused posts for `trait` (at least 2 distinct lexicon hits)."""
    scored = [
        (-trait_score(p.text, trait), hashlib.sha1(f"{seed}:{p.id}".encode()).hexdigest(), p)
        for p in posts
        if p.id not in taken
    ]
    scored.sort(key=lambda t: t[:2])
    return [p for score, _, p in scored if -score >= 2][:n]
