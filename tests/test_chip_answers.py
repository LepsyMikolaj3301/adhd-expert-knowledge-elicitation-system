"""The rules behind notebooks/answer_vignettes.ipynb: citations, the lock-in, the gold document."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import answer_vignettes as av
import chip_answers as ca
import nbformat
import pytest
from chips_schema import ChipDocument, load_document, to_legacy
from make_fixtures import fixture_dir

from app.elicitation.schema import ElicitationDocument, Vignette, VignetteDesign

CUE = "I reorganised my entire desk instead of starting the report"
CONFOUNDER = "I have barely slept since the move"
TEXT = f"😀 {CUE} and then {CONFOUNDER}. " + " ".join(f"word{i}" for i in range(130))
FIFTEEN = "one two three four five six seven eight nine ten eleven twelve thirteen a15 b15"
TEN = "one two three four five six seven eight nine ten"
NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "answer_vignettes.ipynb"


def vignette(vid: str = "V001", **overrides) -> Vignette:
    fields: dict[str, Any] = {
        "id": vid,
        "version": 1,
        "text": TEXT,
        "framing": "personal_journal",
        "question_ids": ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"],
        "q4_whatif": "the writer had an exam",
        "design": VignetteDesign(purpose="test"),
    }
    return Vignette(**{**fields, **overrides})


def citation(chip: int, quote: str = CUE, direction: str | None = "toward") -> dict:
    start = TEXT.index(quote)
    return {
        "chip": chip,
        "text": quote,
        "span": [start, start + len(quote)],
        "direction": direction,
    }


def entry(**overrides) -> dict:
    return {"started_at": "2026-11-05T10:00:00+00:00", "answers": {}, **overrides}


GATE = {"Q1": FIFTEEN, "Q2": TEN, "Q3": TEN}


# --- adding a citation from a pasted quote ------------------------------------------------------


def test_a_pasted_quote_becomes_a_citation_with_python_offsets():
    citations, status = ca.add_citation([], TEXT, CUE)
    assert status == "added"
    assert citations == [
        {"chip": 1, "text": CUE, "span": [2, 2 + len(CUE)], "direction": None},
    ]


@pytest.mark.parametrize(
    "pasted",
    [f"  {CUE}\n", f'"{CUE}"', f"“{CUE}”", CUE.replace("entire desk", "entire\n  desk")],
)
def test_pasting_tolerates_surrounding_quotes_and_copied_line_breaks(pasted):
    citations, status = ca.add_citation([], TEXT, pasted)
    assert status == "added"
    assert citations[0]["text"] == CUE


def test_half_a_word_grows_to_the_whole_word():
    citations, _ = ca.add_citation([], TEXT, "organised my entire de")
    assert citations[0]["text"] == "reorganised my entire desk"


def test_the_same_passage_twice_is_reported_not_added():
    first, _ = ca.add_citation([], TEXT, CUE)
    again, status = ca.add_citation(first, TEXT, CUE)
    assert status == "duplicate:1"
    assert again == first


def test_a_quote_that_is_not_in_the_text_is_refused():
    assert ca.add_citation([], TEXT, "never written")[1] == "not_found"
    assert ca.add_citation([], TEXT, "   ")[1] == "empty"


def test_a_very_long_quote_is_refused():
    long_text = "word " * 600
    assert ca.add_citation([], long_text, long_text)[1] == "too_long"


# --- chips in answers ---------------------------------------------------------------------------


def test_numbers_in_brackets_are_chips_only_when_the_citation_exists():
    assert ca.to_tokens("[1] and [2], not [3]", 2) == "⟦h1⟧ and ⟦h2⟧, not [3]"
    assert ca.to_display("⟦h1⟧ and ⟦h2⟧, not [3]") == "[1] and [2], not [3]"
    assert ca.unknown_numbers("[1] and [3] and [12]", 2) == [3, 12]


def test_removing_a_citation_renumbers_the_rest_and_their_chips():
    citations = [citation(1), citation(2, CONFOUNDER), citation(3, "word1", None)]
    left, answers = ca.remove_citation(
        citations, {"Q1": "see ⟦h2⟧ and ⟦h3⟧", "Q2": "⟦h2⟧ first", "Q3": "(⟦h2⟧)."}, 2
    )
    assert [(c["chip"], c["text"]) for c in left] == [(1, CUE), (2, "word1")]
    assert answers == {"Q1": "see and ⟦h2⟧", "Q2": "first", "Q3": "()."}


def test_uncited_citations_are_found():
    assert ca.uncited([citation(1), citation(2, CONFOUNDER)], {"Q1": "⟦h2⟧"}) == [1]


# --- what each step needs -----------------------------------------------------------------------


def test_q1_asks_about_either_direction_and_q4_has_its_what_if():
    v = vignette()
    assert "in either direction" in ca.question_text("Q1", v)
    assert "Quote" not in ca.question_text("Q1", v)
    assert "the writer had an exam" in ca.question_text("Q4", v)


def test_open_answers_need_their_word_minimum_and_chips_do_not_count():
    v = vignette()
    chips = " ".join(f"⟦h{n}⟧" for n in range(1, 21))
    assert ca.step_problem(v, entry(answers={"Q2": chips}), "Q2") == (
        "Q2 has 0 of 10 different words."
    )
    assert ca.step_problem(v, entry(answers={"Q2": TEN}), "Q2") is None
    assert ca.step_problem(v, entry(answers={"Q5": "too short"}), "Q5") == (
        "Q5 has 2 of 10 different words."
    )


@pytest.mark.parametrize(
    ("q4", "why", "problem"),
    [
        ({}, "", "Write your working hypothesis in one sentence."),
        ({"hypothesis": "tired"}, "", "Your hypothesis has 1 of 3 different words."),
        ({"hypothesis": "tired not trait"}, "", "Pick a point on the scale (0 means no change)."),
        ({"hypothesis": "tired not trait", "shift": 0}, "", None),
        ({"hypothesis": "tired not trait", "shift": 1}, "", "Say which way your hypothesis moves."),
        (
            {"hypothesis": "tired not trait", "shift": -1},
            "exam",
            "Why? has 1 of 5 different words.",
        ),
        ({"hypothesis": "tired not trait", "shift": -1}, "because of the exam today", None),
    ],
)
def test_q4_names_what_is_missing(q4, why, problem):
    answers = {"Q4": why} if why else {}
    assert ca.step_problem(vignette(), entry(q4=q4, answers=answers), "Q4") == problem


def test_q6_needs_a_rating_or_insufficient_information():
    v = vignette()
    assert (
        ca.step_problem(v, entry(), "Q6")
        == "Pick a rating from 1 to 5, or “Insufficient information”."
    )
    assert ca.step_problem(v, entry(rating=3), "Q6") is None
    assert ca.step_problem(v, entry(rating=None, insufficient=True), "Q6") is None


def test_resuming_stays_on_q3_until_locked_then_moves_on():
    v = vignette()
    assert ca.first_open_step(v, entry()) == "Q1"
    assert ca.first_open_step(v, entry(answers={"Q1": FIFTEEN})) == "Q2"
    assert ca.first_open_step(v, entry(answers=GATE)) == "Q3"
    locked = entry(answers=GATE, gate_passed_at="now")
    assert ca.first_open_step(v, locked) == "Q4"
    finished = entry(
        answers={**GATE, "Q5": TEN},
        gate_passed_at="now",
        q4={"hypothesis": "tired not trait", "shift": 0},
        rating=2,
    )
    assert ca.first_open_step(v, finished) == "review"


# --- the lock-in --------------------------------------------------------------------------------


def test_the_lock_in_needs_every_citation_to_have_a_direction():
    v = vignette()
    undirected = entry(answers=GATE, highlights=[citation(1), citation(2, CONFOUNDER, None)])
    assert ca.lock_problem(v, undirected) == "Choose a direction for citation 2."
    assert ca.lock_problem(v, entry(answers=GATE, highlights=[citation(1)])) is None


def test_the_lock_in_needs_the_gate_answers():
    assert ca.lock_problem(vignette(), entry(answers={"Q1": FIFTEEN})) == (
        "Q2 has 0 of 10 different words."
    )


def test_locking_in_records_when_and_how_many_citations():
    e = entry(answers=GATE, highlights=[citation(1), citation(2, CONFOUNDER)])
    ca.lock_in(e)
    assert e["gate_passed_at"]
    assert e["locked_highlights"] == 2
    first = e["gate_passed_at"]
    e["highlights"].append(citation(3, "word1"))
    ca.lock_in(e)
    assert e["gate_passed_at"] == first, "the first time recorded stands"
    assert e["locked_highlights"] == 2


def test_soft_warnings_never_block():
    v = vignette()
    none = entry(answers=GATE)
    assert ca.lock_problem(v, none) is None
    assert "no citations" in ca.lock_warnings(none)[0]
    some = entry(answers=GATE, highlights=[citation(1)])
    assert ca.lock_problem(v, some) is None
    assert "not cited" in ca.lock_warnings(some)[0]


def test_a_long_q1_without_chips_asks_which_fragments_it_is_about():
    long = " ".join(f"word{i}" for i in range(70))
    assert ca.q1_nudge(long)
    assert not ca.q1_nudge(f"⟦h1⟧ {long}")
    assert not ca.q1_nudge("short answer")


def test_accepting_needs_every_question_and_every_direction():
    v = vignette()
    finished = entry(
        answers={**GATE, "Q5": TEN},
        gate_passed_at="now",
        q4={"hypothesis": "tired not trait", "shift": 0},
        rating=2,
        highlights=[citation(1)],
    )
    assert ca.accept_problem(v, finished) is None
    assert ca.accept_problem(v, {**finished, "rating": None}) is not None
    late = {**finished, "highlights": [citation(1), citation(2, CONFOUNDER, None)]}
    assert ca.accept_problem(v, late) == "Choose a direction for citation 2."


# --- loading the vignettes ----------------------------------------------------------------------


def _write_source(root: Path, *ids: str) -> None:
    folder = fixture_dir("silver", ca.SOURCE, root / "fixtures") / "vignettes"
    folder.mkdir(parents=True)
    for vid in ids:
        v = vignette(vid, question_ids=["Q1", "Q2", "Q3", "Q5", "Q6"], q4_whatif=None)
        (folder / f"{vid}.json").write_text(v.model_dump_json())


def test_the_chips_source_lives_in_its_own_folder(tmp_path):
    root = tmp_path / "fixtures"
    assert fixture_dir("gold", "chips", root) == tmp_path / "fixtures_chips" / "synthetic" / "gold"
    assert fixture_dir("gold", "synthetic", root) == root / "synthetic" / "gold"


def test_vignettes_get_their_what_if_and_all_six_questions(tmp_path, monkeypatch):
    _write_source(tmp_path, "V001", "V002")
    monkeypatch.setattr(av, "FIXTURES", tmp_path / "fixtures")
    gold, vignettes, draft = ca.open_session("E01", "psychiatrist", "silver", "fixed")
    assert gold == tmp_path / "fixtures_chips" / "synthetic" / "gold"
    assert draft["order"] == ["V001", "V002"]
    v = vignettes["V001"]
    assert v.question_ids == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
    assert v.q4_whatif
    assert v.content_hash == vignette().content_hash, "the text itself must not change"
    assert (gold / "vignettes" / "V001.json").exists()


def test_a_vignette_without_a_what_if_stops_the_session(tmp_path, monkeypatch):
    _write_source(tmp_path, "V999")
    monkeypatch.setattr(av, "FIXTURES", tmp_path / "fixtures")
    with pytest.raises(av.SetupError, match="V999"):
        ca.open_session("E01", "psychiatrist", "silver", "fixed")


# --- the gold document --------------------------------------------------------------------------


def _draft() -> dict:
    return {
        "expert_id": "E01",
        "order": ["V001", "V002"],
        "skipped": [],
        "answers": {
            "V001": entry(
                answers={
                    "Q1": f"⟦h1⟧ {FIFTEEN}",
                    "Q2": TEN,
                    "Q3": TEN,
                    "Q4": "  ⟦h2⟧ because of the exam today  ",
                    "Q5": TEN,
                },
                highlights=[citation(1), citation(2, CONFOUNDER, "away")],
                locked_highlights=1,
                gate_passed_at="2026-11-05T10:05:00+00:00",
                q4={"hypothesis": "tired not trait", "shift": 1, "toward": "less_adhd"},
                rating=2,
                done=True,
                submitted_at="2026-11-05T10:10:00+00:00",
            ),
            "V002": entry(answers={"Q1": "unfinished"}),
        },
    }


def test_the_document_keeps_citations_chips_q4_and_the_lock_count():
    doc = ca.build_document(_draft(), {"V001": vignette()}, "DOC-0001", datetime.now(UTC))
    assert isinstance(doc, ChipDocument)
    assert doc.schema_version == "1.1-chips"
    [response] = doc.responses
    assert [h.chip for h in response.highlights] == [1, 2]
    assert response.highlights[1].direction == "away"
    assert response.locked_highlights == 1
    assert response.answers["Q4"] == "⟦h2⟧ because of the exam today"
    assert response.q4 is not None
    assert response.q4.shift == 1
    assert response.quoted_fragments == [CUE, CONFOUNDER]


def test_a_vignette_with_no_citations_can_still_be_finished():
    draft = _draft()
    e = draft["answers"]["V001"]
    e["highlights"], e["locked_highlights"] = [], 0
    e["answers"] = {"Q1": FIFTEEN, "Q2": TEN, "Q3": TEN, "Q5": TEN}
    e["q4"] = {"hypothesis": "tired not trait", "shift": 0}
    doc = ca.build_document(draft, {"V001": vignette()}, "DOC-0001", datetime.now(UTC))
    assert doc.responses[0].highlights == []


def test_a_why_left_on_the_screen_at_zero_is_not_written():
    draft = _draft()
    e = draft["answers"]["V001"]
    e["q4"] = {"hypothesis": "tired not trait", "shift": 0, "toward": "other"}
    doc = ca.build_document(draft, {"V001": vignette()}, "DOC-0001", datetime.now(UTC))
    assert "Q4" not in doc.responses[0].answers
    assert doc.responses[0].q4 is not None
    assert doc.responses[0].q4.toward is None


def test_synthetic_ids_cannot_write_gold():
    draft = {**_draft(), "expert_id": "SYN-E01"}
    with pytest.raises(ValueError, match="synthetic"):
        ca.build_document(draft, {"V001": vignette()}, "DOC-0001", datetime.now(UTC))


def test_finishing_writes_the_document_and_manifest_and_drops_the_draft(tmp_path, monkeypatch):
    _write_source(tmp_path, "V001", "V002")
    monkeypatch.setattr(av, "FIXTURES", tmp_path / "fixtures")
    gold, vignettes, _ = ca.open_session("E01", "psychiatrist", "silver", "fixed")
    draft = _draft()
    av.write_json(av.draft_path_for(gold, "E01"), draft)
    doc = ca.finish_draft(gold, draft, vignettes, "silver")
    assert doc.session_id == "DOC-0001"
    assert not av.draft_path_for(gold, "E01").exists()
    written = json.loads((gold / "documents" / "DOC-0001.json").read_text())
    assert written["schema_version"] == "1.1-chips"
    manifest = json.loads((gold / "manifest.json").read_text())
    kinds = {(e["id"], e["kind"]): e for e in manifest["entries"]}
    assert kinds[("DOC-0001", "document")]["source"] == "human:notebook"
    assert ("V001", "vignette") in kinds
    # The same expert isn't asked again what they have answered.
    _, _, resumed = ca.open_session("E01", None, "silver", "fixed")
    assert resumed["order"] == ["V002"]


# --- older tools ---------------------------------------------------------------------------------


def test_older_tools_read_a_chip_document_as_a_plain_one(tmp_path):
    doc = ca.build_document(_draft(), {"V001": vignette()}, "DOC-0001", datetime.now(UTC))
    path = tmp_path / "DOC-0001.json"
    path.write_text(doc.model_dump_json())
    plain = load_document(path)
    assert type(plain) is ElicitationDocument
    [response] = plain.responses
    assert response.answers["Q1"].startswith(f'"{CUE}" ')
    assert response.answers["Q4"].startswith(f'"{CONFOUNDER}" ')
    assert response.q4 is not None
    assert response.q4.shift == 1
    assert to_legacy(doc).responses[0].quoted_fragments == [CUE, CONFOUNDER]


def test_a_plain_document_loads_as_it_is(tmp_path):
    doc = to_legacy(ca.build_document(_draft(), {"V001": vignette()}, "D", datetime.now(UTC)))
    path = tmp_path / "doc.json"
    path.write_text(doc.model_dump_json())
    assert load_document(path) == doc


# --- the notebook itself, with its buttons pressed --------------------------------------------


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    """Runs the notebook's own code cells, with the data folders pointed at a temporary place."""
    _write_source(tmp_path, "V001", "V002")
    monkeypatch.setattr(av, "FIXTURES", tmp_path / "fixtures")
    namespace: dict = {}
    for cell in nbformat.read(NOTEBOOK, as_version=4).cells:
        if cell.cell_type == "code":
            exec(cell.source, namespace)  # noqa: S102
    board = namespace["dashboard"]
    board.expert.value = "E01"
    board.role.value = "psychiatrist"
    board.order.value = "fixed"
    board._start()
    return board


