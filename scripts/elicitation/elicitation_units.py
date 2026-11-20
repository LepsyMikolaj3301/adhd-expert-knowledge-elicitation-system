"""Expert answers -> retrievable units (notes/expert-knowledge.md). No model calls.

A unit is one point of a clinician's answer, kept verbatim, plus the context it needs to stand
alone: a header from the session metadata and the vignette sentence each quote comes from.
"""

import re
from difflib import SequenceMatcher

from elicitation_schema import ElicitationDocument, Response, Vignette
from pydantic import BaseModel, ConfigDict

from app.vignettes.questions import describe_shift
from expert_knowledge_core.notes import FRAMING_LABEL

SEGMENTER_VERSION = 1
LONG_WORDS = 120  # a non-Q1 answer longer than this is split like an unlabelled Q1
MIN_SEGMENT_WORDS = 8  # shorter segments ("Under: nothing much.") join their neighbour
MIN_QUOTE_WORDS = 3  # shorter quotes ("again") are commentary, not evidence worth anchoring
FUZZY_RATIO = 0.8  # word-window similarity that still counts as the same quote
MAX_CONTEXT_WORDS = 60  # vignette sentences are often run-ons; clip around the quote

# what each question asks, short enough for a header ("Q2 'what else could explain them'")
QUESTION_GIST = {
    "Q1": "fragments relevant to ADHD-related traits",
    "Q2": "what else could explain those fragments",
    "Q3": "what is missing from the text",
    "Q4": "how the hypothesis changes if {whatif}",
    "Q5": "what a less experienced clinician would over- or under-read",
}
SHORTHAND = {"hx": "history", "ddx": "differential diagnosis", "r/o": "rule out", "->": "leads to"}

_QUOTE = re.compile(r'"([^"]+)"|“([^”]+)”')
_MARKER = re.compile(
    r"(?:(?<=\s)|^)(?:\([a-z0-9]\)|(?:HOW(?: it is written)?|Over(?:-read)?|Under(?:-read)?):)"
    r"(?=\s)"
    r"|^\s*(?:\d+[.)]|[-•])\s",
    re.MULTILINE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")
_REF = re.compile(r"\b(?:see|as)\s+Q([1-5])\b", re.IGNORECASE)
_BACK_REF = re.compile(r"\b(?:above|unchanged)\b", re.IGNORECASE)
_SHORT = re.compile(r"(?<!\w)(hx|ddx|r/o)(?!\w)|(->)|(?<!\w)(\?)(?=\w)")


class ExpertUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: str
    session_id: str
    expert_id: str
    vignette_id: str
    question_id: str
    text: str  # verbatim
    text_expanded: str  # shorthand spelled out, for the embedder and the generator
    quote_spans: list[tuple[int, int]]  # [start, end) in the vignette text
    unanchored_quotes: list[str]  # quoted in the answer but not found in the vignette
    vignette_context: list[str]
    refers_to: list[str]
    header: str
    framing: str
    track: str
    population: str
    origin: str
    rating: int | None
    insufficient_information: bool
    segmenter_version: int = SEGMENTER_VERSION


# --- segmentation ------------------------------------------------------------------------------


def _quotes(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(1) or m.group(2)) for m in _QUOTE.finditer(text)]


def sentences(text: str) -> list[str]:
    """Split at sentence ends, but never inside a quotation (quotes hold "?" and ".")."""
    inside = [(s, e) for s, e, _ in _quotes(text)]
    out, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        if not any(s < m.start() < e for s, e in inside):
            out.append(text[start : m.start()])
            start = m.end()
    return [*out, text[start:]]


def _words(text: str) -> int:
    return len(text.split())


def _split_at_markers(text: str) -> list[str]:
    cuts = [m.start() for m in _MARKER.finditer(text)]
    if not cuts:
        return [text]
    return [text[a:b] for a, b in zip([0, *cuts], [*cuts, len(text)], strict=True)]


