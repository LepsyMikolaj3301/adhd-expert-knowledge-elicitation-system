"""Fuller sentences from a local model (prompt Answer_enhance.v1).

The model writes text here, unlike the classifier, so its reply is checked by code before it is
used: the same chips the same number of times, not empty, not much longer than the answer. A reply
that fails is dropped and the proofread answer stands. The author sees the result next to their
original and edits it before anyone reads it.
"""

import json
import re
from collections import Counter
from typing import Any

import httpx

from app.assignments.answers import CHIP_RE
from app.prompts import load_prompt
from app.settings import settings

PROMPT = "Answer_enhance.v1"
OPTIONS = {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1200}
# A reply may be at most this many times the answer's words, plus SLACK_WORDS.
GROWTH, SLACK_WORDS = 2.5, 40


async def ask(system: str | None, user: str) -> str:
    """One chat call to Ollama in JSON mode. Tests replace this function."""
    messages = [{"role": "user", "content": user}]
    if system:
        messages.insert(0, {"role": "system", "content": system})
    body: dict[str, Any] = {
        "model": settings.enhance_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"seed": 1, **OPTIONS},
    }
    async with httpx.AsyncClient(
        base_url=settings.ollama_base_url, timeout=settings.ollama_request_timeout
    ) as client:
        response = await client.post("/api/chat", json=body)
        response.raise_for_status()
        return response.json()["message"]["content"]


def check_reply(raw: str, answer: str) -> str | None:
    """The edited answer, or None when the reply can't be used."""
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    text = data.get("answer") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    if Counter(CHIP_RE.findall(text)) != Counter(CHIP_RE.findall(answer)):
        return None
    if len(text.split()) > GROWTH * len(answer.split()) + SLACK_WORDS:
        return None
    return text


async def enhance(question: str, answer: str, quotes: dict[int, str]) -> str | None:
    """The answer in fuller sentences, or None (switched off, unusable reply)."""
    if not settings.enhance_model or not answer.strip():
        return None
    prompt = load_prompt(PROMPT).fill(
        QUESTION=question,
        ANSWER=answer,
        CITATIONS="\n".join(f'⟦h{chip}⟧: "{text}"' for chip, text in sorted(quotes.items()))
        or "(none)",
    )
    return check_reply(await ask(prompt.system, prompt.user), answer)
