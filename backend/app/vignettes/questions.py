"""The base questions and the wording of the Q4 step. All answers must be given to the same text."""

from dataclasses import dataclass
from typing import Literal, get_args

QuestionId = Literal["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
QuestionKind = Literal["open", "shift", "rating_1_5"]
QUESTION_IDS: tuple[str, ...] = get_args(QuestionId)


@dataclass(frozen=True)
class Question:
    id: str
    kind: QuestionKind
    text: str
    # Different words the answer must have to be accepted. For Q4, this is its "why".
    min_words: int | None = None


QUESTIONS: dict[str, Question] = {
    question.id: question
    for question in (
        Question(
            "Q1",
            "open",
            "Quote the fragments you consider relevant to ADHD-related traits. "
            "For each: which trait, and why does this wording suggest it?",
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

# Answered before anything else is shown. Passing the gate locks these answers.
GATE: tuple[str, ...] = ("Q1", "Q2", "Q3")

HYPOTHESIS_MIN_WORDS = 3

Q4_WORDING = {
    "hypothesis": "Your working hypothesis, in one sentence",
    "hypothesis_min_words": HYPOTHESIS_MIN_WORDS,
    "shift_lead": "With this, my hypothesis…",
    "shift_labels": {
        "-2": "is strongly reinforced",
        "-1": "is somewhat reinforced",
        "0": "is unchanged",
        "1": "partly changes",
        "2": "changes completely",
    },
    "toward": "Towards…",
    "toward_labels": {
        "more_adhd": "more ADHD-like",
        "less_adhd": "less ADHD-like",
        "other": "another explanation",
    },
    "why": "Why?",
}


def render_question(question: Question, q4_whatif: str | None) -> str:
    if question.id != "Q4":
        return question.text
    if not q4_whatif:
        raise ValueError("Q4 needs a what-if")
    return question.text.format(whatif=q4_whatif.strip().rstrip("?."))
