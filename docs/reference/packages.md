---
title: Packages expert-knowledge-core and expert-knowledge-rag
diataxis: reference
---

# Packages `expert-knowledge-core` and `expert-knowledge-rag`

`expert-knowledge-core` (`packages/expert-knowledge-core`) holds BM25 sparse vectors, note packing, evaluated prompts, the findings record types and retrieval constants, and depends on pydantic, pgvector and snowballstemmer only. `expert-knowledge-rag` (`packages/expert-knowledge-rag`) provides LangChain retrievers and answer chains that read the Postgres schema `chips`, and depends on the core package, `langchain-core`, `psycopg` and `numpy`. Both are Python libraries (`requires-python >=3.12`) without a CLI or a server.

For how the two packages fit into the indexing and retrieval flow, see [Retrieval and indexing](../explanation/retrieval-and-indexing.md). The backend modules that import the core package are in [Backend: indexing and proofreading](backend-indexing-proofread.md).

## expert_knowledge_core

The package `__init__.py` has a docstring and no re-exports; import from the submodules.

### Module `bm25`

BM25 term weights stored as pgvector `sparsevec` values. A document vector holds `idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))` per term; a query vector holds the count of each term, so the inner product is the BM25 score.

| Name | Signature or value | Description |
|---|---|---|
| `Bm25Config` | pydantic model, `extra="forbid"` | Unknown keys fail on load. Fields below. |
| `Bm25Config.k1` | `float = 1.2`, must be `> 0` | Term-frequency saturation. |
| `Bm25Config.b` | `float = 0.75`, `0 <= b <= 1` | Length normalisation. |
| `Bm25Config.stemmer` | `str \| None = "english"` | Snowball language; `None` disables stemming. |
| `Tokenizer(cfg)(text)` | `-> list[str]` | Lowercases, takes tokens matching `[a-z0-9]+`, drops stopwords, then stems if a stemmer is configured. |
| `term_dim(token)` | `-> int` | 8-byte blake2b digest of the token, read big-endian, modulo `DIMENSIONS`. |
| `fit(texts, cfg)` | `-> list[SparseVector]` | Document vectors for a whole corpus. `idf = log(1 + (n - d + 0.5) / (d + 0.5))` and `avgdl` are corpus-global. An empty list gives an empty list. |
| `query_vector(text, cfg)` | `-> SparseVector \| None` | Term counts of the query; `None` when no term is left after tokenising. |
| `DIMENSIONS` | `1 << 20` (1048576) | Width of every sparse vector; matches the `sparsevec(1048576)` columns. |
| `STOPWORDS` | `frozenset` of 49 English words | Removed by `Tokenizer`. |

### Module `notes`

Pure functions over plain dicts (`records.Record`); no models and no database.

| Function | Description |
|---|---|
| `split_sentences(text) -> list[tuple[int, int]]` | Sentence spans. A line break always ends a sentence. Within a line, no split happens inside a quotation, after one of the abbreviations `e.g.`, `i.e.`, `vs.`, `etc.`, `approx.`, `hx.`, `dr.`, `r/o.`, or after a list number. A sentence under `MIN_SENTENCE_WORDS` words joins its neighbour on the same line. |
| `quote_spans(text) -> list[tuple[int, int, str]]` | Spans of double-quoted text (`"..."` and curly quotes) and of `'...'` text of 4 to 80 characters without a line break. |
| `quote_pieces(sentence) -> list[str]` | Quoted pieces of a sentence, split on `...` and `…`. |
| `short_quote(text, words=8) -> str` | `«` first `words` words `»`, with `…` when the text is longer. |
| `render_sentence(text, highlights) -> str` | Replaces each chip `⟦hN⟧` with the `short_quote` of the highlight whose `chip` is N. A chip without a matching highlight raises `KeyError`. |
| `by_question(sentences, highlights) -> list[str]` | One line `Qn: sentence sentence` per run of sentences with the same `question_id`. |
| `overall(meta) -> str` | `overall: insufficient information`, `overall N/5`, or `no overall rating`. |
| `case_label(meta) -> str` | Article, population and framing label, for example `an adult's journal entry`. |
| `header(meta, unit) -> str` | Header line of a unit: clinician with optional role, case label, `case-level points` or `fragment marked: <direction>`, and the overall rating, joined with ` · `. |
| `merge_groups(units_by_id, unit_ids) -> list[list[str]]` | Groups unit ids that share a sentence id, transitively; groups and members keep the order of first appearance. |
| `pack_block(rec, unit_ids) -> str` | The note text: a `Teaching case <vignette_id>: ...` line, a `Patient's words:` line with direction marks (when the units have highlights), then `Clinician's own words:` followed by the `by_question` lines, each sentence once. |

