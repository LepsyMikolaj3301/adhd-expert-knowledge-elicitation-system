import logging
from dataclasses import replace

import pytest

from expert_knowledge_core.example import example_record
from expert_knowledge_rag.documents import build_documents, local_id
from expert_knowledge_rag.ranking import UnitHit


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
