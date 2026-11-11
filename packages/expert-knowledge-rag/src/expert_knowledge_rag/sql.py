"""The queries, schema-qualified. Mirrors the hybrid search of scripts/rag/rag_common.py.

Dense: pgvector cosine distance. Sparse: `sparse <#> q` is -BM25 (see expert_knowledge_core.bm25),
rows sharing no term with the query (score 0) are not matches. The rankings are fused with RRF.
Vectors travel as text through `CAST(CAST(x AS text) AS vector)`, so no codec has to be registered
on the connection (which keeps it working behind Neon's pooler).
"""

from typing import Any, Literal

from psycopg import sql

from expert_knowledge_core.retrieval import FUSION_DEPTH, PATIENT_TOP_CUES, RRF_K
from expert_knowledge_rag.filters import ExpertFilter, all_of

Search = Literal["hybrid", "dense", "bm25"]
Index = Literal["i1", "i3", "both"]
Query = tuple[sql.Composed, dict[str, Any]]

# (dense column, sparse column) pairs of finding_units: I1 is what was reviewed, I3 adds the
# patient's words. The evaluations chose I1 for questions.
INDEXES: dict[str, list[tuple[str, str]]] = {
    "i1": [("embedding", "sparse")],
    "i3": [("embedding_combined", "sparse_combined")],
    "both": [("embedding", "sparse"), ("embedding_combined", "sparse_combined")],
}

UNIT_COLUMNS = (
    "id",
    "session_id",
    "expert_id",
    "vignette_id",
    "vignette_version",
    "kind",
    "highlight_id",
    "direction",
    "is_synthetic",
    "embed_text",
)


def _table(schema: str, name: str) -> sql.Identifier:
    return sql.Identifier(schema, name)


def _vector(param: str) -> sql.Composable:
    return sql.SQL("CAST(CAST({} AS text) AS vector)").format(sql.Placeholder(param))


def _sparse(param: str) -> sql.Composable:
    return sql.SQL("CAST(CAST({} AS text) AS sparsevec)").format(sql.Placeholder(param))


def _rankings(
    table: sql.Identifier,
    alias: str,
    columns: list[tuple[str, str]],
    search: Search,
    where: sql.Composable,
    depth: int,
) -> tuple[list[sql.Composable], int]:
    """One CTE per ranking (dense and/or sparse, per column pair) and how many there are."""
    a = sql.Identifier(alias)
    ctes: list[sql.Composable] = []
    for dense_col, sparse_col in columns:
        if search in ("hybrid", "dense"):
            d = sql.SQL("{a}.{c} <=> ").format(a=a, c=sql.Identifier(dense_col)) + _vector("dense")
            ctes.append(
                sql.SQL(
                    "{n} AS (SELECT {a}.id, row_number() OVER (ORDER BY {d}) AS rank "
                    "FROM {t} {a} WHERE {w} AND {a}.{c} IS NOT NULL ORDER BY {d} LIMIT {depth})"
                ).format(
                    n=sql.Identifier(f"r{len(ctes)}"),
                    a=a,
                    d=d,
                    t=table,
                    w=where,
                    c=sql.Identifier(dense_col),
                    depth=sql.Literal(depth),
                )
            )
        if search in ("hybrid", "bm25"):
            s = sql.SQL("{a}.{c} <#> ").format(a=a, c=sql.Identifier(sparse_col)) + _sparse(
                "sparse"
            )
            ctes.append(
                sql.SQL(
                    "{n} AS (SELECT {a}.id, row_number() OVER (ORDER BY {s}) AS rank "
                    "FROM {t} {a} WHERE {w} AND ({s}) < 0 ORDER BY {s} LIMIT {depth})"
                ).format(
                    n=sql.Identifier(f"r{len(ctes)}"),
                    a=a,
                    s=s,
                    t=table,
                    w=where,
                    depth=sql.Literal(depth),
                )
            )
    return ctes, len(ctes)


def _fused(count: int) -> sql.Composable:
    union = sql.SQL(" UNION ALL ").join(
        sql.SQL("SELECT * FROM {}").format(sql.Identifier(f"r{n}")) for n in range(count)
    )
    return sql.SQL(
        "fused AS (SELECT id, sum(1.0 / ({k} + rank)) AS score FROM ({u}) r GROUP BY id)"
    ).format(k=sql.Literal(RRF_K), u=union)