| Constant | Value | Meaning |
|---|---|---|
| `CHIP_RE` | `⟦h(\d+)⟧` | Citation chip inside an answer. |
| `FRAMING_LABEL` | `email`, `forum_post`, `personal_journal` to `email`, `forum post`, `journal entry` | Label per framing. |
| `MIN_SENTENCE_WORDS` | `4` | Shorter sentences join a neighbour. |
| `RENDER_WORDS` | `8` | Words kept by `short_quote`. |
| `CASE` | `"case"` | Re-exported from `records`. |

### Module `records`

The findings record stored in `chips.elicitation_sessions.document`. Records are plain dicts; the TypedDicts only describe them.

| Name | Fields or value |
|---|---|
| `FINDINGS_VERSION` | `1`. A record with another `version` is not read. |
| `CASE` | `"case"`: the target of a sentence about the text as a whole. |
| `Direction` | `Literal["toward", "away", "neutral", "unclear"]` |
| `Highlight` | `id` (`h1..` expert, `i1..` implicit), `origin` (`expert` or `implicit`), `chip` (`int \| None`), `span` (`[start, end)` in the vignette), `text`, `direction` (`Direction \| None`). |
| `Sentence` | `id` (for example `Q2.3`), `question_id`, `idx`, `span`, `text`, `targets` (highlight ids and/or `case`), `assigned_by` (`chip`, `quote`, `llm`, `expert` or `None`). |
| `Unit` | `id`, `kind` (`fragment` or `case`), `highlight`, `direction`, `sentences`, `context` (co-cited highlights), `body`, `i1`, `i3`. |
| `Meta` | `role`, `framing`, `population`, `rating` (`int \| None`), `insufficient` (`bool`). |
| `Record` (`total=False`) | `version`, `session_id`, `expert_id`, `vignette_id`, `vignette_version`, `meta`, `highlights`, `sentences`, `units`, `flags`. |
| `is_readable(document) -> bool` | True for a dict whose `version` equals `FINDINGS_VERSION` and that has the keys `meta`, `highlights`, `sentences` and `units`. |

### Module `prompts`

| Name | Description |
|---|---|
| `NOT_IN_SOURCES` | `"NOT_IN_SOURCES"`: the reply when the notes do not answer. |
| `EXPERT_SYSTEM_PROMPT` | System prompt for a clinician's question; asks for 3 to 6 sentences and note citations such as `[E2]`. |
| `PATIENT_SYSTEM_PROMPT` | System prompt for a patient's text; asks for 4 to 7 sentences and forbids diagnosing. |
| `format_notes(texts) -> str` | `[E1] text` blocks separated by a blank line. |
| `build_expert_prompt(question, texts) -> str` | `Question: ...` when `texts` is empty; otherwise a `Notes:` block followed by the question. |
| `build_patient_prompt(patient_text, question, texts) -> str` | `Notes:` block (`(none)` when `texts` is empty), the quoted patient text, then the question. |

### Module `retrieval`

| Constant | Value | Meaning |
|---|---|---|
| `RRF_K` | `60` | Reciprocal rank fusion: score is the sum over rankings of `1 / (RRF_K + rank)`. |
| `FUSION_DEPTH` | `50` | Candidates taken from each ranking before fusing. |
| `NEAR_DUPLICATE` | `0.9` | Cosine of two case units that count as the same generic answer. |
| `PATIENT_TOP_CUES` | `10` | Cue keys kept per patient sentence. |
| `CONTEXT_BONUS` | `0.5` | Weight of the scores of co-cited cues. |
| `EMBEDDING_DIMENSIONS` | `1024` | Width of the stored vectors (bge-m3). |
| `EMBEDDING_MODEL` | `"bge-m3"` | Model the stored vectors were made with. |

### Module `example`