def _shown_question(board) -> str:
    return board.qhead.value


def _type(board, text: str) -> None:
    board.text.value = text


def _add(board, quote: str) -> None:
    board.quote.value = quote
    board._add_citation()


def test_the_notebook_opens_on_q1_with_nothing_lit(dashboard):
    assert dashboard.source.value == ("chips", "silver")
    assert "in either direction" in _shown_question(dashboard)
    assert "<mark" not in dashboard.vignette.value
    assert "writer had an exam" not in _shown_question(dashboard)


def test_the_notebook_adds_a_citation_and_lights_it_only_on_show(dashboard):
    _add(dashboard, CUE)
    assert [c["text"] for c in dashboard.entry["highlights"]] == [CUE]
    assert dashboard.quote.value == "", "the box empties for the next quote"
    assert "<mark" not in dashboard.vignette.value
    dashboard._toggle_show(1)
    assert f">{CUE}</mark>" in dashboard.vignette.value
    dashboard._toggle_show(1)
    assert "<mark" not in dashboard.vignette.value


def test_the_notebook_says_why_a_quote_was_not_added(dashboard):
    _add(dashboard, "never written")
    assert dashboard.entry.get("highlights", []) == []
    assert "exact" in dashboard.msg.value
    assert dashboard.quote.value == "never written", "kept, so it can be corrected"


