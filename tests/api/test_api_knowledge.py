"""The admin's view of the knowledge base: the ingested units with how they were cut, and a test
search that runs the platform's own retrievers over them."""

import pytest
from api_helpers import CUE, admin_api, expert_api
from test_api_pipeline import chips, ingested_single


async def _fragment(admin) -> dict:
    listed = await admin.ok("GET", "/knowledge-units", params={"status": "ingested"})
    return next(u for u in listed if u["kind"] == "fragment")


async def test_the_list_says_how_each_unit_was_cut_and_what_is_embedded(models):
    admin, expert, assignment_id = await ingested_single(models)
    listed = await admin.ok("GET", "/knowledge-units", params={"status": "ingested"})
    by_kind = {u["kind"]: u for u in listed}
    fragment, case = by_kind["fragment"], by_kind["case"]

    assert fragment["highlight_id"] == "h1" and case["highlight_id"] is None
    assert fragment["patient_words"] == CUE
    assert fragment["expert_pseudonym"] == expert.pseudonym
    assert fragment["framing"] == "personal_journal"
    # What gets embedded: the reviewed text with its header.
    assert fragment["embed_text"].endswith(fragment["text"])
    assert "embed_text_combined" not in fragment
    # Every sentence says which question it came from and how it was filed.
    assert fragment["sentences"]
    assert {s["question_id"] for s in fragment["sentences"]} <= {"Q1", "Q2", "Q3", "Q5"}
    assert all(s["assigned_by"] in {"chip", "quote", "llm", "expert"} for s in case["sentences"])
    assert fragment["findings_version"] == 1
    assert fragment["prompt"] == "Expert_sentence_targets.v1"
    assert fragment["classifier"], "the classifier that filed the uncited sentences is named"


async def test_a_unit_found_by_its_own_text_comes_first_with_a_similarity_of_one(models):
    admin, _, _ = await ingested_single(models)
    fragment = await _fragment(admin)

    found = await admin.ok(
        "POST",
        "/knowledge-units/search",
        json={"query": fragment["embed_text"], "mode": "question", "k": 3},
    )
    first = found["hits"][0]
    assert first["rank"] == 1 and first["unit"]["id"] == fragment["id"]
    assert first["similarity"] == pytest.approx(1.0, abs=1e-4)
    assert first["matched_sentence"] is None
    assert first["score"] > 0
    assert [h["rank"] for h in found["hits"]] == list(range(1, len(found["hits"]) + 1))


async def test_patient_text_finds_the_unit_of_the_highlight_it_resembles(models):
    admin, _, _ = await ingested_single(models)
    fragment = await _fragment(admin)

    found = await admin.ok(
        "POST",
        "/knowledge-units/search",
        json={"query": f"Unrelated opening sentence here. {CUE}", "mode": "patient_text"},
    )
    [hit] = found["hits"]
    assert hit["unit"]["id"] == fragment["id"]
    assert hit["matched_sentence"] == CUE
    assert hit["similarity"] is not None and hit["similarity"] > 0.99


async def test_nothing_ingested_gives_no_hits(models):
    admin, _ = await _admin_and_expert()
    for mode in ("question", "patient_text"):
        found = await admin.ok(
            "POST", "/knowledge-units/search", json={"query": "anything at all", "mode": mode}
        )
        assert found == {"hits": []}


async def test_search_says_so_when_the_embedding_model_is_down(models):
    admin, _, _ = await ingested_single(models)
    models.down = True
    body = await admin.fails(
        "POST",
        "/knowledge-units/search",
        503,
        "embedding_unavailable",
        json={"query": "school report", "mode": "question"},
    )
    assert "embedding model" in body["message"]
    # The list does not need the model.
    assert await admin.ok("GET", "/knowledge-units")


async def test_a_search_leaves_the_knowledge_base_as_it_was(models):
    admin, _, _ = await ingested_single(models)
    before = await chips("SELECT count(*) FROM chips.finding_units")
    await admin.ok("POST", "/knowledge-units/search", json={"query": CUE, "mode": "question"})
    assert await chips("SELECT count(*) FROM chips.finding_units") == before


async def test_search_validates_its_input(models):
    admin, _ = await _admin_and_expert()
    for body in (
        {"query": "", "mode": "question"},
        {"query": "x" * 4001, "mode": "question"},
        {"query": "x", "mode": "other"},
        {"query": "x", "k": 0},
        {"query": "x", "k": 21},
    ):
        response = await admin.request("POST", "/knowledge-units/search", json=body)
        assert response.status_code == 422, body


async def _admin_and_expert():
    return await admin_api(), await expert_api("someone@example.com")
