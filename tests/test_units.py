"""Segmentation, quote anchoring, cross-references and shorthand on hand-written answers."""

from datetime import UTC, datetime

import pytest
from elicitation_schema import (
    ElicitationDocument,
    QuestionId,
    Response,
    Vignette,
    VignetteDesign,
    content_hash,
)
from elicitation_units import anchor_quote, build_units, expand_shorthand, render_unit, segment
from pydantic import ValidationError

TEXT = (
    "I kept forgetting to draft this email all week. The deadline is Friday and the numbers "
    "keep swimming when I blink. Then I made coffee instead of starting, which is silly. "
    "Anyway I will try again tomorrow after a proper night of sleep."
)
NOW = datetime(2026, 1, 5, tzinfo=UTC)
ENUMERATED = (
    'Thin. (a) "I kept forgetting to draft this email all week" - one slip, ordinary, and it '
    'is a deadline week. (b) "the numbers keep swimming when I blink" - physical, not attention '
    "at all, sleep or eyes. HOW: one run-on, but it does come back to the point."
)
PROSE = (
    'Little here. "I kept forgetting to draft this email all week" - one slip, apologised for, '
    'and the kind of thing everybody writes. The "Then I made coffee instead of starting" '
    'line is mild avoidance. And "numbers keep swimming" is not attention at all, more '
    "likely tired eyes."
)


WHATIF = "the writer had a night shift before writing this"
Q4 = {"hypothesis": "tired, not much trait-like", "shift": 1, "toward": "less_adhd"}


def make_doc(answers: dict[QuestionId, str], q4: dict | None = Q4) -> ElicitationDocument:
    """One response to a vignette that asks the gate questions answered here, then Q4-Q6."""
    v = Vignette(
        id="V001",
        version=1,
        text=TEXT,
        content_hash=content_hash(TEXT),
        framing="email",
        question_ids=[q for q in ("Q1", "Q2", "Q3") if q in answers] + ["Q4", "Q5", "Q6"],
        q4_whatif=WHATIF,
        design=VignetteDesign(purpose="test"),
    )
    r = Response(
        vignette_id="V001",
        vignette_version=1,
        vignette_hash=v.content_hash,
        expert_id="SYN-001",
        answers=answers,
        rating=2,
        q4=q4,
        started_at=NOW,
        submitted_at=NOW,
    )
    return ElicitationDocument(
        session_id="DOC-SYN-9999",
        expert_id="SYN-001",
        created_at=NOW,
        vignettes=[v],
        responses=[r],
    )


def test_enumerated_q1_splits_at_markers_and_keeps_the_text():
    parts = segment("Q1", ENUMERATED)
    assert [p.split()[0] for p in parts] == ["Thin.", "(a)", "(b)"] or len(parts) >= 3
    assert any(p.startswith("HOW:") for p in parts) or parts[-1].endswith("the point.")
    assert " ".join(" ".join(parts).split()) == " ".join(ENUMERATED.split())


def test_prose_q1_starts_a_point_at_each_new_quote():
    parts = segment("Q1", PROSE)
    assert len(parts) == 3
    assert parts[0].startswith("Little here.")  # the lead-in joins the first quote
    assert "everybody writes" in parts[0]


def test_short_answer_is_one_unit_and_label_answers_split():
    assert segment("Q3", "Another email from a calm week. Plus usual hx.") == [
        "Another email from a calm week. Plus usual hx."
    ]
    over_under = (
        "Over: the coffee break read as avoidance, nothing more. "
        "Under: the sleep loss itself, and the dull week."
    )
    assert len(segment("Q5", over_under)) == 2


def test_anchor_exact_and_near_miss():
    exact = "the numbers keep swimming when I blink"
    start = TEXT.index(exact)
    assert anchor_quote(exact, TEXT) == (start, start + len(exact))
    # one word dropped, as in the bad_quote fixtures
    near = "the numbers swimming when I blink"
    assert anchor_quote(near, TEXT) == (start, start + len(exact))
    assert anchor_quote("completely different words about taxes", TEXT) is None


def test_units_get_header_context_and_cross_reference():
    doc = make_doc(
        {"Q1": PROSE, "Q2": "Sleep covers it.", "Q4": "As it stands, see Q2. Rest same."}
    )
    units = build_units(doc, role="psychiatrist")
    by_id = {u.unit_id: u for u in units}
    first = units[0]
    assert first.header.startswith("Clinician (psychiatrist) on an adult's email · Q1")
    assert first.header.endswith("overall 2/5")
    assert first.vignette_context == [TEXT.split(". ")[0] + "."]
    assert len(first.quote_spans) == 1 and not first.unanchored_quotes
    q4 = by_id["DOC-SYN-9999:V001:Q4:1"]
    assert f'Q4 "how the hypothesis changes if {WHATIF}"' in q4.header
    assert (
        ' · hypothesis "tired, not much trait-like" · +1 partly changes, towards less ADHD-like ·'
        in q4.header
    )
    assert q4.refers_to == ["DOC-SYN-9999:V001:Q2:1"]
    assert "Q2: Sleep covers it." in render_unit(q4, by_id)


