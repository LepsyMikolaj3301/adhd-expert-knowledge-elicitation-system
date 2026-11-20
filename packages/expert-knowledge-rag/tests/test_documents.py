import logging
from dataclasses import replace

import pytest

from expert_knowledge_core.example import example_record
from expert_knowledge_rag.documents import build_documents, local_id
from expert_knowledge_core.agreement import Agreement
from expert_knowledge_rag.ranking import Grouping, UnitHit


def hit(local: str, rank_score: float, session="S1", kind=None) -> UnitHit:
    return UnitHit(
        id=f"{session}-V001-{local}",
        session_id=session,
        expert_id="X1",
        vignette_id="V001",
        vignette_version=1,
        kind=kind or ("case" if local == "case" else "fragment"),
        highlight_id=None if local == "case" else f"{session}-V001-{local}",
        direction=None,
        embed_text=f"I1 of {local}",
        score=rank_score,
    )


def test_local_id_strips_the_prefix_ingestion_added():
    assert local_id(hit("h3", 1.0)) == "h3"
    assert local_id(hit("case", 1.0)) == "case"
    with pytest.raises(ValueError):
        local_id(replace(hit("h3", 1), id="other-id"))


def test_units_sharing_a_sentence_become_one_note_in_the_rank_of_the_best(record):
    hits = [hit("h3", 0.9), hit("case", 0.8), hit("h1", 0.7)]
    docs = build_documents(hits, {"S1": record})
    assert [d.metadata["unit_ids"] for d in docs] == [
        ["S1-V001-h3", "S1-V001-h1"],
        ["S1-V001-case"],
    ]
    first = docs[0]
    assert first.id == "S1-V001-h3"
    assert first.page_content.count("explains most of this more parsimoniously") == 1
    assert first.metadata["merged"] is True and first.metadata["score"] == 0.9
    assert [w["direction"] for w in first.metadata["patient_words"]] == ["unclear", "away"]
    assert first.metadata["source"] == "expert"


def test_merging_can_be_switched_off(record):
    docs = build_documents([hit("h3", 0.9), hit("h1", 0.7)], {"S1": record}, merge=False)
    assert [d.metadata["unit_ids"] for d in docs] == [["S1-V001-h3"], ["S1-V001-h1"]]
    assert "Q5" in docs[0].page_content and docs[0].metadata["merged"] is False


def test_notes_of_different_sessions_are_never_merged():
    a, b = example_record("S1", "X1"), example_record("S2", "X2")
    hits = [hit("h3", 0.9), hit("h3", 0.8, session="S2")]
    docs = build_documents(hits, {"S1": a, "S2": b})
    assert [d.metadata["session_id"] for d in docs] == ["S1", "S2"]


def test_a_merged_note_keeps_the_rank_order_of_its_units(record):
    # h1 and h2 bridge through Q2.1: ranked h2, case, h1 -> one note at h2's place, one case note
    docs = build_documents([hit("h2", 0.9), hit("case", 0.8), hit("h1", 0.7)], {"S1": record})
    assert docs[0].metadata["unit_ids"] == ["S1-V001-h2", "S1-V001-h1"]
    assert docs[0].metadata["score"] == 0.9


def test_an_unreadable_session_gives_one_note_per_unit_as_embedded(caplog):
    raw = {"responses": [], "session_id": "S1"}  # a ChipDocument, as stored in chips_eval
    with caplog.at_level(logging.WARNING):
        docs = build_documents([hit("h3", 0.9), hit("h1", 0.7)], {"S1": raw})
    assert [d.page_content for d in docs] == ["I1 of h3", "I1 of h1"]
    assert docs[0].metadata["patient_words"] == []
    assert sum("no readable findings record" in m for m in caplog.messages) == 1


def test_a_unit_missing_from_the_record_falls_back(record, caplog):
    docs = build_documents([hit("h9", 0.9)], {"S1": record})
    assert docs[0].page_content == "I1 of h9"


