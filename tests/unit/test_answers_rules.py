"""The rules for saving and submitting answers, without a database (assignments/answers.py).

tests/api/test_api_answers.py checks the same codes over HTTP; here every branch is a table row.
"""

import pytest

from app.assignments.answers import (
    AnswerPayload,
    check_chips,
    check_draft,
    clean_submission,
    count_words,
)
from app.core.errors import DomainError

TEXT = "I reorganised my entire desk instead of starting the report and then I slept badly."
CUE = "reorganised my entire desk"
ALL = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
OPEN = {"Q1": "one", "Q2": "two", "Q3": "three", "Q5": "five"}


def cite(chip=1, quote=CUE, direction="toward"):
    start = TEXT.index(quote)
    return {
        "chip": chip,
        "text": quote,
        "span": [start, start + len(quote)],
        "direction": direction,
    }


def payload(**fields) -> AnswerPayload:
    base = {
        "answers": {**OPEN, "Q4": "It would change."},
        "highlights": [cite()],
        "q4": {"hypothesis": "Insomnia", "shift": 1, "toward": "less_adhd"},
        "rating": 3,
    }
    return AnswerPayload.model_validate({**base, **fields})


def code_of(fn, *args) -> str:
    with pytest.raises(DomainError) as error:
        fn(*args)
    return error.value.code


def test_a_complete_payload_is_accepted_and_trimmed():
    cleaned = clean_submission(
        payload(answers={**OPEN, "Q1": "  padded  ", "Q4": " why "}), ALL, TEXT
    )
    assert cleaned.answers["Q1"] == "padded" and cleaned.answers["Q4"] == "why"
    assert cleaned.q4 is not None and cleaned.q4.hypothesis == "Insomnia"


# --- what may be saved as a draft --------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "asked", "code"),
    [
        ({"answers": {"Q5": "x"}}, ["Q1", "Q2"], "question_not_asked"),
        ({"answers": {"Q6": "x"}}, ALL, "answer_to_rating_question"),
        ({"q4": {"shift": 1}}, ["Q1", "Q2"], "question_not_asked"),
        ({"rating": 2}, ["Q1", "Q2"], "question_not_asked"),
        ({"insufficient_information": True}, ["Q1", "Q2"], "question_not_asked"),
        ({"highlights": [cite(2)]}, ALL, "chip_numbers"),
        ({"highlights": [cite(1), cite(1)]}, ALL, "chip_numbers"),
        ({"highlights": [{**cite(), "text": "not the text"}]}, ALL, "highlight_not_in_vignette"),
        ({"highlights": [{**cite(), "span": [5, 5]}]}, ALL, "highlight_not_in_vignette"),
        ({"highlights": [{**cite(), "span": [0, 9999]}]}, ALL, "highlight_not_in_vignette"),
    ],
)
def test_a_draft_is_checked_against_the_questions_and_the_text(fields, asked, code):
    assert code_of(check_draft, payload(**fields), asked, TEXT) == code


def test_a_draft_may_be_incomplete():
    check_draft(AnswerPayload(), ALL, TEXT)
    check_draft(payload(highlights=[cite(direction=None)], answers={"Q1": "just this"}), ALL, TEXT)


# --- what may be submitted ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"answers": {**OPEN, "Q5": "   "}}, "empty_answer"),  # blanks are dropped, then missing
        ({"answers": {"Q1": "a", "Q2": "b", "Q3": "c", "Q4": "why"}}, "empty_answer"),
        ({"answers": {**OPEN, "Q1": "see ⟦h2⟧", "Q4": "why"}}, "unknown_chip"),
        ({"highlights": [cite(direction=None)]}, "highlight_no_direction"),
        ({"rating": None}, "submission_incomplete"),
        ({"rating": 3, "insufficient_information": True}, "rating_conflict"),
        ({"q4": None}, "submission_incomplete"),
        ({"q4": {"hypothesis": "x"}}, "submission_incomplete"),  # no shift: not "0"
        ({"q4": {"hypothesis": "  ", "shift": 1, "toward": "less_adhd"}}, "submission_incomplete"),
        ({"q4": {"hypothesis": "x", "shift": 1}}, "submission_incomplete"),  # no direction
        ({"answers": OPEN}, "submission_incomplete"),  # a shift needs its why
        ({"q4": {"hypothesis": "x", "shift": 0}}, "q4_why_without_shift"),
        ({"q4": {"hypothesis": "x", "shift": -1, "toward": "less_adhd"}}, "toward_without_change"),
        ({"q4": {"hypothesis": "x", "shift": 1, "toward": "other"}}, "other_without_name"),
        (
            {
                "q4": {
                    "hypothesis": "x",
                    "shift": 1,
                    "toward": "less_adhd",
                    "other_explanation": "y",
                }
            },
            "other_without_name",
        ),
    ],
)
def test_a_submission_names_the_first_thing_wrong_with_it(fields, code):
    assert code_of(clean_submission, payload(**fields), ALL, TEXT) == code


def test_a_blank_why_with_no_shift_is_dropped_not_refused():
    answers = {**OPEN, "Q4": "   "}
    cleaned = clean_submission(
        payload(answers=answers, q4={"hypothesis": "x", "shift": 0}), ALL, TEXT
    )
    assert "Q4" not in cleaned.answers and cleaned.q4 is not None and cleaned.q4.shift == 0


def test_a_named_other_explanation_is_kept():
    q4 = {"hypothesis": "x", "shift": 2, "toward": "other", "other_explanation": " trauma "}
    cleaned = clean_submission(payload(q4=q4), ALL, TEXT)
    assert cleaned.q4 is not None and cleaned.q4.other_explanation == "trauma"


def test_a_vignette_without_q4_and_q6_needs_neither():
    cleaned = clean_submission(
        AnswerPayload(answers={"Q1": "a", "Q2": "b", "Q3": "c", "Q5": "e"}),
        ["Q1", "Q2", "Q3", "Q5"],
        TEXT,
    )
    assert cleaned.q4 is None and cleaned.rating is None


def test_insufficient_information_stands_in_for_a_rating():
    cleaned = clean_submission(payload(rating=None, insufficient_information=True), ALL, TEXT)
    assert cleaned.insufficient_information and cleaned.rating is None


# --- chips and words ---------------------------------------------------------------------------


def test_a_chip_must_point_at_a_citation():
    check_chips("Q1", "see ⟦h1⟧ and ⟦h2⟧", {1, 2})
    assert code_of(check_chips, "Q1", "see ⟦h3⟧", {1, 2}) == "unknown_chip"


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("test test test", 1),
        ("Test, TEST!", 1),
        ("a ⟦h1⟧ b ⟦h2⟧", 2),
        ("", 0),
        ("⟦h1⟧", 0),
        ("one two", 2),
    ],
)
def test_words_are_the_different_ones_and_a_chip_is_not_a_word(text, words):
    assert count_words(text) == words
