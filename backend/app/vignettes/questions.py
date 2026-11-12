"""The six base questions and the wording of the Q4 step. All answers must be given to the same
text. The one copy: the API, the worker and the scripts all read it."""

from dataclasses import dataclass
from typing import Literal, get_args

QuestionId = Literal["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
QuestionKind = Literal["open", "shift", "rating_1_5"]
QUESTION_IDS: tuple[str, ...] = get_args(QuestionId)


@dataclass(frozen=True)
class Question:
    id: QuestionId
    kind: QuestionKind
    text: str
    # Different words an answer should have. Only scripts/elicitation uses it: the API neither sends
    # nor enforces it, so the screen never stops anyone for writing too little.
    min_words: int | None = None


QUESTIONS: dict[str, Question] = {
    question.id: question
    for question in (
        Question(
            "Q1",
            "open",
            "Which fragments of the text matter for your reading of ADHD-related traits, in either "
            "direction: pointing toward them, pointing away from them, or just ordinary? For each: "
            "what does it show, and why does this wording suggest it?",
            min_words=15,
        ),
        Question(
            "Q2",
            "open",
            "Which of those fragments could equally reflect something else (e.g. low mood, poor "
            "sleep, anxiety, ordinary procrastination)? What would distinguish them?",
            min_words=10,
        ),
        Question(
            "Q3",
            "open",
            "What is missing from this text that you would need before treating these features "
            "as meaningful?",
            min_words=10,
        ),
        Question(
            "Q4",
            "shift",
            "Given your hypothesis about this person so far: how would it change if {whatif}?",
            min_words=5,
        ),
        Question(
            "Q5",
            "open",
            "What would a less experienced clinician likely over- or under-interpret in this text?",
            min_words=10,
        ),
        Question(
            "Q6",
            "rating_1_5",
            "Overall, how strongly does this text show ADHD-related traits? "
            '(1-5, or "insufficient information")',
        ),
    )
}

# Like min_words, used by scripts/elicitation only.
HYPOTHESIS_MIN_WORDS = 3

# Q4-Q6 are shown only once every asked gate question has a non-blank answer; after that the gate
# answers are locked, so the "hypothesis so far" is not rewritten after seeing the what-if.
GATE = ("Q1", "Q2", "Q3")

# The wording of the Q4 step, shared by the web app, the terminal and notebook scripts and prompts.
Q4_HYPOTHESIS = "Your working hypothesis, in one sentence"
SHIFT_LEAD = "With this, my hypothesis…"
SHIFT_LABELS = {
    -2: "is strongly reinforced",
    -1: "is somewhat reinforced",
    0: "is unchanged",
    1: "partly changes",
    2: "changes completely",
}
Q4_TOWARD = "Towards…"
TOWARD_LABELS = {
    "more_adhd": "more ADHD-like",
    "less_adhd": "less ADHD-like",
    "other": "another explanation",
}
Q4_WHY = "Why?"

# What the API sends to the frontend (JSON keys are strings).
Q4_WORDING = {
    "hypothesis": Q4_HYPOTHESIS,
    "shift_lead": SHIFT_LEAD,
    "shift_labels": {str(shift): label for shift, label in SHIFT_LABELS.items()},
    "toward": Q4_TOWARD,
    "toward_labels": TOWARD_LABELS,
    "why": Q4_WHY,
}


def render_question(question: Question, q4_whatif: str | None) -> str:
    if question.id != "Q4":
        return question.text
    if not q4_whatif:
        raise ValueError("Q4 needs a what-if")
    return question.text.format(whatif=q4_whatif.strip().rstrip("?."))


def describe_shift(shift: int, toward: str | None = None, other: str | None = None) -> str:
    """'+1 partly changes, towards less ADHD-like': a Q4 answer in one line."""
    out = f"{shift:+d} {SHIFT_LABELS[shift]}" if shift else f"0 {SHIFT_LABELS[0]}"
    if toward:
        out += f", towards {other if toward == 'other' and other else TOWARD_LABELS[toward]}"
    return out