`example_record(session_id="S1", expert_id="X1", role=None) -> Record` returns a deep-copied worked example (vignette `V001`, `vignette_version` 1) with four fragment highlights, ten sentences and units built from them (one per targeted highlight plus a case unit). It is meant for tests, READMEs and smoke scripts.

## expert_knowledge_rag

`from expert_knowledge_rag import ...` exports ten names (`__all__`): `ExpertFilter`, `ExpertKnowledgeStore`, `ExpertQuestionRetriever`, `PatientTextRetriever`, `default_embeddings`, `expert_answer_chain`, `expert_prompt`, `format_notes`, `patient_answer_chain` and `patient_prompt`.

### `ExpertKnowledgeStore`

`ExpertKnowledgeStore(dsn=None, *, pool=None, async_pool=None, schema="chips", dimensions=1024)` is the connection to the database. The constructor raises `ValueError` when `dsn`, `pool` and `async_pool` are all `None`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `dsn` | `str \| None` | `None` | Connection string; used when no pool is given. |
| `pool` | any object with `.connection()` | `None` | Sync pool, for example `psycopg_pool.ConnectionPool`. |
| `async_pool` | any object with async `.connection()` | `None` | Async pool, for example `AsyncConnectionPool`. |
| `schema` | `str` | `"chips"` | Postgres schema; quoted as an identifier in every query. |
| `dimensions` | `int` | `EMBEDDING_DIMENSIONS` (1024) | Width the query vectors must have. |

| Method | Description |
|---|---|
| `vector_text(vector) -> str` | Formats a query embedding as `[v1,v2,...]` with `%.8g` per value. Raises `ValueError` when the length differs from `dimensions`; the message names bge-m3. |
| `run(queries) -> list[Rows]` | Runs the `(query, params)` pairs in order inside one transaction, after `SET TRANSACTION READ ONLY`, and returns the rows of each as dicts. Uses `pool.connection()` or `psycopg.connect(dsn, prepare_threshold=None)`. With only an `async_pool` it fails on an assertion. |
| `arun(queries) -> list[Rows]` | The async mirror of `run`, using `async_pool.connection()` or `psycopg.AsyncConnection.connect(dsn, prepare_threshold=None)`. |

### Retrievers

Both retrievers subclass LangChain `BaseRetriever`, implement sync and async retrieval, and return packed notes as `Document` objects. They share these fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `store` | `ExpertKnowledgeStore` | required | Database access. |
| `embeddings` | LangChain `Embeddings` | required | Must be the model the stored vectors were made with (bge-m3). |
| `k` | `int` (`>= 1`) | `4` | Notes returned; the `k` keyword of a call overrides it. |
| `search` | `"hybrid"`, `"dense"` or `"bm25"` | `"hybrid"` | Hybrid fuses dense and BM25 rankings with RRF. |
| `filter` | `ExpertFilter` | `ExpertFilter()` | Which units a search may return. |
| `merge_shared` | `bool` | `True` | Units of one session that share a sentence become one note. |
| `bm25` | `Bm25Config` | `Bm25Config()` | Query tokenisation; must equal the config used for the stored vectors. |
| `fusion_depth` | `int` | `FUSION_DEPTH` (50) | Candidates per ranking. |
| `overfetch` | `int` (`>= 1`) | `4` | Units fetched per note wanted (`k * overfetch`). |

**`ExpertQuestionRetriever`** takes a clinician's question and returns notes. It adds two fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `index` | `"i1"`, `"i3"` or `"both"` | `"i1"` | `i1` searches the reviewed text, `i3` the text with the patient's words added, `both` fuses both. |
| `downweight_duplicate_cases` | `bool` | `True` | Case units near-duplicate to a better-ranked case unit move to the end. |

Behaviour: a blank query returns `[]`. With `search` other than `"dense"` the query is turned into a BM25 vector; if no term survives tokenising, `hybrid` falls back to `dense` and `bm25` returns `[]`. With `search="bm25"` the embedding model is not called. The unit search, the near-duplicate rule, a query for the sessions' records and `build_documents` run in that order, and the first `k` notes are returned.

**`PatientTextRetriever`** takes a patient's text and returns notes about the highlights it resembles. It has the shared fields only. Behaviour:

