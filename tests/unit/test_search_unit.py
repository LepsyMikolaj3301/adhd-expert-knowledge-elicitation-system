"""The admin's test search without a database: embeddings, cosine, and which retriever is built."""

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.core.errors import DomainError
from app.knowledge import embedding, ingest, search
from app.knowledge.schemas import KnowledgeSearchRequest
from expert_knowledge_rag import ExpertQuestionRetriever, PatientTextRetriever


@pytest.mark.parametrize(
    ("a", "b", "value"),
    [
        ([1, 0], [1, 0], 1.0),
        ([1, 0], [0, 1], 0.0),
        ([1, 0], [-1, 0], -1.0),
        ([2, 0], [5, 0], 1.0),  # the length does not matter
        ([0, 0], [1, 1], 0.0),  # a zero vector is not a division by zero
    ],
)
def test_cosine_is_the_angle_between_the_vectors(a, b, value):
    assert search._cosine(a, b) == pytest.approx(value)


def test_a_pgvector_text_is_parsed_into_floats():
    assert search._parse("[1,2.5,-3e-2]") == [1.0, 2.5, -0.03]


async def test_the_embedder_remembers_what_it_embedded(monkeypatch):
    async def embed_texts(texts):
        return [[float(len(t)), 1.0] for t in texts]

    monkeypatch.setattr(embedding, "embed_texts", embed_texts)
    embeddings = search._Embeddings()
    assert await embeddings.aembed_query("abc") == [3.0, 1.0]
    assert await embeddings.aembed_documents(["a", "bb"]) == [[1.0, 1.0], [2.0, 1.0]]
    assert embeddings.queries == {"abc": [3.0, 1.0], "a": [1.0, 1.0], "bb": [2.0, 1.0]}


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("down"),
        httpx.ReadTimeout("slow"),
        OSError("refused"),
        RuntimeError("no model"),
    ],
)
async def test_an_unreachable_model_is_a_503_not_a_crash(monkeypatch, error):
    async def embed_texts(texts):
        raise error

    monkeypatch.setattr(embedding, "embed_texts", embed_texts)
    with pytest.raises(DomainError) as raised:
        await search._Embeddings().aembed_query("q")
    assert (raised.value.code, raised.value.status_code) == ("embedding_unavailable", 503)


def test_the_embedder_is_async_only():
    with pytest.raises(NotImplementedError):
        search._Embeddings().embed_query("q")
    with pytest.raises(NotImplementedError):
        search._Embeddings().embed_documents(["q"])


@pytest.mark.parametrize(
    ("mode", "kind"),
    [("question", ExpertQuestionRetriever), ("patient_text", PatientTextRetriever)],
)
def test_the_mode_picks_the_retriever_and_every_hit_is_one_unit(mode, kind):
    request = KnowledgeSearchRequest(query="q", mode=mode, k=5)
    retriever = search._retriever(request, search._Embeddings())
    assert type(retriever) is kind
    assert retriever.k == 5 and retriever.merge_shared is False
    assert retriever.filter.include_synthetic is True  # the admin sees the test accounts' units


# --- ingestion helpers -------------------------------------------------------------------------


def test_a_vector_is_written_as_pgvector_text():
    assert ingest._vec([1.0, 0.25, 1 / 3]) == "[1,0.25,0.33333333]"


def test_a_span_is_a_pair_of_ints():
    assert ingest._span([3, 9]) == {"a": 3, "b": 9}


@pytest.mark.parametrize(
    "value",
    ["2026-01-05T09:16:00", datetime(2026, 1, 5, 9, 16), "2026-01-05T09:16:00+00:00"],
)
def test_a_time_without_a_zone_is_utc(value):
    assert ingest._as_time(value) == datetime(2026, 1, 5, 9, 16, tzinfo=UTC)


def test_review_events_keep_ids_and_kinds_only_for_what_was_kept():
    created = datetime(2026, 1, 5, tzinfo=UTC)
    row = SimpleNamespace(created_at=created, updated_at=created, check_outcome="skipped")
    record = {
        "flags_shown": [{"highlight": "h1", "message": "x"}, {"highlight": "h9", "message": "y"}],
        "corrections": [
            {
                "kind": "sentence_moved",
                "sentence": "Q1.1",
                "before": ["h1"],
                "after": ["h2"],
                "at": "2026-01-05T10:00:00",
            },
            {
                "kind": "sentence_moved",
                "sentence": "Q9.9",
                "before": [],
                "after": [],
                "at": "2026-01-05T10:01:00",
            },
            {
                "kind": "toggle_changed",
                "highlight": "h1",
                "before": "away",
                "after": "toward",
                "after_flag": True,
                "at": "2026-01-05T10:02:00",
            },
            {
                "kind": "toggle_changed",
                "highlight": "h9",
                "before": "a",
                "after": "b",
                "after_flag": False,
                "at": "2026-01-05T10:03:00",
            },
        ],
    }
    events = ingest._events(record, {"h1"}, {"Q1.1"}, row)
    assert [kind for kind, _, _ in events] == [
        "flag_shown", "sentence_moved", "toggle_changed", "skipped"
    ]  # fmt: skip
    assert events[1][1] == {"sentence": "Q1.1", "before": ["h1"], "after": ["h2"]}


def test_an_answer_that_was_not_skipped_has_no_skipped_event():
    row = SimpleNamespace(
        created_at=datetime(2026, 1, 5, tzinfo=UTC), updated_at=None, check_outcome="done"
    )
    assert ingest._events({}, set(), set(), row) == []