def test_cite_appends_a_number_that_is_stored_as_a_chip(dashboard):
    _add(dashboard, CUE)
    _type(dashboard, "This reads as avoidance")
    dashboard._cite(1)
    assert dashboard.text.value == "This reads as avoidance [1] "
    assert dashboard.entry["answers"]["Q1"] == "This reads as avoidance ⟦h1⟧ "
    assert 'class="av-chip"' in dashboard.helper.value


def test_a_number_typed_by_hand_is_also_a_chip(dashboard):
    _add(dashboard, CUE)
    _type(dashboard, "[1] typed by hand")
    assert dashboard.entry["answers"]["Q1"] == "⟦h1⟧ typed by hand"


def test_next_is_refused_until_the_answer_is_long_enough(dashboard):
    _type(dashboard, "too short")
    dashboard._next()
    assert dashboard.steps[dashboard.k] == "Q1"
    assert "2 of 15 different words" in dashboard.msg.value
    _type(dashboard, FIFTEEN)
    dashboard._next()
    assert dashboard.steps[dashboard.k] == "Q2"


def _to_q3(board) -> None:
    _type(board, FIFTEEN)
    board._next()
    _type(board, TEN)
    board._next()
    _type(board, TEN)


def test_q4_stays_hidden_and_unreachable_until_the_lock_in(dashboard):
    _to_q3(dashboard)
    assert dashboard.next_btn.description == "Lock in results"
    dashboard._go(dashboard.steps.index("Q4"))
    assert dashboard.steps[dashboard.k] == "Q3"
    assert "exam" not in _shown_question(dashboard)
    assert not dashboard.entry.get("gate_passed_at")


