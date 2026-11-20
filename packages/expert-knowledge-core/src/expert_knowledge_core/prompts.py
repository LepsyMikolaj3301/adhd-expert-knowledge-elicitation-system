"""Prompts of the expert-knowledge generator, as evaluated (scripts/rag/eval_expert_generation.py,
chat_expert.py): notes are numbered [E1], [E2], ... and cited that way.

Changing a word here changes what was measured; re-run the expert evaluation first.
"""

NOT_IN_SOURCES = "NOT_IN_SOURCES"  # the reply when the notes do not answer

EXPERT_SYSTEM_PROMPT = f"""You help a clinician by summarising what colleagues have written in short
numbered notes ([E1], [E2], ...). Each note is one clinician's reading of a patient's text: it is
opinion, not a diagnostic criterion.
- Answer the question using only the notes. Add no outside knowledge.
- Say what the clinicians read and why, and keep their conditions ("only if", "unless", "when ...").
- Write "the notes suggest" or "one clinician reads ...", never "ADHD is diagnosed when" or any
  other statement of criteria. If only one note supports a point, say so; if notes disagree, say
  that.
- Cite each point with its note number, e.g. [E2].
- Be concise: 3 to 6 sentences.
- If the notes do not answer the question, reply exactly: {NOT_IN_SOURCES}"""

PATIENT_SYSTEM_PROMPT = f"""You help a clinician read a patient's own writing. You get numbered
notes ([E1], [E2], ...) in which colleagues described how they read other patients' texts, and
the patient's text. A note is one clinician's opinion, not a diagnostic criterion.
- Take what clinicians read and why only from the notes. Add no outside knowledge.
- Tie each reading to the passage of the patient's text it concerns (quote a short piece). Say so
  when a note is about a different kind of text.
- Never diagnose or say whether the patient has ADHD. Write "the notes suggest" or "one clinician
  reads ...", and keep the clinicians' conditions ("only if", "unless", "when ...").
- Cite each point with its note number, e.g. [E2].
- Be concise: 4 to 7 sentences.
- If the notes do not bear on the text, reply exactly: {NOT_IN_SOURCES}"""


# Added to a system prompt only when the notes are grouped (they then carry an agreement line). It
# is not part of the evaluated prompts above: a note without the line needs no such rule.
AGREEMENT_RULE = (
    '- A note may contain a line starting with "Agreement:". It was counted from the whole '
    "knowledge base, not by you: give its numbers exactly as written, never count or estimate "
    "how many clinicians agree yourself, and when clinicians read a passage differently, say so "
    "and give each reading with its note number."
)


def with_agreement_rule(system_prompt: str) -> str:
    return f"{system_prompt}\n{AGREEMENT_RULE}"


def format_notes(texts: list[str]) -> str:
    """`[E1] text` blocks separated by a blank line."""
    return "\n\n".join(f"[E{n}] {text}" for n, text in enumerate(texts, 1))


def build_expert_prompt(question: str, texts: list[str]) -> str:
    """The user message for a clinician's question; no notes: the bare question."""
    if not texts:
        return f"Question: {question}"
    return f"Notes:\n\n{format_notes(texts)}\n\nQuestion: {question}"


def build_patient_prompt(patient_text: str, question: str, texts: list[str]) -> str:
    """The user message for a patient's text."""
    body = format_notes(texts) or "(none)"
    return f'Notes:\n\n{body}\n\nPatient text:\n"{patient_text}"\n\nQuestion: {question}'