1. Splits the text with `notes.split_sentences` (the whole stripped text if that yields nothing).
2. Embeds the sentences with `embed_documents` unless `search="bm25"`.
3. Runs one `sql.cues_search` per sentence over the cue keys. A sentence with no BM25 terms falls back to `dense` in `hybrid` mode and is skipped in `bm25` mode; no queries means `[]`.
4. Scores each cue with `ranking.cue_scores` (RRF over the sentence rankings) and loads the units of those cues with `sql.units_for_cues`.
5. Ranks units with `ranking.rank_by_cues`, keeps `k * overfetch`, and builds notes.

It does not apply the near-duplicate rule.

### `ExpertFilter`

Pydantic model; every field that is set must hold.

| Field | Type | Default | Applies to |
|---|---|---|---|
| `populations` | `list[str] \| None` | `None` | Units (`population`). |
| `tracks` | `list[str] \| None` | `None` | Units (`track`). |
| `framings` | `list[str] \| None` | `None` | Units (`framing`). |
| `vignettes` | `list[str] \| None` | `None` | Units and cue keys (`vignette_id = ANY`). |
| `exclude_vignettes` | `list[str]` | `[]` | Units and cue keys (`vignette_id <> ALL`). |
| `experts` | `list[str] \| None` | `None` | Units only (`expert_id`); cue keys are shared, so they are not filtered by expert. |

`on_unit(alias="u")` and `on_cue(alias="c")` return `(conditions, params)` with parameterised conditions; `all_of(conditions)` joins them with `AND`, or gives `TRUE` for none.

### Chains

| Function | Input | Output |
|---|---|---|
| `expert_answer_chain(retriever, llm)` | a string, or a dict with `question` | `{"answer": str, "notes": [Document]}` |
| `patient_answer_chain(retriever, llm)` | a string, or a dict with `patient_text` and optional `question` | `{"answer": str, "notes": [Document]}` |

When the retriever returns no documents, the answer is `NOT_IN_SOURCES`, `notes` is empty and the model is not called. The default `question` of the patient chain is `DEFAULT_PATIENT_QUESTION` (`"What do the notes say about how this text should be read?"`, defined in `chains.py`).

### Prompts and embeddings

| Name | Description |
|---|---|
| `expert_prompt()` | `ChatPromptTemplate` with the core expert system prompt and variables `notes` and `question`. |
| `patient_prompt()` | `ChatPromptTemplate` with the core patient system prompt and variables `notes`, `patient_text` and `question`. |
| `format_notes(docs) -> str` | `core.prompts.format_notes` over the `page_content` of the documents. |
| `default_embeddings(base_url="http://localhost:11434", **kwargs)` | Returns `langchain_ollama.OllamaEmbeddings(model="bge-m3", base_url=base_url, **kwargs)`. The import happens inside the function, so the `ollama` extra is needed only when it is called. |

### Internal modules

These modules are not in `__all__` but define the retrieval rules.

| Name | Description |
|---|---|
| `documents.build_documents(hits, records, *, merge=True) -> list[Document]` | One `Document` per note, ordered by the rank of its best unit. `page_content` is `pack_block` of the group. A session whose record is missing, not readable, or lacks a unit gives one `Document` per unit with `embed_text` as content and a logged warning. |
| `documents.SOURCE` | `"expert"`; value of `metadata["source"]`. |
| `documents.local_id(hit)` | Unit id inside the record: the id minus the prefix `<session_id>-<vignette_id>-`; raises `ValueError` when the prefix is absent. |
| `ranking.UnitHit` | Frozen dataclass: `id`, `session_id`, `expert_id`, `vignette_id`, `vignette_version`, `kind`, `highlight_id`, `direction`, `embed_text`, `score`, `vector` (`np.ndarray \| None`, set for case units only). `UnitHit.from_row(row, score=None)` builds it from a row. |
| `ranking.downweight_duplicate_cases(hits)` | Case units whose cosine to an earlier kept case unit is at least `NEAR_DUPLICATE` go to the end; other units keep their order. |
| `ranking.cue_scores(rankings, rrf_k)` | Sum of `1 / (rrf_k + rank)` per cue over the sentence rankings. |
| `ranking.rank_by_cues(rows, score)` | Units whose own cue scored, with score `own + CONTEXT_BONUS * sum(context cue scores)`, sorted by descending score, then id. |
| `sql.units_search(schema, *, index, search, limit, filter, dense=None, sparse=None, depth=FUSION_DEPTH)` | Query over `finding_units`: one ranking CTE per dense and/or sparse column pair, fused by `sum(1.0 / (RRF_K + rank))`, ordered by score then id. Dense ranking uses cosine distance `<=>`; sparse ranking uses `<#>` and keeps only rows with a negative value (a shared term). Case units return their `embedding` as text in `vector`. |
| `sql.cues_search(schema, *, search, filter, dense=None, sparse=None, top=PATIENT_TOP_CUES, depth=FUSION_DEPTH)` | Ranks `cue_keys` as `cue_id`, `score`. Only cues that have a unit the filter allows take part. |
| `sql.units_for_cues(schema, cue_ids, filter)` | Units whose own cue (`unit_cues.role = 'cue'`) is in `cue_ids`, with `cue_id` and the `context_ids` array (`role = 'context'`). |
| `sql.sessions(schema, session_ids)` | `id` and `document` of the `elicitation_sessions` rows. |
| `sql.INDEXES` | `i1` is (`embedding`, `sparse`); `i3` is (`embedding_combined`, `sparse_combined`); `both` is both pairs. |
| `sql.UNIT_COLUMNS` | `id`, `session_id`, `expert_id`, `vignette_id`, `vignette_version`, `kind`, `highlight_id`, `direction`, `embed_text`. |
| `sql.Search`, `sql.Index`, `sql.Query` | `Literal["hybrid", "dense", "bm25"]`, `Literal["i1", "i3", "both"]`, `tuple[Composed, dict]`. |