def test_locking_in_asks_first_then_opens_q4(dashboard):
    _add(dashboard, CUE)
    _to_q3(dashboard)
    dashboard._next()
    assert "direction for citation 1" in dashboard.msg.value
    assert not dashboard.entry.get("gate_passed_at")

    dashboard._set_direction(1, "toward")
    dashboard._next()
    assert dashboard.next_btn.description == "Confirm: lock in results"
    assert "not cited" in dashboard.msg.value
    assert not dashboard.entry.get("gate_passed_at")

    dashboard._next()
    assert dashboard.entry["gate_passed_at"]
    assert dashboard.entry["locked_highlights"] == 1
    assert dashboard.steps[dashboard.k] == "Q4"
    assert "writer had an exam" in _shown_question(dashboard)
    assert dashboard.q4_shift.value is None, "the scale has no default"


def test_moving_away_cancels_a_lock_in_waiting_for_confirmation(dashboard):
    _to_q3(dashboard)
    dashboard._next()
    assert dashboard.next_btn.description == "Confirm: lock in results"
    dashboard._back()
    dashboard._next()
    assert dashboard.next_btn.description == "Lock in results"
    assert not dashboard.entry.get("gate_passed_at")


def _lock(board) -> None:
    _to_q3(board)
    board._next()
    board._next()


