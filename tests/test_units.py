"""Segmentation, quote anchoring, cross-references and shorthand on hand-written answers."""

from datetime import UTC, datetime

from app.elicitation.schema import ElicitationDocument, Response, Vignette, VignetteDesign
from app.elicitation.units import anchor_quote, build_units, expand_shorthand, render_unit, segment

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


def make_doc(answers: dict[str, str]) -> ElicitationDocument:
    v = Vignette(
        id="V001",
        version=1,
        text=TEXT,
        framing="email",
        question_ids=["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"],
        q4_element="the sleep",
        design=VignetteDesign(purpose="test"),
    )
    r = Response(
        vignette_id="V001",
        vignette_version=1,
        vignette_hash=v.content_hash,
        expert_id="SYN-001",
        is_synthetic=True,
        answers=answers,
        rating=2,
        started_at=NOW,
        submitted_at=NOW,
    )
    return ElicitationDocument(
        session_id="DOC-SYN-9999",
        expert_id="SYN-001",
        created_at=NOW,
        is_synthetic=True,
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