def test_a_session_whose_record_is_missing_falls_back():
    docs = build_documents([hit("h3", 0.9)], {})
    assert docs[0].page_content == "I1 of h3"


def grouping_of(*units: UnitHit, counts=None, k=3, n=4, label="agreed") -> Grouping:
    """One group (id 7) holding `units`; the counts are those of the whole group, not of `units`."""
    agreement = Agreement(span=(0, 10), k=k, n=n, counts=counts or {"away": k}, label=label)
    return Grouping(
        of_highlight={u.highlight_id: 7 for u in units if u.highlight_id},
        agreements={7: agreement},
        members={7: list(units)},
    )


def test_units_of_one_group_become_one_note_with_the_agreement_line():
    a, b = example_record("S1", "X1"), example_record("S2", "X2")
    hits = [hit("h3", 0.9), hit("h3", 0.8, session="S2")]
    docs = build_documents(hits, {"S1": a, "S2": b}, grouping=grouping_of(*hits))
    [note] = docs
    assert note.id == "S1-V001-h3" and note.metadata["score"] == 0.9
    assert note.metadata["unit_ids"] == ["S1-V001-h3", "S2-V001-h3"]
    assert note.metadata["group_id"] == 7 and note.metadata["merged"] is True
    line = note.metadata["agreement"]["line"]
    assert line == "Agreement: 3 of 4 clinicians who answered this text cited it; 3 away (agreed)."
    assert line in note.page_content
    assert note.page_content.count("Clinician ") == 2
    assert "S1" not in note.page_content and "X2" not in note.page_content


def test_a_group_note_counts_clinicians_that_were_not_hits_and_quotes_only_a_few():
    sessions = ["S1", "S2", "S3", "S4", "S5"]
    records = {s: example_record(s, f"X{n}") for n, s in enumerate(sessions)}
    members = [hit("h3", 0.0, session=s) for s in sessions]
    best = [members[0]]
    docs = build_documents(
        best, records, grouping=grouping_of(*members, k=5, n=6, counts={"away": 5})
    )
    [note] = docs
    assert note.metadata["agreement"]["k"] == 5
    assert len(note.metadata["unit_ids"]) == 5, "every clinician of the group is read"
    assert note.page_content.count("Clinician ") == 3, "but at most three are quoted"
    assert note.metadata["expert_ids"] == ["X1"]  # `hit` gives every unit this expert id


def test_case_units_and_units_in_no_group_are_packed_as_before(record):
    hits = [hit("h3", 0.9), hit("case", 0.8), hit("h1", 0.7)]
    plain = build_documents(hits, {"S1": record})
    only_h3 = grouping_of(hits[0])
    docs = build_documents(hits, {"S1": record}, grouping=only_h3)
    by_first = {d.metadata["unit_ids"][0]: d for d in docs}
    assert by_first["S1-V001-case"].page_content == next(
        d.page_content for d in plain if d.metadata["unit_ids"] == ["S1-V001-case"]
    )
    assert "group_id" not in by_first["S1-V001-case"].metadata
    assert "group_id" not in by_first["S1-V001-h1"].metadata
    assert by_first["S1-V001-h3"].metadata["group_id"] == 7


def test_a_group_note_takes_the_place_of_its_best_hit():
    a, b = example_record("S1", "X1"), example_record("S2", "X2")
    hits = [hit("case", 0.95), hit("h3", 0.9, session="S2"), hit("h3", 0.8)]
    docs = build_documents(
        hits, {"S1": a, "S2": b}, grouping=grouping_of(hits[1], hits[2]), merge=False
    )
    assert [d.metadata.get("group_id") for d in docs] == [None, 7]


def test_a_group_whose_best_record_cannot_be_read_falls_back_to_the_plain_note(record):
    hits = [hit("h3", 0.9, session="S2")]  # no record for S2
    docs = build_documents(hits, {"S1": record}, grouping=grouping_of(*hits))
    [note] = docs
    assert "group_id" not in note.metadata and note.page_content == "I1 of h3"
