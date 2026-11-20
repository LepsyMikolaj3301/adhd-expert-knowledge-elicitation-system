"""Where experts agree: ingestion and removal keep `chips.fragment_groups` in step with the
highlights, in the same transaction. The grouping rules are tested in the core package; here is
what reaches the database."""

from api_helpers import (
    CONFOUNDER,
    CUE,
    VIGNETTE_TEXT,
    admin_api,
    answer_and_submit,
    assign,
    decide_all,
    expert_api,
    highlight,
    published_version,
    run_jobs,
    to_review,
)
from sqlalchemy import text
from test_api_pipeline import CITED_PAYLOAD, chips, count

from app.core.db import session_factory
from app.knowledge import agreement

TRIMMED_CUE = CUE[:-7]  # most of the same passage: overlaps CUE, but is not identical
OTHER_WORDS = "word3 word4 word5"


def payload(cue_direction: str | None, cue: str = CUE, second=(CONFOUNDER, "away")):
    marks = [highlight(1, cue, cue_direction), highlight(2, *second)]
    return {**CITED_PAYLOAD, "highlights": marks}


async def four_experts():
    """Four experts read one text. e1 and e2 mark the cue as toward, e3 marks nearly the same
    words as away, e4 does not mark it at all. e1-e3 mark the confounder as away, e4 too."""
    admin = await admin_api()
    experts = [await expert_api(f"e{n}@example.com") for n in range(1, 5)]
    version = await published_version(admin)
    ids = await assign(admin, version, *experts)
    payloads = [
        payload("toward"),
        payload("toward"),
        payload("away", TRIMMED_CUE),
        {
            **CITED_PAYLOAD,
            "highlights": [highlight(1, CONFOUNDER, "away"), highlight(2, OTHER_WORDS, "neutral")],
        },
    ]
    for expert, assignment_id, body in zip(experts, ids, payloads, strict=True):
        await answer_and_submit(expert, assignment_id, body)
        await to_review(expert, assignment_id)
        await decide_all(admin, assignment_id)
        await run_jobs()
    return admin, experts, ids


GROUPS = (
    "SELECT n_answered, n_attending, n_toward, n_away, n_neutral, n_unclear, n_mixed, label, "
    "lower(span), upper(span) FROM chips.fragment_groups ORDER BY lower(span), upper(span)"
)


async def groups():
    return {(r[8], r[9]): r[:8] for r in await chips(GROUPS)}


def spans():
    def span(quote):
        start = VIGNETTE_TEXT.index(quote)
        return start, start + len(quote)

    return span(CUE), span(TRIMMED_CUE), span(CONFOUNDER), span(OTHER_WORDS)


async def test_three_of_four_cite_the_passage_and_the_group_says_how_they_read_it(models):
    await four_experts()
    cue, trimmed, confounder, other = spans()
    union = (min(cue[0], trimmed[0]), max(cue[1], trimmed[1]))
    found = await groups()
    # (n answered, k attending, toward, away, neutral, unclear, mixed, label)
    assert found[union] == (4, 3, 2, 1, 0, 0, 0, "split")
    assert found[confounder] == (4, 4, 0, 4, 0, 0, 0, "agreed")
    assert found[other] == (4, 1, 0, 0, 1, 0, 0, "single")
    assert len(found) == 3


async def test_every_member_is_a_highlight_of_the_knowledge_base(models):
    await four_experts()
    assert await count("fragment_group_members") == 8
    orphans = await chips(
        "SELECT m.highlight_id FROM chips.fragment_group_members m "
        "LEFT JOIN chips.highlights h ON h.id = m.highlight_id WHERE h.id IS NULL"
    )
    assert orphans == []
    assert await chips("SELECT DISTINCT embedding_model FROM chips.finding_units") == [("bge-m3",)]


async def test_withdrawing_an_expert_removes_them_from_the_count_and_the_denominator(models):
    admin, experts, _ = await four_experts()
    cue, trimmed, confounder, _ = spans()
    union = (min(cue[0], trimmed[0]), max(cue[1], trimmed[1]))

    await admin.ok("DELETE", f"/knowledge-units/by-expert/{experts[2].user_id}")

    found = await groups()
    # e3, the dissenter, is gone: the passage is now 2 of 3, and they agree.
    assert found[union] == (3, 2, 2, 0, 0, 0, 0, "agreed")
    assert found[confounder] == (3, 3, 0, 3, 0, 0, 0, "agreed")


async def test_withdrawing_the_only_expert_who_marked_a_passage_removes_its_group(models):
    admin, experts, _ = await four_experts()
    _, _, _, other = spans()
    assert other in await groups()

    await admin.ok("DELETE", f"/knowledge-units/by-expert/{experts[3].user_id}")

    assert other not in await groups()


async def test_removing_everyone_leaves_no_groups(models):
    admin, experts, _ = await four_experts()
    for expert in experts:
        await admin.ok("DELETE", f"/knowledge-units/by-expert/{expert.user_id}")
    assert await count("fragment_groups") == 0 and await count("fragment_group_members") == 0


async def test_recomputing_gives_the_same_groups_and_the_backfill_rebuilds_them(models):
    await four_experts()
    before = await chips(GROUPS)
    async with session_factory()() as db:
        [(code,)] = (
            await db.execute(text("SELECT DISTINCT vignette_id FROM chips.highlights"))
        ).all()
        assert await agreement.recompute(db, code, 1) == 3
        await db.commit()
    assert await chips(GROUPS) == before
    assert await count("fragment_groups") == 3, "recomputing replaces, it does not add"

    async with session_factory()() as db:
        await db.execute(text("DELETE FROM chips.fragment_groups"))
        assert await agreement.recompute_all(db) == 3
        await db.commit()
    assert await chips(GROUPS) == before


async def test_the_admins_search_says_how_many_clinicians_marked_the_passage(models):
    admin, experts, _ = await four_experts()
    listed = await admin.ok("GET", "/knowledge-units", params={"status": "ingested"})
    cue = next(
        u
        for u in listed
        if u["kind"] == "fragment" and u["patient_words"] == CUE and u["direction"] == "toward"
    )
    found = await admin.ok(
        "POST", "/knowledge-units/search", json={"query": cue["embed_text"], "k": 20}
    )
    hits = {h["unit"]["id"]: h for h in found["hits"]}
    agreement = hits[cue["id"]]["agreement"]
    assert (agreement["attending"], agreement["answered"], agreement["label"]) == (3, 4, "split")
    assert agreement["counts"] == {"toward": 2, "away": 1}
    assert agreement["line"].startswith("Agreement: 3 of 4 clinicians")
    # every fragment unit belongs to a group, here and only here: there is no case unit
    assert [h["unit"]["kind"] for h in found["hits"]] == ["fragment"] * len(found["hits"])
    assert all(h["agreement"] is not None for h in found["hits"])