def units_search(
    schema: str,
    *,
    index: Index,
    search: Search,
    limit: int,
    filter: ExpertFilter,
    dense: str | None = None,
    sparse: str | None = None,
    depth: int = FUSION_DEPTH,
) -> Query:
    """Units ranked by `search` over the `index` texts. `dense` / `sparse` are the query vectors
    as text. Case units come back with their I1 vector (`vector`), for the near-duplicate rule."""
    conditions, params = filter.on_unit("u")
    ctes, count = _rankings(
        _table(schema, "finding_units"), "u", INDEXES[index], search, all_of(conditions), depth
    )
    columns = sql.SQL(", ").join(sql.SQL("u.{}").format(sql.Identifier(c)) for c in UNIT_COLUMNS)
    query = sql.SQL(
        "WITH {ctes}, {fused} SELECT {cols}, f.score, "
        "CASE WHEN u.kind = 'case' THEN u.embedding::text END AS vector "
        "FROM fused f JOIN {t} u ON u.id = f.id ORDER BY f.score DESC, u.id LIMIT {limit}"
    ).format(
        ctes=sql.SQL(", ").join(ctes),
        fused=_fused(count),
        cols=columns,
        t=_table(schema, "finding_units"),
        limit=sql.Literal(limit),
    )
    return query, {**params, "dense": dense, "sparse": sparse}


def cues_search(
    schema: str,
    *,
    search: Search,
    filter: ExpertFilter,
    dense: str | None = None,
    sparse: str | None = None,
    top: int = PATIENT_TOP_CUES,
    depth: int = FUSION_DEPTH,
) -> Query:
    """Cue keys (the patient's words of a highlight) ranked for one sentence. Only cues that
    have a unit the filter allows take part: a cue of synthetic-only units must not use up a
    place when synthetic units are excluded."""
    unit_conditions, params = filter.on_unit("cu")
    cue_conditions, cue_params = filter.on_cue("c")
    exists = sql.SQL(
        "EXISTS (SELECT 1 FROM {uc} uc JOIN {u} cu ON cu.id = uc.unit_id "
        "WHERE uc.cue_key_id = c.id AND {w})"
    ).format(
        uc=_table(schema, "unit_cues"),
        u=_table(schema, "finding_units"),
        w=all_of(unit_conditions),
    )
    ctes, count = _rankings(
        _table(schema, "cue_keys"),
        "c",
        [("embedding", "sparse")],
        search,
        all_of([*cue_conditions, exists]),
        depth,
    )
    query = sql.SQL(
        "WITH {ctes}, {fused} SELECT id AS cue_id, score FROM fused "
        "ORDER BY score DESC, id LIMIT {top}"
    ).format(ctes=sql.SQL(", ").join(ctes), fused=_fused(count), top=sql.Literal(top))
    return query, {**params, **cue_params, "dense": dense, "sparse": sparse}


def units_for_cues(schema: str, cue_ids: list[int], filter: ExpertFilter) -> Query:
    """The units whose own cue is one of `cue_ids`, with their co-cited (context) cue ids."""
    conditions, params = filter.on_unit("u")
    columns = sql.SQL(", ").join(sql.SQL("u.{}").format(sql.Identifier(c)) for c in UNIT_COLUMNS)
    query = sql.SQL(
        "SELECT {cols}, uc.cue_key_id AS cue_id, "
        "COALESCE((SELECT array_agg(x.cue_key_id) FROM {ucs} x "
        "WHERE x.unit_id = u.id AND x.role = 'context'), '{{}}') AS context_ids, "
        "CASE WHEN u.kind = 'case' THEN u.embedding::text END AS vector "
        "FROM {ucs} uc JOIN {u} u ON u.id = uc.unit_id "
        "WHERE uc.role = 'cue' AND uc.cue_key_id = ANY(%(cue_ids)s) AND {w}"
    ).format(
        cols=columns,
        ucs=_table(schema, "unit_cues"),
        u=_table(schema, "finding_units"),
        w=all_of(conditions),
    )
    return query, {**params, "cue_ids": cue_ids}


def sessions(schema: str, session_ids: list[str]) -> Query:
    """The findings records of the sessions the hits come from."""
    query = sql.SQL("SELECT id, document FROM {t} WHERE id = ANY(%(ids)s)").format(
        t=_table(schema, "elicitation_sessions")
    )
    return query, {"ids": session_ids}