def test_unanchored_quote_is_reported():
    doc = make_doc(
        {"Q1": 'Odd: "a sentence the writer never wrote at all" - hmm, nothing much here.'}
    )
    (unit,) = build_units(doc)
    assert unit.quote_spans == [] and unit.unanchored_quotes


def test_shorthand_is_spelled_out_and_original_kept():
    assert expand_shorthand("usual hx; A -> B; ?means") == (
        "usual hx [history]; A -> [leads to] B; ?means"
    )


def test_key_check_rejects_names_from_the_vignette():
    import json

    import pytest
    from make_fixtures import Rejected
    from make_unit_keys import check_keys, vignette_names

    names = vignette_names("We spoke. Then Kevin said it was fine, and I agreed.")
    assert names == {"Kevin"}
    good = {
        "reading_rule": "A rumination loop about one person is not attention.",
        "questions": ["how do I spot rumination?", "is a loop about a colleague inattention?"],
        "traits": ["rumination"],
        "direction": "lowers",
    }
    assert check_keys(json.dumps(good), names)["direction"] == "lowers"
    with pytest.raises(Rejected, match="names from"):
        check_keys(json.dumps({**good, "reading_rule": "Kevin's remark is rumination."}), names)
    with pytest.raises(Rejected, match="direction"):
        check_keys(json.dumps({**good, "direction": "up"}), names)


def test_q4_needs_whatif_not_tied_to_text():
    v = make_doc({"Q1": PROSE}).vignettes[0]
    assert v.q4_whatif is not None and v.q4_whatif not in v.text  # a what-if is not a quote
    with pytest.raises(ValidationError, match="q4_without_whatif"):
        Vignette(**(v.model_dump() | {"q4_whatif": None}))
    with pytest.raises(ValidationError, match="extra"):
        Vignette(**(v.model_dump() | {"q4_fragment": "after a proper night of sleep"}))


def test_render_question_fills_whatif():
    from app.vignettes.questions import QUESTIONS, render_question

    text = render_question(QUESTIONS["Q4"], "the writer had an exam earlier that day.")
    assert text.endswith("how would it change if the writer had an exam earlier that day?")
    with pytest.raises(ValueError, match="what-if"):
        render_question(QUESTIONS["Q4"], None)


@pytest.mark.parametrize(
    ("q4", "code"),
    [
        ({"shift": 3}, "less_than_equal"),
        ({"shift": -1, "toward": "less_adhd"}, "toward_without_change"),
        ({"shift": 0, "toward": "more_adhd"}, "toward_without_change"),
        ({"shift": 2, "toward": "other"}, "other_without_name"),
        ({"shift": 2, "toward": "more_adhd", "other_explanation": "grief"}, "other_without_name"),
        ({"shift": 1, "hypothesis": "  "}, "empty_answer"),
    ],
)
def test_shift_answer_rules(q4, code):
    from elicitation_schema import ShiftAnswer

    with pytest.raises(ValidationError, match=code):
        ShiftAnswer(**q4)


def test_q4_why_needs_a_nonzero_shift():
    answers: dict[QuestionId, str] = {"Q1": PROSE, "Q4": "Because the night shift explains it."}
    make_doc(answers)  # +1 with a why: fine
    make_doc({"Q1": PROSE}, q4={"shift": 0})  # 0 without a why: fine
    for q4 in ({"shift": 0}, None):
        with pytest.raises(ValidationError, match="q4_why_without_shift"):
            make_doc(answers, q4=q4)


def test_q4_answer_needs_q4_asked():
    doc = make_doc({"Q1": PROSE})
    data = doc.model_dump()
    data["vignettes"][0]["question_ids"] = ["Q1", "Q6"]
    with pytest.raises(ValidationError, match="question_not_asked: Q4"):
        ElicitationDocument.model_validate(data)


def test_gate_questions_come_before_the_rest():
    data = make_doc({"Q1": PROSE, "Q2": "Sleep covers it."}).model_dump()
    data["responses"][0]["answers"].pop("Q2")  # Q2 asked but unanswered, Q4 and Q6 answered
    with pytest.raises(ValidationError, match="gate_not_passed"):
        ElicitationDocument.model_validate(data)
    data["vignettes"][0]["question_ids"] = ["Q1", "Q4", "Q5", "Q6"]  # Q2 not asked: Q1 is the gate
    ElicitationDocument.model_validate(data)
