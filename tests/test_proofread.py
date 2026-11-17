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


def test_chips_are_sent_as_a_placeholder_not_the_patients_words():
    # The patient's words are not checked: errors in them made LanguageTool fail the request.
    data = grammar.annotate("Her ⟦h1⟧ is telling.")
    assert data == {
        "annotation": [
            {"text": "Her "},
            {"markup": "⟦h1⟧", "interpretAs": grammar.CHIP_READS_AS},
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


def reply(text: str) -> str:
    return json.dumps({"answer": text})


def test_a_reply_must_keep_every_chip_and_not_grow_too_much():
    answer = "⟦h1⟧ avoidance, not tidiness"
    assert enhance.rejection(reply("⟦h1⟧ reads as avoidance, not tidiness."), answer, {}) is None
    for bad, why in (
        (reply("It reads as avoidance."), "chips"),  # the chip is gone
        (reply("⟦h1⟧ ⟦h1⟧ avoidance"), "chips"),  # one too many
        (reply("⟦h1⟧ " + "word " * 60), "too_long"),
        (reply("  "), "empty"),
        (json.dumps({"text": "⟦h1⟧ x"}), "not_json"),
        ("not json", "not_json"),
    ):
        assert enhance.rejection(bad, answer, {}) == why, bad


# Taken from the v1 replies on the scale fixture: the model wrote the cited passage out as the
# clinician's own sentence, in the patient's first person.
NOTE = '⟦h4⟧ - hand note, list in locker "or my coat", mild, could be just tired.'
QUOTES = {4: "I wrote it on my hand because the list is in my locker, or my coat, I forget which."}


def test_a_reply_that_copies_the_cited_passage_is_refused():
    copied = "⟦h4⟧ - they wrote it on a hand and forget which locker; mild."
    assert enhance.leaked(copied, NOTE, QUOTES) == ["forget", "wrote"]
    assert enhance.rejection(reply(copied), NOTE, QUOTES) == "leak"


def test_the_patients_first_person_is_refused_where_the_clinician_wrote_none():
    answer = "⟦h1⟧ - time underestimate, 2h became the evening; weak alone."
    flipped = "⟦h1⟧ - I underestimated the time; two hours went, and I felt weak alone."
    assert enhance.rejection(reply(flipped), answer, {}) == "voice"


def test_a_quoted_my_is_the_patients_not_the_clinicians():
    """The real v1 case: the note quotes "or my coat", the reply tells the passage as "I"."""
    told = "⟦h4⟧ - I wrote a note on my hand; the list is in the locker, so it is mild."
    assert enhance.narrated(NOTE) == 0
    assert enhance.rejection(reply(told), NOTE, {}) == "voice"


def test_the_clinicians_own_i_is_fine():
    """'Need a baseline' -> 'I need a baseline' supplies the clinician's dropped subject. On the
    scale fixture this was the most common edit of Q3, and none of it is the patient speaking."""
    answer = "Need a baseline. Looked at ⟦h1⟧, can't say more."
    fuller = "I need a baseline. I looked at ⟦h1⟧, and I can't say more."
    assert enhance.narrated(fuller) == 0
    assert enhance.rejection(reply(fuller), answer, {}) is None


def test_a_reply_that_only_adds_glue_words_passes():
    """Words such as 'shows' or 'suggests' may also stand in a passage; they are not a copy."""
    answer = "⟦h1⟧ avoidance, not tidiness. ⟦h2⟧ mild"
    quotes = {1: "It shows I am tidy", 2: "This suggests nothing, like before"}
    fuller = "⟦h1⟧ shows avoidance, not tidiness. ⟦h2⟧ suggests something mild."
    assert enhance.leaked(fuller, answer, quotes) == []
    assert enhance.rejection(reply(fuller), answer, quotes) is None


def test_one_shared_word_is_not_yet_a_leak():
    answer = "⟦h1⟧ late start, mild"
    fuller = "⟦h1⟧ shows a late start in the evening, which is mild."
    assert enhance.rejection(reply(fuller), answer, {1: "I started late in the evening"}) is None


async def test_the_model_is_not_shown_the_cited_passages(monkeypatch):
    seen = []

    async def ask(system, user):
        seen.append(system + user)
        return reply("⟦h4⟧ is a hand note; the list is in a locker or a coat, which is mild.")

    monkeypatch.setattr(enhance, "ask", ask)
    monkeypatch.setattr(enhance.settings, "enhance_model", "qwen3.5:9b")
    text, refused = await enhance.enhance("Q?", NOTE, QUOTES)
    assert refused is None and text.startswith("⟦h4⟧ is a hand note")
    assert "I forget which" not in seen[0] and NOTE in seen[0]


async def test_a_refused_reply_says_why(monkeypatch):
    async def ask(system, user):
        return reply("⟦h4⟧ - I wrote it on my hand because I forget which.")

    monkeypatch.setattr(enhance, "ask", ask)
    monkeypatch.setattr(enhance.settings, "enhance_model", "qwen3.5:9b")
    assert await enhance.enhance("Q?", NOTE, QUOTES) == (None, "leak")


async def test_switching_the_enhancement_off_never_calls_the_model(monkeypatch):
    async def never(*args):
        raise AssertionError("called")

    monkeypatch.setattr(enhance, "ask", never)
    monkeypatch.setattr(enhance.settings, "enhance_model", "")
    assert await enhance.enhance("Q?", "an answer", {}) == (None, None)


# --- one answer, end to end ---------------------------------------------------------------------


def test_the_layout_is_one_sentence_per_line():
    text = "First point here, clearly. Second point, also clear.\n- a list item stays"
    assert pipeline.layout(text) == (
        "First point here, clearly.\nSecond point, also clear.\n- a list item stays"
    )


async def test_garbage_goes_before_the_grammar_checker_sees_it(monkeypatch):
    seen = []

    async def ask(text):
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
