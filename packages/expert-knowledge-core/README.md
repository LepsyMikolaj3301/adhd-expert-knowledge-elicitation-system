# expert-knowledge-core

The part of the expert-knowledge RAG that must not exist in two copies. It has no LangChain, web
framework or database driver; it is imported by the web application's ingestion (`backend/`) and
by [`expert-knowledge-rag`](../expert-knowledge-rag).

| Module | What | Why it is shared |
|---|---|---|
| `bm25` | BM25 as `sparsevec` (`fit`, `query_vector`, `Bm25Config`) | a query must be tokenised exactly like the stored vectors |
| `notes` | sentence splitting, chip rendering, `merge_groups`, `pack_block` | the packed text must match what was embedded |
| `records` | TypedDicts of the findings record in `chips.elicitation_sessions.document` | the contract between writer and reader |
| `prompts` | the evaluated system prompts and the `[E#]` note format | what was measured |
| `retrieval` | RRF k, fusion depth, near-duplicate and patient-mode constants | what the evaluations settled on |

Changes here affect both sides: run the repo's tests (`uv run pytest`) and the package's own.
