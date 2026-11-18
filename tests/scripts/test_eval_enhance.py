"""Tests for eval_enhance.py: the sample, the four cells of metrics, and the blinded judging."""

import json

import eval_enhance as ee

NOTE = ee.Item("S1/V001/Q1", "Q?", "⟦h1⟧ - late start, mild", {1: "I started late in the evening"})
PROSE = ee.Item("S1/V001/Q2", "Q?", "⟦h1⟧ could be ordinary tiredness.", {1: "I was tired"})


def raw(text: str) -> str:
    return json.dumps({"answer": text})


def test_note_style_answers_are_found():
    assert NOTE.note and not PROSE.note
    assert ee.is_note("- one thing\n- another thing")
    assert not ee.is_note("A sentence. - not a list")


def test_the_sample_keeps_every_note_and_is_the_same_each_time():
    others = [ee.Item(f"S/V/{n}", "Q?", f"Plain answer {n}.", {}) for n in range(50)]
    first = ee.sample([NOTE, *others], 10, seed=3)
    assert NOTE in first and len(first) == 11
    assert first == ee.sample([NOTE, *others], 10, seed=3)


def rows():
    replies = [
        # v1 copies the passage, in the patient's voice: the old checks keep it, the new refuse it
        {"key": NOTE.key, "arm": "v1", "raw": raw("⟦h1⟧ - I started late in the evening, mild.")},
        {"key": PROSE.key, "arm": "v1", "raw": raw("⟦h1⟧ could be ordinary tiredness.")},
        {"key": NOTE.key, "arm": "v2", "raw": raw("⟦h1⟧ shows a late start, which is mild.")},
        {"key": PROSE.key, "arm": "v2", "raw": "not json"},
    ]
    return ee.judged_rows([NOTE, PROSE], replies)


def test_the_cells_separate_the_prompt_from_the_checks():
    m = ee.metrics(rows())
    assert m["all/v1/old"]["accepted"]["rate"] == 1.0
    assert m["all/v1/new"]["accepted"]["rate"] == 0.5
    assert m["all/v1/new"]["refused_because"] == {"voice": 1}  # one passage word: no leak yet
    assert m["notes/v1/old"]["voice"]["rate"] == 1.0
    assert m["notes/v2/new"]["accepted"]["rate"] == 1.0
    assert m["notes/v2/new"]["leak"]["rate"] == 0.0 and m["notes/v2/new"]["voice"]["rate"] == 0.0
    assert m["all/v2/old"]["refused_because"] == {"not_json": 1}


def test_judging_is_blinded_and_comes_back_to_the_right_arm(tmp_path):
    r = rows()
    n = ee.write_blocks([NOTE, PROSE], r, tmp_path)
    assert n == 2  # v1 and v2 on the note changed it; the unchanged prose reply is not judged
    block = (tmp_path / "judge" / "blocks" / "block_01.md").read_text()
    assert "v1" not in block and "v2" not in block and "I started late in the evening" in block
    key = json.loads((tmp_path / "judge" / "key.json").read_text())
    grades = {
        pid: {
            "meaning": "added" if k["arm"] == "v1" else "same",
            "voice_ok": k["arm"] == "v2",
            "fuller": 3,
        }
        for pid, k in key.items()
    }
    for judge in ("haiku", "sonnet"):
        (tmp_path / "judge" / judge).mkdir()
        (tmp_path / "judge" / judge / "block_01.json").write_text(json.dumps(grades))
    j = ee.judge_summary(r, key, ee.load_grades(tmp_path))
    assert j["haiku/notes/v1/old"]["meaning_same"]["rate"] == 0.0
    assert j["haiku/notes/v2/new"]["meaning_same"]["rate"] == 1.0
    assert j["haiku/notes/v1/new"]["meaning_same"] == {"n": 0}  # the new checks refuse that reply
    assert j["agreement"]["meaning_same"] == 1.0
    report = ee.report(ee.metrics(r), j, {"model": "m", "answers": 2, "notes": 1, "seed": 1})
    assert "meaning kept 0.0% → 100.0% (not lower: yes)" in report
