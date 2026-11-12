"""The chip logic inside the backend: sentences, citations, units. No models, no database."""

import chip_findings
import pytest

from app.knowledge import findings

TEXT = (
    "I haven't slept well since moving. Numbers on the screen look blurry when I blink. "
    "The report falls apart again like last week."
)
SLEEP = "I haven't slept well since moving"
REPORT = "The report falls apart again like last week"


def highlight(chip: int, quote: str, direction: str) -> findings.Highlight:
    start = TEXT.index(quote)
    return findings.Highlight(chip, quote, (start, start + len(quote)), direction)


def response(answers: dict[str, str]) -> findings.Response:
    return findings.Response(
        vignette_id="V001",
        vignette_version=1,
        answers=answers,
        highlights=[highlight(1, SLEEP, "away"), highlight(2, REPORT, "toward")],
        rating=2,
        insufficient_information=False,
    )


def build(answers: dict[str, str], labels: dict[str, list[str]] | None = None) -> dict:
    return chip_findings.build_record(
        response(answers), TEXT, "S1", "E1", None, "personal_journal", "adult", labels
    )


CHIPS_ONLY = {
    "Q1": "⟦h1⟧ explains the tiredness. ⟦h2⟧ suggests a repeated pattern of disorganisation.",
}


def test_sentences_with_chips_need_no_classifier():
    record = build(CHIPS_ONLY)
    assert [(s["id"], s["targets"], s["assigned_by"]) for s in record["sentences"]] == [
        ("Q1.1", ["h1"], "chip"),
        ("Q1.2", ["h2"], "chip"),
    ]


def test_a_sentence_without_chip_waits_for_the_classifier():
    answers = {**CHIPS_ONLY, "Q3": "What was the baseline before the move?"}
    with pytest.raises(ValueError, match="need the classifier"):
        build(answers)
    record = build(answers, {"Q3.1": ["case"]})
    assert record["sentences"][-1]["targets"] == ["case"]
    assert record["sentences"][-1]["assigned_by"] == "llm"


def test_units_carry_a_body_a_reviewer_can_read():
    answers = {**CHIPS_ONLY, "Q3": "What was the baseline before the move?"}
    units = {u["highlight"] or "case": u for u in build(answers, {"Q3.1": ["case"]})["units"]}
    assert units["h1"]["body"] == f"Q1: «{SLEEP}» explains the tiredness."
    assert units["case"]["body"] == "Q3: What was the baseline before the move?"
    # The embedded text is that body under a header, never the other way round.
    assert units["h1"]["i1"].endswith(units["h1"]["body"])
    assert units["h1"]["i3"].splitlines()[1] == f'Patient: "{SLEEP}"'


def test_a_submission_becomes_a_response():
    payload = {
        "answers": {"Q1": "⟦h1⟧ explains the tiredness."},
        "highlights": [
            {"chip": 1, "text": SLEEP, "span": [0, len(SLEEP)], "direction": "away"},
        ],
        "q4": {"hypothesis": "tired", "shift": 1},
        "rating": None,
        "insufficient_information": True,
    }
    resp = findings.response_from_submission(payload, "V001", 2)
    assert (resp.vignette_id, resp.vignette_version, resp.insufficient_information) == (
        "V001",
        2,
        True,
    )
    assert resp.highlights == [findings.Highlight(1, SLEEP, (0, len(SLEEP)), "away")]


def test_only_open_questions_are_filed():
    payload = {
        "answers": {"Q1": "⟦h1⟧ explains the tiredness.", "Q4": "because the whatif changes it"},
        "highlights": [{"chip": 1, "text": SLEEP, "span": [0, 5], "direction": "away"}],
    }
    resp = findings.response_from_submission(payload, "V001", 1)
    assert list(resp.answers) == ["Q1"]
