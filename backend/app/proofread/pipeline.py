"""One answer through the proofreading: garbage out, grammar, fuller sentences, grammar again,
then one sentence per line. Garbage goes first: a spelling checker would otherwise turn
"afdoafgja" into a real word.

The grammar checker and the model are optional: when one can't be reached, its pass is skipped and
recorded, and the author still gets their answer back to check. Nothing here fails the job.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.errors import safe_traceback
from app.proofread import enhance, garbage, grammar
from expert_knowledge_core.notes import split_sentences

logger = logging.getLogger(__name__)
# What can go wrong talking to LanguageTool or Ollama. Anything else is a bug and raises.
SERVICE_ERRORS = (httpx.HTTPError, OSError, KeyError, ValueError)


@dataclass
class Proofread:
    text: str
    dropped: list[str] = field(default_factory=list)
    passes: dict[str, Any] = field(default_factory=dict)


def layout(text: str) -> str:
    """One sentence per line."""
    return "\n".join(text[a:b].strip() for a, b in split_sentences(text))


async def _grammar(
    text: str, quotes: dict[int, str], protected: set[str], passes: dict[str, Any], key: str
) -> str:
    try:
        checked = await grammar.check(text, quotes, protected)
    except SERVICE_ERRORS as exc:
        logger.warning("grammar check skipped\n%s", safe_traceback(exc))
        passes[key] = "unavailable"
        return text
    passes[key] = checked.edits
    if checked.version:
        passes["languagetool"] = checked.version
    return checked.text


async def proofread_answer(
    question: str, answer: str, quotes: dict[int, str], vignette: str
) -> Proofread:
    protected = grammar.vocabulary(vignette)
    passes: dict[str, Any] = {}
    text, dropped = garbage.drop_garbage(answer, protected)
    passes["dropped"] = len(dropped)
    text = await _grammar(text, quotes, protected, passes, "grammar")
    enhanced = None
    if text.strip():
        try:
            enhanced = await enhance.enhance(question, text, quotes)
        except SERVICE_ERRORS as exc:
            logger.warning("enhancement skipped\n%s", safe_traceback(exc))
            passes["enhanced"] = "unavailable"
    if enhanced is not None:
        passes["enhanced"] = True
        text = await _grammar(enhanced, quotes, protected, passes, "grammar_after")
    else:
        passes.setdefault("enhanced", False)
    return Proofread(text=layout(text), dropped=dropped, passes=passes)
