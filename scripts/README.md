# scripts/

Run everything from the repository root, e.g. `python scripts/rag/ask.py "question"`. Inside the dev
container `PYTHONPATH=/workspace/backend` is already set (scripts import `app.*`); elsewhere set it.
Scripts in a folder import their helpers by plain module name (`rag_common`, `reddit_posts`), so a
folder is self-contained.

| Folder | Responsibility | Scripts (in pipeline order) |
|---|---|---|
| `corpus/` | Build the knowledge base from the literature | `fetch_sources` -> `upload_raw_documents` -> `parse_raw_documents` -> `chunk_parsed_documents` -> `index_chunks`; `purge_sources` removes sources again |
| `db/` | Database setup and access | `init_db` (apply `backend/db/init.sql`), `psql.sh` (psql shell, `overview`); `load_chips_pg` + `chips_schema.sql` (experiment chip units into the schema `chips_eval`; it refuses `chips`, where the web application ingests approved answers), `chips_backup` (back up, verify, empty and restore the tables of `chips`) |
| `rag/` | Query the RAG and evaluate it | `ask`; evaluation: `eval_retrieval`, `eval_generation`, `judge_generations`, `report_eval`, `compare_runs`; expert notes: `eval_expert_units`, `eval_expert_generation`, `chat_expert` (human chat + ratings); shared `rag_common`; chip units (docs/new-chips-knowledge.md): `chip_retrieval`, `eval_chip_units`, `eval_chip_generation` (chips vs the B1 baseline, same questions and claims) |
| `elicitation/` | Elicitation documents: test fixtures and schema | `make_fixtures` (`--source synthetic|reddit`, see `docs/fixtures.md`), `fetch_reddit_pool`, `screen_reddit_posts`, `export_schema`; gold: `answer_vignettes` (a human answers in the terminal), `make_gold_claims` (an agent writes the claims); `migrate_q4_whatif` (one-off: schema 1.0 → 1.1, the Q4 what-if); chips test (docs/new-chips-knowledge.md, data in `data/fixtures_chips`): `chips_schema`, `make_chip_fixtures`, `classify_sentence_targets`, `chip_findings` (pure; tests in `test_chip_findings.py`, run by path), `build_chip_units`; `llm_clients`, `prompt_loader`, `leak_terms` and `reddit_posts` are helpers of `make_fixtures` (generation lives here, not in `backend/`) |

Rule of thumb: production logic belongs in `backend/app/`; a script only wires it together or
holds throwaway/example code (like the Reddit post reader).
