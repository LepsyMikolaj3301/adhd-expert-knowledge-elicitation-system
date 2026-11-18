"""The retrievers' orchestration over a store that answers from a script (no database)."""

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from expert_knowledge_core.example import example_record
from expert_knowledge_rag import (
    ExpertFilter,
    ExpertKnowledgeStore,
    ExpertQuestionRetriever,
    PatientTextRetriever,
)


class ScriptedStore(ExpertKnowledgeStore):
    """Answers each `run` with the next scripted list of row lists; remembers what it was asked."""

    def __init__(self, *script):
        super().__init__("postgresql://unused")
        self.script = list(script)
        self.asked: list[list] = []

    def run(self, queries):
        self.asked.append(list(queries))
        return self.script.pop(0)

    async def arun(self, queries):
        return self.run(queries)


def unit_row(local: str, score: float = 0.03, **extra) -> dict:
    return {
        "id": f"S1-V001-{local}", "session_id": "S1", "expert_id": "X1", "vignette_id": "V001",
        "vignette_version": 1, "kind": "case" if local == "case" else "fragment",
        "highlight_id": None if local == "case" else f"S1-V001-{local}", "direction": None,
        "embed_text": f"I1 of {local}", "score": score, "vector": None,
    } | extra  # fmt: skip


SESSIONS = [{"id": "S1", "document": example_record("S1", "X1")}]
EMB = DeterministicFakeEmbedding(size=1024)


def question(store, **kw):
    return ExpertQuestionRetriever(store=store, embeddings=EMB, **kw)


def test_question_retrieval_searches_then_loads_the_sessions_of_the_hits():
    store = ScriptedStore([[unit_row("h3"), unit_row("case", 0.02)]], [SESSIONS])
    docs = question(store, k=2).invoke("How do I tell sleep deprivation from attention problems?")
    assert [d.metadata["unit_ids"] for d in docs] == [["S1-V001-h3"], ["S1-V001-case"]]
    assert docs[0].page_content.startswith("Teaching case V001")
    units_query, params = store.asked[0][0]
    assert params["dense"].startswith("[") and params["sparse"]
    assert store.asked[1][0][1] == {"ids": ["S1"]}
    assert "LIMIT 8" in units_query.as_string()  # k * overfetch


def test_k_can_be_given_per_call_and_sets_how_many_units_are_fetched():
    store = ScriptedStore([[unit_row("h3"), unit_row("case", 0.02)]], [SESSIONS])
    docs = question(store, k=4).invoke("sleep deprivation", k=1)
    assert len(docs) == 1
    assert "LIMIT 4" in store.asked[0][0][0].as_string()  # 1 note * overfetch 4


def test_k_cuts_the_notes():
    store = ScriptedStore([[unit_row("h3"), unit_row("case", 0.02)]], [SESSIONS])
    assert len(question(store, k=1).invoke("sleep deprivation")) == 1


def test_no_hits_is_an_empty_list_without_loading_sessions():
    store = ScriptedStore([[]])
    assert question(store).invoke("sleep deprivation") == []
    assert len(store.asked) == 1


def test_a_blank_query_asks_nothing():
    store = ScriptedStore()
    assert question(store).invoke("   ") == []
    assert store.asked == []


def test_a_query_of_stopwords_falls_back_to_dense_in_hybrid_mode():
    store = ScriptedStore([[]])
    question(store).invoke("the of and")
    _, params = store.asked[0][0]
    assert params["sparse"] is None and params["dense"]


def test_a_query_of_stopwords_has_no_match_in_bm25_mode():
    store = ScriptedStore()
    assert question(store, search="bm25").invoke("the of and") == []
    assert store.asked == []


def test_bm25_mode_never_embeds():
    class NoEmbeddings(DeterministicFakeEmbedding):
        def embed_query(self, text):
            raise AssertionError("embedded")

    store = ScriptedStore([[]])
    ExpertQuestionRetriever(store=store, embeddings=NoEmbeddings(size=1024), search="bm25").invoke(
        "sleep deprivation"
    )
    assert store.asked[0][0][1]["dense"] is None


def test_the_wrong_embedding_width_is_a_clear_error():
    store = ScriptedStore()
    with pytest.raises(ValueError, match="bge-m3"):
        ExpertQuestionRetriever(store=store, embeddings=DeterministicFakeEmbedding(size=8)).invoke(
            "x y z"
        )


def test_near_duplicate_case_units_are_pushed_down():
    near = "[1,0]"
    store = ScriptedStore(
        [[unit_row("case", vector=near), unit_row("h3"), unit_row("h1", vector=None)]],
        [SESSIONS],
    )
    docs = question(store, k=3, merge_shared=False).invoke("sleep deprivation")
    assert docs[0].metadata["kinds"] == ["case"]  # nothing to be a duplicate of: kept first


async def test_async_matches_sync():
    rows = [unit_row("h3"), unit_row("case", 0.02)]
    sync = question(ScriptedStore([rows], [SESSIONS]), k=2).invoke("sleep deprivation")
    asynchronous = await question(ScriptedStore([rows], [SESSIONS]), k=2).ainvoke(
        "sleep deprivation"
    )
    assert [d.metadata["unit_ids"] for d in sync] == [d.metadata["unit_ids"] for d in asynchronous]


# --- patient text ------------------------------------------------------------------------------


def patient(store, **kw):
    return PatientTextRetriever(store=store, embeddings=EMB, **kw)


def test_every_sentence_searches_the_cues_and_scores_add_up():
    cue_rows = [
        [{"cue_id": 1, "score": 0.1}, {"cue_id": 2, "score": 0.05}],
        [{"cue_id": 2, "score": 0.1}],
    ]
    unit_rows = [
        unit_row("h3") | {"cue_id": 1, "context_ids": [2]},
        unit_row("h1") | {"cue_id": 2, "context_ids": None},
    ]
    store = ScriptedStore(cue_rows, [unit_rows], [SESSIONS])
    docs = patient(store, k=4, merge_shared=False).invoke(
        "My hands won't stop trembling at work. Nights are short lately."
    )
    assert len(store.asked[0]) == 2  # one cue search per sentence
    assert [d.metadata["unit_ids"][0] for d in docs] == ["S1-V001-h3", "S1-V001-h1"]
    asked_ids = store.asked[1][0][1]["cue_ids"]
    assert sorted(asked_ids) == [1, 2]


def test_no_cue_match_returns_nothing():
    store = ScriptedStore([[], []])
    assert patient(store).invoke("Something unrelated entirely. Truly.") == []
    assert len(store.asked) == 1


def test_a_blank_patient_text_asks_nothing():
    store = ScriptedStore()
    assert patient(store).invoke("") == []


def test_the_vignette_filter_is_part_of_the_cue_search():
    store = ScriptedStore([[]])
    patient(store, filter=ExpertFilter(exclude_vignettes=["V001"])).invoke(
        "My hands tremble a lot."
    )
    query, params = store.asked[0][0]
    assert params["f_exclude"] == ["V001"]


async def test_async_patient_matches_sync():
    cue_rows = [[{"cue_id": 1, "score": 0.1}]]
    units = [[unit_row("h3") | {"cue_id": 1, "context_ids": None}]]
    sync = patient(ScriptedStore(cue_rows, units, [SESSIONS])).invoke("My hands tremble a lot.")
    other = await patient(ScriptedStore(cue_rows, units, [SESSIONS])).ainvoke(
        "My hands tremble a lot."
    )
    assert [d.metadata["unit_ids"] for d in sync] == [d.metadata["unit_ids"] for d in other]