def test_after_the_lock_in_q1_is_read_only_and_locked_citations_are_fixed(dashboard):
    _add(dashboard, CUE)
    dashboard._set_direction(1, "toward")
    _lock(dashboard)
    dashboard._go(0)
    assert dashboard.text.disabled
    assert "locked" in _shown_question(dashboard)
    before = list(dashboard.entry["highlights"])
    dashboard._remove(1)
    dashboard._set_direction(1, "away")
    assert dashboard.entry["highlights"] == before


def test_new_citations_after_the_lock_in_stay_editable(dashboard):
    _add(dashboard, CUE)
    dashboard._set_direction(1, "toward")
    _lock(dashboard)
    _add(dashboard, CONFOUNDER)
    assert len(dashboard.entry["highlights"]) == 2
    dashboard._set_direction(2, "away")
    assert dashboard.entry["highlights"][1]["direction"] == "away"
    dashboard._remove(2)
    assert len(dashboard.entry["highlights"]) == 1
    assert dashboard.entry["locked_highlights"] == 1


def test_removing_a_cited_citation_asks_first(dashboard):
    _add(dashboard, CUE)
    _type(dashboard, "[1] something")
    dashboard._remove(1)
    assert len(dashboard.entry["highlights"]) == 1
    assert "again" in dashboard.msg.value
    dashboard._remove(1)
    assert dashboard.entry["highlights"] == []
    assert dashboard.text.value == "something"