Metadata of a note (`documents._metadata`): `source`, `unit_ids`, `session_id`, `expert_id`, `vignette_id`, `vignette_version`, `kinds`, `directions`, `patient_words` (list of `text` and `direction`), `score` (of the best unit) and `merged` (`True` when the note holds more than one unit).

## Dependencies

| Package | Dependencies (`pyproject.toml`) |
|---|---|
| `expert-knowledge-core` | `pydantic>=2.6`, `pgvector>=0.3`, `snowballstemmer>=3.1.1` |
| `expert-knowledge-rag` | `expert-knowledge-core` (uv workspace source), `langchain-core>=1.0,<2`, `psycopg[binary]>=3.2`, `numpy>=2.0` |
| `expert-knowledge-rag` extra `ollama` | `langchain-ollama>=1.0` |
| `expert-knowledge-rag` extra `pool` | `psycopg-pool>=3.2` |

The rag package's pytest configuration sets `asyncio_mode = "auto"` and declares the marker `integration` (needs the Postgres of `DATABASE_URL`).

## Sources in code

- `packages/expert-knowledge-core/pyproject.toml` - core dependencies
- `packages/expert-knowledge-core/src/expert_knowledge_core/__init__.py` - package docstring, no re-exports
- `packages/expert-knowledge-core/src/expert_knowledge_core/bm25.py` - Bm25Config, Tokenizer, fit, query_vector, DIMENSIONS, STOPWORDS
- `packages/expert-knowledge-core/src/expert_knowledge_core/example.py` - example_record
- `packages/expert-knowledge-core/src/expert_knowledge_core/notes.py` - sentence splitting, rendering, packing, constants
- `packages/expert-knowledge-core/src/expert_knowledge_core/prompts.py` - system prompts, NOT_IN_SOURCES, prompt builders
- `packages/expert-knowledge-core/src/expert_knowledge_core/records.py` - record TypedDicts, FINDINGS_VERSION, is_readable
- `packages/expert-knowledge-core/src/expert_knowledge_core/retrieval.py` - retrieval constants
- `packages/expert-knowledge-rag/pyproject.toml` - rag dependencies, extras, pytest settings
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/__init__.py` - public exports
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/chains.py` - answer chains, DEFAULT_PATIENT_QUESTION
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/documents.py` - build_documents, metadata, local_id
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/filters.py` - ExpertFilter, all_of
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/ollama.py` - default_embeddings
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/prompts.py` - prompt templates, format_notes
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/ranking.py` - UnitHit, duplicate downweighting, cue scoring
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/retrievers.py` - the two retrievers and their fields
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/sql.py` - query builders, INDEXES, UNIT_COLUMNS
- `packages/expert-knowledge-rag/src/expert_knowledge_rag/store.py` - ExpertKnowledgeStore
