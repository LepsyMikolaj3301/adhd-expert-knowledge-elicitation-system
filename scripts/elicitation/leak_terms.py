"""Words a vignette must not contain: they name the construct instead of letting it show."""

import re

LEAK_TERMS = (
    "adhd",
    "add/adhd",
    "attention deficit",
    "attention-deficit",
    "executive function",
    "executive dysfunction",
    "dopamine",
    "hyperfocus",
    "neurodivergent",
    "neurodiverse",
    "neurotypical",
    "diagnosed",
    "diagnosis",
    "my brain is wired",
    "my therapist says",
    "my psychiatrist",
    "inattentive",
    "hyperactive",
    "impulsivity",
    "subreddit",
    "r/adhd",
    # medication names
    "methylphenidate",
    "ritalin",
    "concerta",
    "medikinet",
    "adderall",
    "amphetamine",
    "lisdexamfetamine",
    "vyvanse",
    "elvanse",
    "atomoxetine",
    "strattera",
)

_PATTERN = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(t) for t in LEAK_TERMS) + r")(?!\w)", re.IGNORECASE
)


def find_leaks(text: str) -> list[str]:
    """Distinct blocklisted terms found in `text` (lowercased, in order of appearance)."""
    seen: dict[str, None] = {}
    for m in _PATTERN.finditer(text):
        seen.setdefault(m.group(1).lower())
    return list(seen)