def _split_by_new_quotes(text: str) -> list[str]:
    """A sentence with a quote not seen before starts a new point, once the current one has a quote.

    Sentences before the first quote and unquoted sentences after a quote stay with the point they
    lead into or follow.
    """
    segments: list[list[str]] = [[]]
    seen: set[str] = set()
    current_has_quote = False
    for sentence in sentences(text):
        fresh = {q.casefold() for *_, q in _quotes(sentence)} - seen
        if fresh and current_has_quote:
            segments.append([])
            current_has_quote = False
        segments[-1].append(sentence)
        if fresh:
            seen |= fresh
            current_has_quote = True
    return [" ".join(s) for s in segments]


def _merge_short(segments: list[str]) -> list[str]:
    out: list[str] = []
    carry = ""
    for s in segments:
        s = f"{carry} {s}".strip()
        carry = ""
        if _words(s) < MIN_SEGMENT_WORDS:
            carry = s
        else:
            out.append(s)
    if carry:
        if out:
            out[-1] = f"{out[-1]} {carry}"
        else:
            out.append(carry)
    return out


def segment(question_id: str, answer: str) -> list[str]:
    parts = _split_at_markers(answer.strip())
    if len(parts) == 1 and (question_id == "Q1" or _words(answer) > LONG_WORDS):
        parts = _split_by_new_quotes(answer.strip())
    return _merge_short([p.strip() for p in parts if p.strip()])


# --- context -----------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(text.casefold().strip(" .,;:!?").split())


def anchor_quote(quote: str, vignette: str) -> tuple[int, int] | None:
    """Exact (case/space-insensitive) match first, then the best word window above FUZZY_RATIO."""
    bare = quote.strip(" .,;:!?")
    hit = vignette.casefold().find(bare.casefold()) if bare else -1
    if hit >= 0:
        return hit, hit + len(bare)
    words = [
        (m.start(), m.start() + len(m.group().rstrip(".,;:!?")), _norm(m.group()))
        for m in re.finditer(r"\S+", vignette)
    ]
    target, n = _norm(quote), len(quote.split())
    best, best_span = FUZZY_RATIO, None
    for size in {max(n - 1, 1), n, n + 1}:
        for i in range(len(words) - size + 1):
            window = words[i : i + size]
            ratio = SequenceMatcher(None, target, " ".join(w[2] for w in window)).ratio()
            if ratio >= best:
                best, best_span = ratio, (window[0][0], window[-1][1])
    return best_span


def _answer_quotes(text: str) -> list[str]:
    pieces = []
    for *_, q in _quotes(text):
        pieces += [p for p in re.split(r"\.\.\.|…", q) if _words(p) >= MIN_QUOTE_WORDS]
    return pieces


