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
Q4 = Question(
    id="Q4",
    kind="open",
    text="How would your reading change if {element} were different?",
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
QUESTIONS_BY_ID = {q.id: q for q in QUESTIONS}
assert tuple(QUESTIONS_BY_ID) == get_args(QuestionId), "QuestionId and QUESTIONS are out of sync"


def render_question(question: Question, q4_element: str | None) -> str:
    """Question text as shown to the expert (fills Q4's {element})."""
    if question.id == "Q4":
        if not q4_element:
            raise ValueError("Q4 needs q4_element")
        return question.text.format(element=q4_element)
    return question.text
