# expert-knowledge-rag

LangChain access to the expert knowledge database: clinicians' readings of teaching cases, ingested
by the web application into the Postgres schema `chips` (pgvector). An app adds this package,
points it at the database and gets `BaseRetriever`s and answer chains. It reads only; it never
writes.

Built on `langchain-core` and [`expert-knowledge-core`](../expert-knowledge-core). How the
knowledge is made and why it is cut this way: [docs/new-chips-knowledge.md](../../docs/new-chips-knowledge.md).

## Install

```
pip install expert-knowledge-rag                 # retrievers, chains
pip install "expert-knowledge-rag[ollama]"       # + default_embeddings() (bge-m3 through Ollama)
pip install "expert-knowledge-rag[pool]"         # + psycopg_pool, for a connection pool
```

In this repository it is a uv workspace member: `uv sync --all-packages`.

## Use

```python
from expert_knowledge_rag import ExpertKnowledgeStore, ExpertQuestionRetriever, default_embeddings

store = ExpertKnowledgeStore("postgresql://user:pass@host/db")  # schema "chips", read-only
retriever = ExpertQuestionRetriever(store=store, embeddings=default_embeddings(), k=4)

notes = retriever.invoke(
    "How do I tell sleep deprivation from attention problems in a patient's text?"
)
print(notes[0].page_content)
```

Each Document is one **note**: the case line, the patient's words with the expert's direction
label, and the clinician's own sentences verbatim, citations rendered as short quotes. `metadata`
has `unit_ids`, `session_id`, `expert_id`, `vignette_id`, `kinds`, `directions`, `patient_words`,
`score` and `merged`.

```
Teaching case V001: an adult's journal entry; clinician; overall: insufficient information
Patient's words: "every time I try to type a formula my hand starts shaking slightly" (marked: unclear)
Clinician's own words:
Q1: «every time I try to type a formula…» could be read as motor restlessness under task difficulty, ...
```

### Two retrievers

| | Input | How |
|---|---|---|
| `ExpertQuestionRetriever` | a clinician's question | dense + BM25 over the reviewed text (I1), fused with RRF; near-duplicate generic case answers go last |
| `PatientTextRetriever` | a new patient's text | each sentence searches the patient's words that experts highlighted (cue keys); a unit scores its cue plus a bonus for co-cited highlights |

Common fields: `k` (notes returned), `search` (`"hybrid"`, `"dense"`, `"bm25"`), `filter`,
`merge_shared` (units of one expert that share a sentence become one note), `bm25`, `overfetch`.
Everything is also available async (`ainvoke`).

### Filters

```python
from expert_knowledge_rag import ExpertFilter

ExpertFilter(populations=["adult"], exclude_vignettes=["V007"])
```

Use `exclude_vignettes` when the text being read is itself a teaching case.

### Answer chains

```python
from expert_knowledge_rag import expert_answer_chain

chain = expert_answer_chain(retriever, llm)  # llm: any LangChain chat model
chain.invoke("What separates rumination from goal-loss digression?")
# {"answer": "One clinician reads ... [E1]", "notes": [Document, ...]}
```

The prompts are the evaluated ones (`expert_knowledge_core.prompts`): notes are `[E1]`, `[E2]`, ...
and cited that way, and the model reports them as colleagues' opinion, never as criteria. With no
notes the model is not called and the answer is `NOT_IN_SOURCES`. `patient_answer_chain` does the
same for a patient's text.

### As an agent tool

```python
from langchain_core.tools import create_retriever_tool

tool = create_retriever_tool(
    retriever, "expert_notes", "What clinicians wrote about reading patients' texts."
)
```

## Things that must match the database

- **The query embedding model must be bge-m3** (1024 dimensions), the model the stored vectors were
  made with (`config/indexing.yaml`). A different width raises an error; a different model with the
  same width returns noise, so check `embeddings` when you pass your own.
- **`bm25=` must match `config/indexing.yaml` `sparse`** (defaults do): a query is tokenised as the
  stored vectors were, by `expert_knowledge_core.bm25`.
- `schema="chips"` is what the web application ingests into; `"chips_eval"` holds the test data of
  `scripts/db/load_chips_pg.py`, whose sessions have no findings record, so its units come back one
  per note as embedded, with a warning.
- Connections are `READ ONLY` transactions with prepared statements off (works behind a connection pooler).
  Pass `pool=` / `async_pool=` to reuse connections.

## Tests

```
uv run pytest packages/expert-knowledge-rag                      # unit tests; integration tests need DATABASE_URL
uv run pytest packages/expert-knowledge-rag -m "not integration" # no database
```

The integration tests create a throwaway schema from `scripts/db/chips_schema.sql`, seed the V001
example from the design doc and drop it afterwards.
