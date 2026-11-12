"""Step 3 of docs/new-chips-knowledge.md: a local model files the sentences that carry no citation.

One JSON-mode call per answer (prompt Expert_sentence_targets.v1): the numbered vignette, the
highlights with ids, every sentence (known targets shown), and the ids still open. The reply is ids
only. Code rejects unknown ids, missing sentences and a misplaced `prev`, and asks again with a new
seed. The model never writes text that is stored or shown.

A sentence still wrong after the retries is left out of the labels, and `apply_classification`
files it under `case`. A model that can't be reached is different: that raises, so the job fails
and is retried, instead of quietly filing everything under `case`.
"""

from typing import Any

from app.knowledge import findings
from app.ollama import chat_json, parse_json_object
from app.prompts import Prompt, load_prompt
from app.settings import settings

PROMPT = "Expert_sentence_targets.v1"
OPTIONS = {"temperature": 0.2, "num_predict": 600, "num_ctx": 8192}
RETRIES = 3


def prompt_for(
    vignette: str, highlights: list[dict], sentences: list[dict], left: list[str]
) -> Prompt:
    numbered = "\n".join(
        f"[{n}] {vignette[a:b].strip()}"
        for n, (a, b) in enumerate(findings.split_sentences(vignette), 1)
    )
    marks = []
    for h in highlights:
        note = (
            "" if h["origin"] == "expert" else " (quoted in the answers, not marked as a highlight)"
        )
        marks.append(f'{h["id"]}: "{h["text"]}"{note}')
    lines = []
    for s in sentences:
        known = f" -> {', '.join(s['targets'])}" if s["targets"] else ""
        lines.append(f"{s['id']}{known}  {' '.join(s['text'].split())}")
    return load_prompt(PROMPT).fill(
        VIGNETTE=numbered,
        HIGHLIGHTS="\n".join(marks),
        SENTENCES="\n".join(lines),
        UNRESOLVED=", ".join(left),
    )


def check_labels(
    raw: str, sentences: list[dict], left: list[str], allowed: set[str]
) -> tuple[dict[str, list[str]], list[str]]:
    """(valid entries, errors). A valid entry is a non-empty list of allowed ids; `prev` alone and
    never for the first sentence of an answer. The errors never quote the reply."""
    data = parse_json_object(raw)
    if data is None:
        return {}, ["the reply is not a JSON object"]
    first = {
        s["id"]
        for i, s in enumerate(sentences)
        if not i or sentences[i - 1]["question_id"] != s["question_id"]
    }
    good, errors = {}, []
    for sid in left:
        value = data.get(sid)
        if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value):
            errors.append(f"{sid}: missing or not a list of ids")
            continue
        ids = [x.strip().lower() for x in value]
        unknown = [x for x in ids if x not in allowed]
        if unknown:
            errors.append(f"{sid}: unknown ids {unknown}")
        elif "prev" in ids and (len(ids) > 1 or sid in first):
            errors.append(f"{sid}: 'prev' must be alone and not on the first sentence")
        else:
            good[sid] = list(dict.fromkeys(ids))
    return good, errors


async def ask(system: str | None, user: str, seed: int) -> str:
    """One chat call to Ollama in JSON mode. Tests replace this function."""
    return await chat_json(settings.classifier_model, system, user, {"seed": seed, **OPTIONS})


async def classify(
    vignette: str,
    highlights: list[dict],
    sentences: list[dict],
    left: list[str],
    *,
    retries: int = RETRIES,
    seed: int = 1,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """The labels for the sentences in `left`, and how it went: {attempts, errors}. Keeps the best
    reply seen, so a retry that does worse can't lose what an earlier one got right."""
    info: dict[str, Any] = {"attempts": 0, "errors": []}
    labels: dict[str, list[str]] = {}
    if not left:
        return labels, info
    allowed = {h["id"] for h in highlights} | {findings.CASE, "prev"}
    prompt = prompt_for(vignette, highlights, sentences, left)
    for attempt in range(retries + 1):
        info["attempts"] = attempt + 1
        raw = await ask(prompt.system, prompt.user, seed + attempt * 7919)
        good, errors = check_labels(raw, sentences, left, allowed)
        if len(good) > len(labels):
            labels = good
        info["errors"] = errors
        if not errors:
            break
    return labels, info