def test_a_whole_vignette_from_q1_to_the_document(dashboard):
    _add(dashboard, CUE)
    dashboard._set_direction(1, "toward")
    dashboard._cite(1)
    dashboard.text.value = dashboard.text.value + FIFTEEN
    dashboard._next()
    _type(dashboard, TEN)
    dashboard._next()
    _type(dashboard, TEN)
    dashboard._next()
    dashboard._next()

    dashboard.q4_hyp.value = "tired not a trait"
    dashboard.q4_shift.value = 1
    dashboard.q4_toward.value = "less_adhd"
    _add(dashboard, CONFOUNDER)
    dashboard._set_direction(2, "away")
    dashboard._cite(2)
    assert dashboard.q4_why.value == "[2] "
    dashboard.q4_why.value += "because of the exam today"
    dashboard._next()
    _type(dashboard, TEN)
    dashboard._next()
    dashboard.rating.value = 2
    dashboard._next()
    assert dashboard.steps[dashboard.k] == "review"
    dashboard._next()
    assert dashboard.entry_for("V001")["done"]
    assert dashboard.vid == "V002", "the next vignette opens"

    dashboard._finish()
    assert "Confirm" in dashboard.finish_btn.description
    dashboard._finish()
    assert "DOC-0001" in dashboard.msg.value
    documents = list(dashboard.gold.glob("documents/DOC-*.json"))
    assert len(documents) == 1
    doc = ChipDocument.model_validate_json(documents[0].read_text())
    [response] = doc.responses
    assert response.locked_highlights == 1
    assert [h.chip for h in response.highlights] == [1, 2]
    assert response.answers["Q1"].startswith("⟦h1⟧ ")
    assert response.answers["Q4"].startswith("⟦h2⟧ ")


def test_a_draft_resumes_where_it_was_left(dashboard, tmp_path):
    _add(dashboard, CUE)
    _type(dashboard, FIFTEEN)
    dashboard._next()
    dashboard._pause()
    gold, vignettes, draft = ca.open_session("E01", None, "silver", "fixed")
    assert draft["answers"]["V001"]["highlights"][0]["text"] == CUE
    assert ca.first_open_step(vignettes["V001"], draft["answers"]["V001"]) == "Q2"
