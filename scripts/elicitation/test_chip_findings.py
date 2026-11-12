"""Tests for chip_findings.py, built on the worked example of docs/new-chips-knowledge.md.

Run by path (it sits outside tests/ because new code lives in scripts/ only):
    python -m pytest scripts/elicitation/test_chip_findings.py -q
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import chip_findings as cf  # noqa: E402
from chips_schema import ChipDocument, to_legacy  # noqa: E402
from elicitation_schema import Vignette, VignetteDesign, content_hash  # noqa: E402

FRAGS = [
    ("numbers on screen keep looking like they are moving when I blink", "away"),
    ("I haven't slept well since moving into this new flat two months ago", "away"),
    ("every time I try to type a formula my hand starts shaking slightly", "unclear"),
    ("the whole thing falls apart again like last week when I forgot to file the forms until "
     "Monday morning", "toward"),
]  # fmt: skip
TEXT = (
    "So here I am staring at the spreadsheet and the "
    + f"{FRAGS[0][0]} which is mostly because {FRAGS[1][0]} and {FRAGS[2][0]} so I will make "
    + f"coffee but it is due on Friday and if I do not get it right then {FRAGS[3][0]}. "
    + "The radiator is new. I will sort it out tomorrow."
)
ANSWERS = {
    "Q1": "⟦h3⟧ could be read as motor restlessness under task difficulty, but it's shaky ground. "
    '⟦h4⟧: the "again" suggests a repeated pattern of disorganisation. I\'m hedging heavily on '
    "both: hand shaking is more often anxiety or physiology, and the forgetting could just as "
    "well be sleep deprivation.",
    "Q2": "⟦h2⟧ explains most of this more parsimoniously: ⟦h1⟧, ⟦h3⟧, the gritty eyes, the fog. "
    "The 'falling apart' at work is more likely acute burnout than chronic disorganisation. "
    "What would distinguish them: lapses that also occur when sleep is adequate.",
    "Q3": "I'm missing baseline functioning before the move. Does ⟦h3⟧ happen only when tired? "
    "Without knowing whether this is new, I can't rule out adjustment disorder.",
    "Q5": "A less experienced clinician might take ⟦h3⟧ and ⟦h1⟧ as hyperactivity, missing that "
    "they follow from insomnia. They might also under-read ⟦h4⟧ as a one-off.",
}


def make_doc() -> ChipDocument:
    v = Vignette(
        id="V001", version=1, text=TEXT, content_hash=content_hash(TEXT),
        framing="personal_journal", question_ids=["Q1", "Q2", "Q3", "Q5", "Q6"],
        design=VignetteDesign(purpose="test"),
    )  # fmt: skip
    t = datetime(2026, 1, 5, 9, tzinfo=UTC)
    highlights = []
    for n, (text, direction) in enumerate(FRAGS, 1):
        a = TEXT.index(text)
        highlights.append(dict(chip=n, text=text, span=[a, a + len(text)], direction=direction))
    resp = dict(
        vignette_id="V001", vignette_version=1, vignette_hash=v.content_hash, expert_id="SYN-001",
        is_synthetic=True, answers=ANSWERS, highlights=highlights, insufficient_information=True,
        started_at=t, submitted_at=t,
    )  # fmt: skip
    return ChipDocument(
        session_id="DOC-SYN-0001", expert_id="SYN-001", created_at=t, is_synthetic=True,
        vignettes=[v], responses=[resp],
    )  # fmt: skip


def record(labels=None):
    doc = make_doc()
    return cf.build_record(
        doc.responses[0], TEXT, doc.session_id, doc.expert_id, "consultant psychiatrist",
        "personal_journal", "adult", labels,
    )  # fmt: skip


LABELS = {
    "Q1.3": ["h3", "h4"], "Q2.3": [cf.CASE], "Q3.1": [cf.CASE], "Q3.3": ["prev"],
}  # fmt: skip


def test_assignment_by_chip_and_quote():
    highlights, sentences = cf.assign(make_doc().responses[0], TEXT)
    by_id = {s["id"]: s for s in sentences}
    assert by_id["Q1.1"]["targets"] == ["h3"] and by_id["Q1.1"]["assigned_by"] == "chip"
    assert by_id["Q2.1"]["targets"] == ["h2", "h1", "h3"]
    assert by_id["Q5.2"]["targets"] == ["h4"]
    # 'falling apart' is quoted, not chipped: the fuzzy/exact matcher finds highlight 4
    assert by_id["Q2.2"]["targets"] == ["h4"] and by_id["Q2.2"]["assigned_by"] == "quote"
    assert not [h for h in highlights if h["origin"] == "implicit"]


def test_unresolved_go_to_the_classifier_and_prev_inherits():
    _, sentences = cf.assign(make_doc().responses[0], TEXT)
    assert cf.unresolved(sentences) == ["Q1.3", "Q2.3", "Q3.1", "Q3.3"]
    fallback = cf.apply_classification(sentences, LABELS)
    by_id = {s["id"]: s for s in sentences}
    assert fallback == []
    assert by_id["Q1.3"]["targets"] == ["h3", "h4"] and by_id["Q1.3"]["assigned_by"] == "llm"
    assert by_id["Q3.3"]["targets"] == by_id["Q3.2"]["targets"] == ["h3"]


def test_classifier_gap_falls_back_to_case():
    _, sentences = cf.assign(make_doc().responses[0], TEXT)
    fallback = cf.apply_classification(sentences, {"Q1.3": ["h3"]})
    assert fallback == ["Q2.3", "Q3.1", "Q3.3"]


def test_missing_labels_are_an_error():
    try:
        record(None)
    except ValueError as e:
        assert "classifier" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_units_context_and_flag():
    rec = record(LABELS)
    units = {u["highlight"] or "case": u for u in rec["units"]}
    assert set(units) == {"h1", "h2", "h3", "h4", "case"}
    assert units["h1"]["sentences"] == ["Q2.1", "Q5.1"]
    assert set(units["h3"]["context"]) == {"h2", "h1", "h4"}  # order = first mention
    assert units["h4"]["sentences"] == ["Q1.2", "Q1.3", "Q2.2", "Q5.2"]
    assert units["case"]["sentences"] == ["Q2.3", "Q3.1"]
    # toggle toward + "more likely ... than" in a sentence about h4 -> a direction flag
    flags = [f for f in rec["flags"] if f["kind"] == "direction" and f["highlight"] == "h4"]
    assert flags and "Keep, change, or mark unclear?" in flags[0]["message"]
    assert not [f for f in rec["flags"] if f["kind"] == "coverage"]


def test_embedded_text():
    rec = record(LABELS)
    unit = next(u for u in rec["units"] if u["highlight"] == "h3")
    first = unit["i1"].splitlines()
    assert first[0].startswith("Clinician (consultant psychiatrist) on an adult's journal entry")
    assert "fragment marked: unclear" in first[0] and "insufficient information" in first[0]
    assert any(line.startswith("Q1: «every time I try to type a formula…»") for line in first)
    assert "⟦" not in unit["i1"]
    assert unit["i3"].splitlines()[1] == f'Patient: "{FRAGS[2][0]}"'
    case = next(u for u in rec["units"] if u["kind"] == "case")
    assert case["i3"] == case["i1"]


def test_merge_and_pack_print_each_sentence_once():
    rec = record(LABELS)
    by_id = {u["id"]: u for u in rec["units"]}
    h1, h3 = (u["id"] for u in rec["units"] if u["highlight"] in ("h1", "h3"))
    groups = cf.merge_groups(by_id, [h3, h1])
    assert groups == [[h3, h1]]
    block = cf.pack_block(rec, groups[0])
    assert block.count("explains most of this more parsimoniously") == 1
    assert "(marked: unclear)" in block and "(marked: away)" in block
    assert block.startswith("Teaching case V001: an adult's journal entry")


def test_sentence_splitting_rules():
    text = 'Hard to say. He wrote "is it? maybe." and left. e.g. this one. See ⟦h1⟧ now, ok.'
    spans = cf.split_sentences(text)
    parts = [text[a:b] for a, b in spans]
    assert parts[0].startswith("Hard to say. He wrote")  # 3 words: joined forward when first
    assert any("e.g. this one" in p for p in parts)
    short = "One two three four. ⟦h2⟧ too."
    assert len(cf.split_sentences(short)) == 1  # a chip and one word is not a sentence


def test_implicit_highlight_from_a_quote_that_matches_the_vignette_only():
    doc = make_doc()
    doc.responses[0].answers["Q3"] = 'Is "the radiator is new" relevant to anything here at all?'
    highlights, sentences = cf.assign(doc.responses[0], TEXT)
    implicit = [h for h in highlights if h["origin"] == "implicit"]
    assert len(implicit) == 1 and implicit[0]["text"].lower() == "the radiator is new"
    assert implicit[0]["direction"] is None
    q31 = next(s for s in sentences if s["id"] == "Q3.1")
    assert q31["targets"] == ["i1"] and q31["assigned_by"] == "quote"


def test_legacy_view_renders_chips_as_quotes():
    legacy = to_legacy(make_doc())
    q1 = legacy.responses[0].answers["Q1"]
    assert "⟦" not in q1 and f'"{FRAGS[2][0]}" could be read' in q1
    assert legacy.responses[0].quoted_fragments[0] == FRAGS[0][0]
