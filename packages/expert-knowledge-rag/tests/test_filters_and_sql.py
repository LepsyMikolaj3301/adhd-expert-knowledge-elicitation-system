import pytest
from psycopg import sql

from expert_knowledge_core.retrieval import FUSION_DEPTH, RRF_K
from expert_knowledge_rag import sql as q
from expert_knowledge_rag.filters import ExpertFilter, all_of


def text(composable: sql.Composable) -> str:
    return composable.as_string()


def test_default_filter_has_no_conditions():
    conditions, params = ExpertFilter().on_unit("u")
    assert conditions == []
    assert params == {}
    assert text(all_of([])) == "TRUE"


def test_every_set_field_becomes_a_parameterised_condition():
    f = ExpertFilter(
        populations=["adult"], tracks=["general"], framings=["email"], vignettes=["V001"],
        exclude_vignettes=["V009"],
    )  # fmt: skip
    conditions, params = f.on_unit("u")
    assert len(conditions) == 5
    assert params == {
        "f_populations": ["adult"], "f_tracks": ["general"], "f_framings": ["email"],
        "f_vignettes": ["V001"], "f_exclude": ["V009"],
    }  # fmt: skip
    assert "ANY(%(f_populations)s)" in text(conditions[0])


def test_experts_filter_limits_units_but_not_cue_keys():
    f = ExpertFilter(experts=["silver/SYN-001", "silver/SYN-002"])
    conditions, params = f.on_unit("u")
    assert [text(c) for c in conditions] == ['"u"."expert_id" = ANY(%(f_experts)s)']
    assert params == {"f_experts": ["silver/SYN-001", "silver/SYN-002"]}
    assert f.on_cue("c") == ([], {})  # a cue key is shared by every expert who marked it


def test_cue_conditions_only_use_the_vignette():
    conditions, params = ExpertFilter(populations=["adult"], exclude_vignettes=["V9"]).on_cue("c")
    assert [text(c) for c in conditions] == ['"c".vignette_id <> ALL(%(f_exclude)s)']
    assert params == {"f_exclude": ["V9"]}


@pytest.mark.parametrize("search,dense,sparse", [("hybrid", 1, 1), ("dense", 1, 0), ("bm25", 0, 1)])
def test_units_search_has_the_rankings_of_the_search_mode(search, dense, sparse):
    query, params = q.units_search(
        "chips",
        index="i1",
        search=search,
        limit=8,
        filter=ExpertFilter(),
        dense="[1]",
        sparse="{1:1}/3",
    )
    sql_text = text(query)
    assert sql_text.count("<=> CAST") // 2 == dense  # used in SELECT ordering and ORDER BY
    assert sql_text.count("<#>") // 3 == sparse
    assert '"chips"."finding_units"' in sql_text and f"LIMIT {FUSION_DEPTH}" in sql_text
    assert f"({RRF_K} + rank)" in sql_text and "LIMIT 8" in sql_text
    assert params["dense"] == "[1]" and params["sparse"] == "{1:1}/3"


def test_index_both_ranks_the_reviewed_and_the_combined_text():
    query, _ = q.units_search(
        "chips",
        index="both",
        search="hybrid",
        limit=4,
        filter=ExpertFilter(),
        dense="[1]",
        sparse="x",
    )
    sql_text = text(query)
    assert "embedding_combined" in sql_text and "sparse_combined" in sql_text
    assert (
        'SELECT * FROM "r0" UNION ALL SELECT * FROM "r1" UNION ALL SELECT * FROM "r2"' in sql_text
    )
    assert 'SELECT * FROM "r3"' in sql_text


def test_schema_is_quoted_not_interpolated():
    query, _ = q.sessions('x"; DROP SCHEMA chips; --', ["S1"])
    assert '"x""; DROP SCHEMA chips; --"."elicitation_sessions"' in text(query)


def test_cue_search_only_considers_cues_with_an_allowed_unit():
    query, params = q.cues_search(
        "chips", search="hybrid", filter=ExpertFilter(tracks=["general"]), dense="[1]", sparse="x"
    )
    sql_text = text(query)
    assert 'EXISTS (SELECT 1 FROM "chips"."unit_cues"' in sql_text
    assert '"cu"."track" = ANY(%(f_tracks)s)' in sql_text
    assert "LIMIT 10" in sql_text


def test_units_for_cues_selects_the_context_cues():
    query, params = q.units_for_cues("chips", [1, 2], ExpertFilter())
    assert "x.role = 'context'" in text(query) and params["cue_ids"] == [1, 2]
