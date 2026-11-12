"""Linking the lines of an answer to citations, and cutting linked lines into units."""

import chip_findings

from app.knowledge import findings
from app.proofread import links

VIGNETTE = "I reorganised my entire desk instead of starting the report and then slept badly."
H1 = "I reorganised my entire desk"


def highlights() -> list[dict]:
    start = VIGNETTE.index(H1)
    return [
        dict(id="h1", origin="expert", chip=1, span=[start, start + len(H1)], text=H1,
             direction="toward")
    ]  # fmt: skip


def test_lines_are_linked_by_chip_then_by_quoted_words():
    hs = highlights()
    linked = links.link_lines(
        {
            "Q1": '⟦h1⟧ is avoidance.\nThen "slept badly" points elsewhere.\nNothing here.',
        },
        hs,
        VIGNETTE,
    )
    assert [(line["targets"], line["assigned_by"]) for line in linked["Q1"]] == [
        (["h1"], "chip"),
        (["i1"], "quote"),
        ([], None),
    ]
    assert hs[-1]["origin"] == "implicit" and hs[-1]["text"] == "slept badly"


def test_relink_keeps_unchanged_lines_and_the_authors_own_tags():
    hs = highlights()
    old = [
        {"text": "Kept as it was.", "targets": ["case"], "assigned_by": "llm"},
        {"text": "Tagged by hand.", "targets": ["h1"], "assigned_by": "expert"},
        {"text": "Gone now.", "targets": ["h1"], "assigned_by": "llm"},
    ]
    text = "Kept as it was.\nTagged by hand.\n⟦h1⟧ is new.\n\nAlso new, no quote."
    lines = links.relink(old, text, {"Also new, no quote.": ["case", "h1", "case"]}, hs, VIGNETTE)
    assert lines == [
        {"text": "Kept as it was.", "targets": ["case"], "assigned_by": "llm"},
        {"text": "Tagged by hand.", "targets": ["h1"], "assigned_by": "expert"},
        {"text": "⟦h1⟧ is new.", "targets": ["h1"], "assigned_by": "chip"},
        {"text": "Also new, no quote.", "targets": ["case", "h1"], "assigned_by": "expert"},
    ]
    assert links.unlinked(lines) == []
    assert links.unlinked(links.relink([], "Just this.", {}, hs, VIGNETTE)) == [0]


def test_a_newline_always_ends_a_sentence():
    text = "short one\nAnd a second line that goes on. With two sentences in it here."
    assert [text[a:b] for a, b in findings.split_sentences(text)] == [
        "short one",
        "And a second line that goes on.",
        "With two sentences in it here.",
    ]


def test_linked_lines_cut_into_the_same_units_as_filed_sentences():
    """record_from_lines gives what build_record gives when the targets are the same."""
    answers = {
        "Q1": "⟦h1⟧ reads as avoidance of the task, not ordinary tidiness.",
        "Q2": "Could equally be sleep loss after the move, not a trait.",
    }
    response = findings.Response(
        vignette_id="V1",
        vignette_version=1,
        answers=answers,
        highlights=[findings.Highlight(1, H1, (0, len(H1)), "toward")],
        rating=2,
        insufficient_information=False,
    )
    args = ("s1", "e1", None, "personal_journal", "adult")
    filed = chip_findings.build_record(response, VIGNETTE, *args, labels={"Q2.1": ["case"]})
    hs = findings.expert_highlights(response.highlights)
    lines = {
        "Q1": [{"text": answers["Q1"], "targets": ["h1"], "assigned_by": "chip"}],
        "Q2": [{"text": answers["Q2"], "targets": ["case"], "assigned_by": "llm"}],
    }
    linked = findings.record_from_lines(response, lines, hs, *args)
    assert [u["i1"] for u in linked["units"]] == [u["i1"] for u in filed["units"]]
    assert [u["sentences"] for u in linked["units"]] == [["Q1.1"], ["Q2.1"]]


def test_a_line_of_two_sentences_gives_both_its_targets():
    response = findings.Response("V1", 1, {"Q3": "x"}, [], None, False)
    two = "The first sentence is here. The second one is here too."
    record = findings.record_from_lines(
        response,
        {"Q3": [{"text": two, "targets": ["case"], "assigned_by": "expert"}]},
        [],
        "s1", "e1", None, "email", "adult",
    )  # fmt: skip
    assert [(s["id"], s["text"], s["targets"]) for s in record["sentences"]] == [
        ("Q3.1", "The first sentence is here.", ["case"]),
        ("Q3.2", "The second one is here too.", ["case"]),
    ]
