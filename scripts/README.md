# scripts/

Run everything from the repository root, e.g. `python scripts/rag/ask.py "question"`. Inside the dev
container `PYTHONPATH=/workspace/backend` is already set (scripts import `app.*`); elsewhere set it.
Scripts in a folder import their helpers by plain module name (`rag_common`, `reddit_posts`), so a
folder is self-contained.

| Folder | Responsibility | Scripts (in pipeline order) |
|---|---|---|
| `corpus/` | Build the knowledge base from the literature | `fetch_sources` -> `upload_raw_documents` -> `parse_raw_documents` -> `chunk_parsed_documents` -> `index_chunks`; `purge_sources` removes sources again |
| `db/` | Database setup and access | `init_db` (apply `backend/db/init.sql`), `psql.sh` (psql shell, `overview`) |
| `rag/` | Query the RAG and evaluate it | `ask`; evaluation: `eval_retrieval`, `eval_generation`, `judge_generations`, `report_eval`, `compare_runs`; shared `rag_common` |
| `elicitation/` | Elicitation documents: test fixtures and schema | `make_fixtures` (see `docs/fixtures.md`), `export_schema`; `llm_clients`, `prompt_loader`, `leak_terms` and `reddit_posts` are helpers of `make_fixtures` (generation lives here, not in `backend/`) |

Rule of thumb: production logic belongs in `backend/app/`; a script only wires it together or
holds throwaway/example code (like the Reddit post reader).
