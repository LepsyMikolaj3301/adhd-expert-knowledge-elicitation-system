"""The six base questions every vignette draws from (Vignette.question_ids selects a subset)."""

from typing import get_args

from app.elicitation.schema import Question, QuestionId

Q1 = Question(
    id="Q1",
    kind="open",
    text=(
        "Quote the fragments you consider relevant to ADHD-related traits. "
        "For each: which trait, and why does this wording suggest it?"
    ),
)
Q2 = Question(
    id="Q2",
    kind="open",
    text=(
        "Which of those fragments could equally reflect something else (e.g. low mood, poor "
        "sleep, anxiety, ordinary procrastination)? What would distinguish them?"
    ),
)
Q3 = Question(
    id="Q3",
    kind="open",
    text=(
        "What is missing from this text that you would need before treating these features "
        "as meaningful?"
    ),
)
# Q4 is a short Script Concordance Test item: the vignette author supplies a what-if
# (Vignette.q4_whatif), the expert answers on a -2..+2 scale (ShiftAnswer) with a one-line
# hypothesis, a direction (only for +1/+2) and a why (answers["Q4"], only when not 0). The answering
# apps require all of these; the schema accepts their absence (synthetic answers, older drafts).
Q4 = Question(
    id="Q4",
    kind="shift",
    text="Given your hypothesis about this person so far: how would it change if {whatif}?",
)
Q5 = Question(
    id="Q5",
    kind="open",
    text="What would a less experienced clinician likely over- or under-interpret in this text?",
)
Q6 = Question(
    id="Q6",
    kind="rating_1_5",
    text=(
        "Overall, how strongly does this text show ADHD-related traits? "
        '(1-5, or "insufficient information")'
    ),
)

QUESTIONS = (Q1, Q2, Q3, Q4, Q5, Q6)
QUESTIONS_BY_ID: dict[str, Question] = {q.id: q for q in QUESTIONS}
assert tuple(QUESTIONS_BY_ID) == get_args(QuestionId), "QuestionId and QUESTIONS are out of sync"

# Q4-Q6 are shown only once every asked gate question has a non-blank answer; after that the
# gate answers are locked, so the "hypothesis so far" is not rewritten after seeing the what-if.
GATE = ("Q1", "Q2", "Q3")

# Shared wording of the Q4 step (terminal, notebook, prompts, web frontend).
Q4_HYPOTHESIS = "Your working hypothesis, in one sentence"
SHIFT_LEAD = "With this, my hypothesis…"
SHIFT_LABELS = {
    -2: "is strongly reinforced",
    -1: "is somewhat reinforced",
    0: "is unchanged",
    1: "partly changes",
    2: "changes completely",
}
TOWARD_LABELS = {
    "more_adhd": "more ADHD-like",
    "less_adhd": "less ADHD-like",
    "other": "another explanation",
}
Q4_TOWARD = "Towards…"
Q4_WHY = "Why?"


def render_question(question: Question, q4_whatif: str | None) -> str:
    """Question text as shown to the expert (fills Q4's {whatif})."""
    if question.id == "Q4":
        if not q4_whatif:
            raise ValueError("Q4 needs q4_whatif")
        return question.text.format(whatif=q4_whatif.strip().rstrip("?."))
    return question.text


def describe_shift(shift: int, toward: str | None = None, other: str | None = None) -> str:
    """'+1 partly changes, towards less ADHD-like': a Q4 answer in one line."""
    out = f"{shift:+d} {SHIFT_LABELS[shift]}" if shift else f"0 {SHIFT_LABELS[0]}"
    if toward:
        out += f", towards {other if toward == 'other' and other else TOWARD_LABELS[toward]}"
    return out