def _context_sentence(
    vignette: str, span: tuple[int, int], max_words: int = MAX_CONTEXT_WORDS
) -> str:
    """The vignette sentence containing `span`, clipped around it when it is a run-on."""
    start = 0
    for m in _SENTENCE_END.finditer(vignette):
        if m.end() > span[0]:
            break
        start = m.end()
    m = _SENTENCE_END.search(vignette, span[1])
    sentence = vignette[start : m.start() if m else len(vignette)]
    if _words(sentence) <= max_words:
        return sentence
    before, after = (
        vignette[start : span[0]].split(),
        vignette[span[1] : start + len(sentence)].split(),
    )
    keep = max((max_words - len(vignette[span[0] : span[1]].split())) // 2, 0)
    clipped_before = ("… " if len(before) > keep else "") + " ".join(before[len(before) - keep :])
    clipped_after = " ".join(after[:keep]) + (" …" if len(after) > keep else "")
    return f"{clipped_before} {vignette[span[0] : span[1]]} {clipped_after}".strip()


def expand_shorthand(text: str) -> str:
    def spell(m: re.Match) -> str:
        if m.group(3):
            return "?"  # "?means" stays as written; a gloss would read as noise
        word = m.group(1) or m.group(2)
        return f"{word} [{SHORTHAND[word]}]"

    return _SHORT.sub(spell, text)


def header(doc_role: str | None, vignette: Vignette, response: Response, question_id: str) -> str:
    who = f"Clinician ({doc_role})" if doc_role else "Clinician"
    framing = FRAMING_LABEL[vignette.framing]
    gist = QUESTION_GIST[question_id].format(whatif=vignette.q4_whatif)
    q4 = ""  # Q4: the scale answer next to the why, e.g. ' · hypothesis "..." · +1 partly changes'
    if question_id == "Q4" and response.q4 is not None:
        a = response.q4
        if a.hypothesis:
            q4 += f' · hypothesis "{a.hypothesis.strip()}"'
        q4 += f" · {describe_shift(a.shift, a.toward, a.other_explanation)}"
    if response.insufficient_information:
        overall = "overall: insufficient information"
    elif response.rating is not None:
        overall = f"overall {response.rating}/5"
    else:
        overall = "no overall rating"
    population = vignette.design.population
    article = "an" if population[0] in "aeiou" else "a"
    return f'{who} on {article} {population}\'s {framing} · {question_id} "{gist}"{q4} · {overall}'


# --- building units ----------------------------------------------------------------------------


def build_units(
    doc: ElicitationDocument,
    role: str | None = None,
    context_words: int = MAX_CONTEXT_WORDS,
    max_context: int | None = None,
) -> list[ExpertUnit]:
    """All units of a document. `role` is the expert's short role line for the header;
    `context_words` and `max_context` shorten the vignette context (words per sentence, sentences).
    """
    vignettes = {v.id: v for v in doc.vignettes}
    units: list[ExpertUnit] = []
    for response in doc.responses:
        vignette = vignettes[response.vignette_id]
        by_question: dict[str, list[ExpertUnit]] = {}
        for qid, answer in response.answers.items():
            for n, text in enumerate(segment(qid, answer), 1):
                spans, unanchored = [], []
                for quote in _answer_quotes(text):
                    span = anchor_quote(quote, vignette.text)
                    if span is None:
                        unanchored.append(quote)
                    elif span not in spans:
                        spans.append(span)
                context = list(
                    dict.fromkeys(_context_sentence(vignette.text, s, context_words) for s in spans)
                )[:max_context]
                unit = ExpertUnit(
                    unit_id=f"{doc.session_id}:{vignette.id}:{qid}:{n}",
                    session_id=doc.session_id,
                    expert_id=doc.expert_id,
                    vignette_id=vignette.id,
                    question_id=qid,
                    text=text,
                    text_expanded=expand_shorthand(text),
                    quote_spans=spans,
                    unanchored_quotes=unanchored,
                    vignette_context=context,
                    refers_to=[],
                    header=header(role, vignette, response, qid),
                    framing=vignette.framing,
                    track=vignette.design.track,
                    population=vignette.design.population,
                    origin=vignette.design.origin,
                    rating=response.rating,
                    insufficient_information=response.insufficient_information,
                )
                by_question.setdefault(qid, []).append(unit)
        for qid, qunits in by_question.items():
            for unit in qunits:
                unit.refers_to = _refs(unit, qid, by_question)
        units += [u for qunits in by_question.values() for u in qunits]
    return units


def _refs(unit: ExpertUnit, qid: str, by_question: dict[str, list[ExpertUnit]]) -> list[str]:
    targets = [f"Q{n}" for n in dict.fromkeys(_REF.findall(unit.text))]
    if not targets and qid != "Q1" and _BACK_REF.search(unit.text):
        targets = ["Q1"]  # "rest unchanged", "everything above": the main reading
    return [u.unit_id for t in targets if t != qid for u in by_question.get(t, [])]


def render_unit(unit: ExpertUnit, by_id: dict[str, ExpertUnit], ref_words: int = 40) -> str:
    """What the generator or the embedder sees: header, quoted vignette sentences, the answer."""
    lines = [unit.header]
    lines += [f'Text: "{c}"' for c in unit.vignette_context]
    lines.append(f"Clinician: {unit.text_expanded}")
    if unit.refers_to:
        ref = by_id[unit.refers_to[0]]
        words = ref.text_expanded.split()
        cut = " …" if len(words) > ref_words else ""
        lines.append(f"({ref.question_id}: {' '.join(words[:ref_words])}{cut})")
    return "\n".join(lines)
