"""The proofreading passes on their own: grammar fixes, garbage, the enhancement check, layout."""

import json

import pytest

from app.proofread import enhance, garbage, grammar, pipeline

VIGNETTE = "I reorganised my entire desk instead of starting the report. Hyperfocus all night."


def match(text: str, word: str, fix: str, category: str = "GRAMMAR", nth: int = 0) -> dict:
    start = -1
    for _ in range(nth + 1):
        start = text.index(word, start + 1)
    return {
        "offset": start,
        "length": len(word),
        "replacements": [{"value": fix}, {"value": "second choice"}],
        "rule": {"id": f"{category}_RULE", "category": {"id": category}},
    }


# --- grammar ------------------------------------------------------------------------------------


def test_fixes_are_applied_from_the_end_so_offsets_stay_right():
    text = "he dont know. she dont care"
    reply = {"matches": [match(text, "dont", "doesn't"), match(text, "dont", "doesn't", nth=1)]}
    checked = grammar.apply(text, reply, set())
    assert checked.text == "he doesn't know. she doesn't care"
    assert checked.edits == 2


def test_only_the_first_suggestion_and_only_some_kinds_of_rule():
    text = "The patient is very very tired , clearly"
    reply = {
        "matches": [
            match(text, "very very", "very", "REDUNDANCY"),
            match(text, " ,", ",", "PUNCTUATION"),
            match(text, "clearly", "obviously", "STYLE"),
        ]
    }
    checked = grammar.apply(text, reply, set())
    assert checked.text == "The patient is very very tired, clearly"
    assert sorted(checked.skipped) == ["REDUNDANCY_RULE", "STYLE_RULE"]


def test_overlapping_fixes_keep_only_the_later_one():
    text = "a a b"
    reply = {"matches": [match(text, "a a", "a"), match(text, "a b", "ab", nth=0)]}
    reply["matches"][1]["offset"] = 2
    assert grammar.apply(text, reply, set()).text == "a ab"


def test_a_fix_never_touches_a_chip():
    text = "⟦h1⟧ show that he is tired"
    reply = {"matches": [match(text, "⟦h1⟧ show", "⟦h1⟧ shows")]}
    assert grammar.apply(text, reply, set()).text == text


@pytest.mark.parametrize(
    ("word", "fix", "applied"),
    [
        ("teh", "the", True),
        ("recieve", "receive", True),
        ("excpecting", "expecting", True),  # not a word at all
        ("behaviour", "behavior", False),  # British spelling
        ("reorganised", "reorganized", False),  # and it is in the vignette
        ("hyperfocus", "hyper focus", False),  # a clinical term
        ("stimming", "stemming", False),
    ],
)
def test_spelling_is_fixed_only_where_the_fix_is_clearly_the_word_meant(word, fix, applied):
    text = f"I think {word} matters"
    reply = {"matches": [match(text, word, fix, "TYPOS")]}
    checked = grammar.apply(text, reply, grammar.vocabulary(VIGNETTE))
    assert (checked.text == f"I think {fix} matters") is applied


def test_offsets_count_utf16_units_like_java():
    text = "😀 he dont know"
    reply = {"matches": [{**match(text, "dont", "doesn't"), "offset": text.index("dont") + 1}]}
    assert grammar.apply(text, reply, set()).text == "😀 he doesn't know"


def test_chips_are_sent_as_the_words_they_stand_for():
    data = grammar.annotate("Her ⟦h1⟧ is telling.", {1: "I can't sleep"})
    assert data == {
        "annotation": [
            {"text": "Her "},
            {"markup": "⟦h1⟧", "interpretAs": '"I can\'t sleep"'},
            {"text": " is telling."},
        ]
    }
    json.dumps(data)


# --- garbage ------------------------------------------------------------------------------------


def test_keyboard_mashing_is_dropped_and_the_rest_kept():
    words = grammar.vocabulary(VIGNETTE)
    text = "The desk story is avoidance. afdoafgja qwrtzlk.\nawdaw\nSleep matters too."
    kept, dropped = garbage.drop_garbage(text, words)
    assert kept == "The desk story is avoidance.\nSleep matters too."
    assert dropped == ["afdoafgja qwrtzlk.", "awdaw"]


@pytest.mark.parametrize(
    "sentence",
    [
        "I wasnt excpecting this at all, honestly.",  # typos are not garbage
        "ADHD and ASD overlap here.",
        "Hyperfocus all night is in the text.",
        "⟦h1⟧ ⟦h2⟧",
        "No.",
    ],
)
def test_real_writing_is_never_garbage(sentence):
    assert not garbage.is_garbage(sentence, grammar.vocabulary(VIGNETTE))


def test_another_language_counts_as_unreadable():
    """The answers feed an English knowledge base. The author sees what was dropped and can
    write it again."""
    assert garbage.is_garbage("Pacjent nie śpi dobrze od tygodnia", set())


# --- the enhancement ----------------------------------------------------------------------------


def test_a_reply_must_keep_every_chip_and_not_grow_too_much():
    answer = "⟦h1⟧ avoidance, not tidiness"
    good = json.dumps({"answer": "⟦h1⟧ reads as avoidance, not tidiness."})
    assert enhance.check_reply(good, answer) == "⟦h1⟧ reads as avoidance, not tidiness."
    for bad in (
        json.dumps({"answer": "It reads as avoidance."}),  # the chip is gone
        json.dumps({"answer": "⟦h1⟧ ⟦h1⟧ avoidance"}),  # one too many
        json.dumps({"answer": "⟦h1⟧ " + "word " * 60}),  # far longer
        json.dumps({"answer": "  "}),
        json.dumps({"text": "⟦h1⟧ x"}),
        "not json",
    ):
        assert enhance.check_reply(bad, answer) is None, bad


async def test_switching_the_enhancement_off_never_calls_the_model(monkeypatch):
    async def never(*args):
        raise AssertionError("called")

    monkeypatch.setattr(enhance, "ask", never)
    monkeypatch.setattr(enhance.settings, "enhance_model", "")
    assert await enhance.enhance("Q?", "an answer", {}) is None


# --- one answer, end to end ---------------------------------------------------------------------


def test_the_layout_is_one_sentence_per_line():
    text = "First point here, clearly. Second point, also clear.\n- a list item stays"
    assert pipeline.layout(text) == (
        "First point here, clearly.\nSecond point, also clear.\n- a list item stays"
    )


async def test_garbage_goes_before_the_grammar_checker_sees_it(monkeypatch):
    seen = []

    async def ask(text, quotes):
        seen.append(text)
        return {"matches": []}

    async def echo(system, user):
        raise ConnectionError("down")

    monkeypatch.setattr(grammar, "ask", ask)
    monkeypatch.setattr(enhance, "ask", echo)
    result = await pipeline.proofread_answer(
        "Q?", "The desk story is avoidance of work. asdkjh qwlkej.", {}, VIGNETTE
    )
    assert seen == ["The desk story is avoidance of work."]
    assert result.text == "The desk story is avoidance of work."
    assert result.dropped == ["asdkjh qwlkej."]
    assert result.passes == {"dropped": 1, "grammar": 0, "enhanced": "unavailable"}
