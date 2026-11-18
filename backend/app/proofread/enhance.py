"""Fuller sentences from a local model (prompt Answer_enhance.v2).

The model writes text here, unlike the classifier, so its reply is checked by code before it is
used: the same chips the same number of times, not empty, not much longer than the answer, no
words taken from the cited passages, and no "I" where the clinician wrote none. A reply that fails
is dropped and the proofread answer stands. The author sees the result next to their original and
edits it before anyone reads it.

The model is not shown the cited passages: with them (v1) it copied them into the answer, often in
the patient's first person. The checks still read them (`quotes`), to catch that.
"""

import re
from collections import Counter

from snowballstemmer import stemmer

from app.assignments.answers import CHIP_RE
from app.ollama import chat_json, parse_json_object
from app.prompts import load_prompt
from app.settings import settings
from expert_knowledge_core.bm25 import STOPWORDS

PROMPT = "Answer_enhance.v2"
OPTIONS = {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1200}
# A reply may be at most this many times the answer's words, plus SLACK_WORDS.
GROWTH, SLACK_WORDS = 2.5, 40
# A reply with this many words that are in a cited passage but not in the answer copied the passage.
LEAK_WORDS = 2
# Words a fuller sentence adds on its own, wherever they also stand in a passage.
_GLUE_TEXT = (
    "about after also any because before both can could did does done each even here how just "
    "may might more most much not now one only other out over same some still than them too "
    "two very what when who why being shows suggests seems looks reads like"
)
_GLUE = frozenset(_GLUE_TEXT.split())
_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
# The patient telling their own story: "my", "me", or "I" with a past-tense verb ("I wrote",
# "I felt", "I underestimated"). A clinician writes "I need", "I would", "I can't say": they pass.
_NARRATED = re.compile(
    r"\b(?:my|me|mine|myself)\b|\bI\s+(?!(?:need|looked|noticed|wondered)\b)"
    r"(?:\w+ed|was|were|felt|wrote|did|had|went|kept|forgot|took|"
    r"got|made|left|told|thought|knew|lost|spent|sat|ran|came|gave|put|said|began|found|slept)\b",
    re.IGNORECASE,
)
# "…", “…”, and '…' where the quote marks don't stand inside a word (so "can't" is no quote).
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|(?<![A-Za-z])'[^']*'(?![A-Za-z])")
_stem = stemmer("english").stemWord


def _content(text: str) -> set[str]:
    """The stems of a text's content words: 3+ letters, not a stop or glue word."""
    words = _WORD.findall(CHIP_RE.sub(" ", text).lower().replace("’", "'"))
    return {_stem(w) for w in words if len(w) >= 3 and w not in STOPWORDS and w not in _GLUE}


def leaked(reply: str, answer: str, quotes: dict[int, str]) -> list[str]:
    """Stems of the reply that are in a cited passage but nowhere in the answer, sorted."""
    passages = set().union(*(_content(text) for text in quotes.values())) if quotes else set()
    return sorted((_content(reply) - _content(answer)) & passages)


def narrated(text: str) -> int:
    """How often the text tells a story in the first person, outside quotation marks (a quoted
    "my coat" is the patient's own words, cited)."""
    text = _QUOTED.sub(" ", text.replace("’", "'").replace("‘", "'"))
    return len(_NARRATED.findall(text))


def rejection(raw: str, answer: str, quotes: dict[int, str]) -> str | None:
    """Why the reply can't be used, or None when it can."""
    data = parse_json_object(raw)
    if data is None or not isinstance(data.get("answer"), str):
        return "not_json"
    text = data["answer"].strip()
    if not text:
        return "empty"
    if Counter(CHIP_RE.findall(text)) != Counter(CHIP_RE.findall(answer)):
        return "chips"
    if len(text.split()) > GROWTH * len(answer.split()) + SLACK_WORDS:
        return "too_long"
    if len(leaked(text, answer, quotes)) >= LEAK_WORDS:
        return "leak"
    if narrated(text) > narrated(answer):
        return "voice"
    return None


async def ask(system: str | None, user: str) -> str:
    """One chat call to Ollama in JSON mode. Tests replace this function."""
    return await chat_json(settings.enhance_model, system, user, {"seed": 1, **OPTIONS})


async def reply(question: str, answer: str) -> str:
    """The model's raw reply for one answer."""
    prompt = load_prompt(PROMPT).fill(QUESTION=question, ANSWER=answer)
    return await ask(prompt.system, prompt.user)


async def enhance(
    question: str, answer: str, quotes: dict[int, str]
) -> tuple[str | None, str | None]:
    """(the answer in fuller sentences, why the reply was refused). Both None when switched off or
    there is no answer."""
    if not settings.enhance_model or not answer.strip():
        return None, None
    raw = await reply(question, answer)
    why = rejection(raw, answer, quotes)
    data = parse_json_object(raw)
    if why or data is None:
        return None, why
    return data["answer"].strip(), None
