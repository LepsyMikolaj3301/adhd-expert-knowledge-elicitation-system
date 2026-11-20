from expert_knowledge_core import notes
from expert_knowledge_core.example import example_record
from expert_knowledge_core.records import is_readable


def units_by_id(rec):
    return {u["id"]: u for u in rec["units"]}


def test_example_record_is_readable_and_cut_like_the_doc():
    rec = example_record()
    assert is_readable(rec)
    by_id = units_by_id(rec)
    assert by_id["h1"]["sentences"] == ["Q2.1", "Q5.1"]
    assert by_id["h4"]["sentences"] == ["Q1.2", "Q1.3", "Q2.2", "Q5.2"]
    assert set(by_id["h3"]["context"]) == {"h2", "h1", "h4"}
    assert by_id["case"]["sentences"] == ["Q2.3", "Q3.1"]


def test_unreadable_documents():
    rec = example_record()
    assert not is_readable({**rec, "version": 99})
    assert not is_readable({"responses": []})  # a ChipDocument, as in chips_eval
    assert not is_readable(None)


def test_embedded_text():
    unit = units_by_id(example_record())["h3"]
    first = unit["i1"].splitlines()
    assert first[0].startswith("Clinician on an adult's journal entry")
    assert "fragment marked: unclear" in first[0] and "insufficient information" in first[0]
    assert "⟦" not in unit["i1"]
    assert "i3" not in unit


def test_merge_and_pack_print_each_sentence_once():
    rec = example_record()
    by_id = units_by_id(rec)
    assert notes.merge_groups(by_id, ["h3", "h1"]) == [["h3", "h1"]]
    block = notes.pack_block(rec, ["h3", "h1"])
    assert block.count("explains most of this more parsimoniously") == 1
    assert "(marked: unclear)" in block and "(marked: away)" in block
    assert block.startswith("Teaching case V001: an adult's journal entry")
    assert "⟦" not in block and "«" in block


def test_units_that_share_nothing_stay_apart():
    rec = example_record()
    assert notes.merge_groups(units_by_id(rec), ["h2", "case"]) == [["h2"], ["case"]]


def test_chip_rendering_truncates_to_eight_words():
    hl = [{"chip": 4, "text": "one two three four five six seven eight nine ten"}]
    assert (
        notes.render_sentence("See ⟦h4⟧ now.", hl)
        == "See «one two three four five six seven eight…» now."
    )


def test_sentence_splitting_rules():
    text = 'Hard to say. He wrote "is it? maybe." and left. e.g. this one. See ⟦h1⟧ now, ok.'
    parts = [text[a:b] for a, b in notes.split_sentences(text)]
    assert parts[0].startswith("Hard to say. He wrote")  # 3 words: joined forward when first
    assert any("e.g. this one" in p for p in parts)
    assert len(notes.split_sentences("One two three four. ⟦h2⟧ too.")) == 1


def test_a_line_break_always_ends_a_sentence():
    text = "First line is long enough.\nSecond line is also long enough."
    assert [text[a:b] for a, b in notes.split_sentences(text)] == [
        "First line is long enough.",
        "Second line is also long enough.",
    ]
