---
title: Backend vignettes and knowledge
diataxis: reference
---

# Backend modules `app.vignettes` and `app.knowledge`

Language: **English** · [Polski](../../pl/reference/backend-vignettes-knowledge.md)

`app.vignettes` holds the admin-authored vignette texts, their versions and the fixed question set, and serves the admin endpoints under `/api/v1/vignettes` and `/api/v1/vignette-versions`. `app.knowledge` cuts approved answers into knowledge units, embeds them, writes them to the `chips` schema, and serves the admin endpoints under `/api/v1/knowledge-units`. Both routers are mounted in `backend/app/main.py` under the prefix `/api/v1`; every endpoint below requires an admin user (`AdminUser`).

Related pages: [assignments and jobs](backend-assignments-jobs.md), [reviews](backend-reviews.md), [indexing and proofread](backend-indexing-proofread.md), [shared packages](packages.md), [retrieval and indexing](../explanation/retrieval-and-indexing.md), [architecture](../explanation/architecture.md).

Error bodies use the codes below. `invalid(...)` errors answer HTTP 422, `not_found` answers 404, and a `DomainError` without an explicit status answers 409 (`backend/app/core/errors.py`).

## Vignettes: HTTP endpoints

| Method and path | Body / query | Result | Errors |
|---|---|---|---|
| `GET /vignettes/questions` | none | list of `QuestionTemplate` (`id`, `kind`, `text`) for Q1-Q6; Q4 keeps the `{whatif}` placeholder | none beyond auth |
| `GET /vignettes` | none | list of `VignetteAdminView` ordered by `code`; each holds all its versions ordered by version number | none beyond auth |
| `POST /vignettes` (201) | `VignetteCreate` | `VignetteAdminView` with the vignette and version 1 as a draft; audit action `vignette_created` | 409 `vignette_code_taken`; 422 content-rule codes |
| `POST /vignettes/{vignette_id}/versions` (201) | `VersionContent` | `VersionAdminView` with the next version number, picked under a row lock on the vignette; audit action `version_created` | 404 `not_found`; 422 content-rule codes |
| `PATCH /vignette-versions/{version_id}` | `VersionUpdate` | `VersionAdminView`; the update is merged with the stored content and re-validated | 409 `version_not_draft`; 422 `validation_error` (details `fields`); 422 content-rule codes |
| `POST /vignette-versions/{version_id}/publish` | none | `VersionAdminView` with status `published` and `published_at`; audit action `version_published` | 409 `version_not_draft`; 422 `word_count_out_of_range`, `summary_missing`, `construct_word_in_text` |
| `POST /vignette-versions/{version_id}/retire` | none | `VersionAdminView` with status `retired`; audit action `version_retired`; stops new assignments, and assignments already made run on this version | 409 `version_not_published` |

`publish`, `retire` and `PATCH` lock the version row before they read its status.

## Vignettes: validation rules

### Content rules (`validate_content`)

`validate_content(content: VersionContent) -> None` runs on create, add-version and update, in this order. Each failure is a 422 with a stable code.

| Code | Condition |
|---|---|
| `q4_without_whatif` | `q4_whatif` is empty or blank |
| `control_with_cues` | `design.is_control` is true and `design.planted_cues` is not empty |
| `track_without_target` | `design.track` is `text_analysis` and `design.knowledge_target` is empty |
| `variant_b_without_change` | `variant.arm` is `B` and `variant.change` is empty |
| `span_not_in_text` | a `planted_cues[].quote` or `confounders[].quote` is not a substring of `text` (details: `quote`) |

### Publish rules (`publish_version`)

| Code | Condition |
|---|---|
| `word_count_out_of_range` | `len(text.split())` is outside `MIN_WORDS, MAX_WORDS = 120, 250` (details: `words`) |
| `summary_missing` | `patient_summary` is blank |
| `construct_word_in_text` | `check_construct_words` finds a construct term in `text`, `q4_whatif` or `patient_summary`, checked in that order (details: `field`, `term`) |

Construct terms are the case-insensitive pattern `adhd`, `attention deficit` (space or hyphen), `methylphenidate`, `ritalin`, `concerta`, `medikinet`, `adderall`, `vyvanse`, `elvanse`, `lisdexamfetamine`, `dexamfetamine`, `atomoxetine`, `strattera`, `guanfacine`, `intuniv` (`_CONSTRUCT_TERMS`), plus the uppercase word `ADD` (`_ADD_UPPERCASE`; the lowercase verb passes). The check runs at publish time only; a draft may contain these words.

### Schema constraints (`vignettes/schemas.py`)

| Model | Field | Constraint |
|---|---|---|
| `VignetteCreate` | `code` | pattern `^V\d{3,}$`, max length 32 |
| `VersionContent` | `text` | length 1 to 20000 |
| | `framing` | `forum_post`, `personal_journal` or `email` (`Framing`); required |
| | `q4_whatif` | optional, max length 1000 |
| | `patient_summary` | default `""`, max length 600 |
| | `variant`, `design` | `VariantInfo` optional; `VignetteDesign` required |
| `VersionUpdate` | all fields | optional; same limits as `VersionContent`; `design` and `variant` replace the stored value as a whole |
| `PlantedCue` | `quote`, `trait`, `strength` | `quote` min length 1; `strength` is `weak`, `moderate` or `strong` |
| `Confounder` | `quote`, `alternative_explanation` | `quote` min length 1 |
| `VariantInfo` | `pair_id`, `arm`, `change` | `arm` is `A` or `B`; `change` optional |
| `VignetteDesign` | `purpose` `""`, `notes` `""`, `planted_cues` `[]`, `confounders` `[]`, `is_control` `False`, `track` `general`, `knowledge_target` `None`, `origin` `hand_written`, `population` `adult`, `source_ref` `None` | `track` is `general` or `text_analysis`; `origin` is `llm`, `real_text` or `hand_written` |

`VersionContent`, `VignetteCreate`, `VersionUpdate`, `PlantedCue`, `Confounder`, `VariantInfo` and `VignetteDesign` reject unknown keys (`extra="forbid"`), so a client cannot send `question_ids`. `VersionAdminView` adds `id`, `vignette_id`, `version`, `status`, `content_hash`, `question_ids`, `created_at`, `published_at` and a computed `word_count`. `VignetteAdminView` holds `id`, `code`, `created_at` and `versions`.

## Vignettes: data model

| Model | Table | Columns |
|---|---|---|
| `Vignette` | `vignettes` | `id` UUID, `code` String(32) unique, `created_by` (FK `app.users.id`), `created_at` |
| `VignetteVersion` | `vignette_versions` | `id`, `vignette_id` (FK, indexed), `version`, `status`, `text`, `content_hash` String(64), `framing` String(32), `question_ids` ARRAY(String(8)), `q4_whatif`, `patient_summary` (default `""`), `variant` JSONB, `design` JSONB, `created_at`, `published_at`; unique (`vignette_id`, `version`) |

`VersionStatus` values: `draft` (default), `published`, `retired`. `question_ids` is always the list `Q1`..`Q6` (`QUESTION_IDS`). `content_hash` is `content_hash(text)` from `app.core.security`.

## Vignettes: questions (`questions.py`)

`QuestionId` is `Q1`..`Q6`; `QuestionKind` is `open`, `shift` or `rating_1_5`. `Question` is a frozen dataclass with `id`, `kind`, `text`, `min_words`. The comments in the file state that `min_words` is used by `scripts/elicitation` only; the API neither sends nor enforces it.

| Id | Kind | `min_words` | Text starts |
|---|---|---|---|
| Q1 | `open` | 15 | "Which fragments of the text matter for your reading of ADHD-related traits…" |
| Q2 | `open` | 10 | "Which of those fragments could equally reflect something else…" |
| Q3 | `open` | 10 | "What is missing from this text…" |
| Q4 | `shift` | 5 | "Given your hypothesis about this person so far: how would it change if {whatif}?" | <!-- lint-ignore -->
| Q5 | `open` | 10 | "What would a less experienced clinician likely over- or under-interpret…" |
| Q6 | `rating_1_5` | none | "Overall, how strongly does this text show ADHD-related traits?…" |

Other names in the file:

| Name | Value / signature | Meaning |
|---|---|---|
| `QUESTIONS` | `dict[str, Question]` keyed by id | the question set |
| `GATE` | `("Q1", "Q2", "Q3")` | Q4-Q6 are shown after every asked gate question has a non-blank answer; the gate answers are then locked (comment in the file) |
| `HYPOTHESIS_MIN_WORDS` | `3` | scripts only (comment in the file) |
| `Q4_HYPOTHESIS`, `SHIFT_LEAD`, `Q4_TOWARD`, `Q4_WHY` | "Your working hypothesis, in one sentence", "With this, my hypothesis…", "Towards…", "Why?" | Q4 step wording |
| `SHIFT_LABELS` | `-2` "is strongly reinforced", `-1` "is somewhat reinforced", `0` "is unchanged", `1` "partly changes", `2` "changes completely" | labels of the shift scale |
| `TOWARD_LABELS` | `more_adhd` "more ADHD-like", `less_adhd` "less ADHD-like", `other` "another explanation" | direction labels |
| `Q4_WORDING` | dict with `hypothesis`, `shift_lead`, `shift_labels` (string keys), `toward`, `toward_labels`, `why` | the wording sent to the frontend |
| `render_question(question, q4_whatif) -> str` | | returns the text; for Q4 fills `{whatif}` with the what-if stripped of trailing `?` and `.`; raises `ValueError` if Q4 has no what-if |
| `describe_shift(shift, toward=None, other=None) -> str` | | one-line description of a Q4 answer, for example "+1 partly changes, towards less ADHD-like" |

## Vignettes: service and import functions

| Function | Behaviour |
|---|---|
| `opening_words(text, count=40) -> str` | the first `count` words, with a trailing "…" when the text is longer |
| `create_vignette(db, code, content, admin)` | validates, inserts the vignette (a duplicate code raises `vignette_code_taken`), inserts version 1 |
| `add_version(db, vignette_id, content, admin)` | locks the vignette row, inserts version `max(version) + 1` |
| `update_version(db, version_id, changes)` | draft only; merges `changes.model_dump(exclude_unset=True)` over the stored fields; an explicit `null` for a required field yields `validation_error` |
| `publish_version(db, version_id, admin)`, `retire_version(db, version_id, admin)` | status transitions described above |
| `version_and_code(db, version_id) -> (VignetteVersion, str)` | the version and its vignette code |
| `list_vignettes(db)` | all vignettes with all versions |
| `read_whatifs(path) -> dict[str, str]` | reads a JSON object mapping code to what-if text; raises 422 `whatifs_unreadable` for an unreadable file, invalid JSON or a different shape |
| `plan_import(directory, whatifs) -> dict[str, VersionContent]` | reads every `V*.json` in `directory` in sorted order; for each file the `id` field is the code, the keys `text`, `framing`, `variant`, `design` are kept, and `q4_whatif` comes from `whatifs`; runs `validate_content`; raises one 422 `import_refused` that lists every problem, or `no_vignette_files` when the folder has none; a what-if without a matching file is also listed as a problem; a file whose code has no non-blank what-if is listed with the message "no what-if for this vignette." |
| `async import_vignettes(db, directory, whatifs, admin) -> ImportResult(created, skipped)` | calls `plan_import` first, so nothing is written when any file is invalid; creates a draft (version 1) for each new code and skips codes that exist |

The CLI command `python -m app.cli import-vignettes --dir DIR --whatifs FILE --admin-email EMAIL` calls the import (`backend/app/cli.py`).

## Knowledge: HTTP endpoints

| Method and path | Parameters | Result | Errors |
|---|---|---|---|
| `GET /knowledge-units` | query `status` (a `UnitStatus`), `limit` 1-500 (default 100), `offset` >= 0 (default 0) | list of `KnowledgeUnitListItem`, newest first (`created_at` descending, then `ordinal`, `id`) | none beyond auth |
| `POST /knowledge-units/search` | body `KnowledgeSearchRequest` | `KnowledgeSearchResponse` (`hits`) | 503 `embedding_unavailable` |
| `GET /knowledge-units/index` | none | `IndexStatus`; `up_to_date` when no refit job exists or the latest one is done, otherwise the latest refit job's status value and its `last_error` | none beyond auth |
| `POST /knowledge-units/index/refit` (202) | none | `IndexStatus` with state `queued`; queues a refit job unless one is already queued | none beyond auth |
| `DELETE /knowledge-units/{unit_id}` (204) | none | removes one unit | 404 `not_found` when the unit is missing or not `ingested` |
| `DELETE /knowledge-units/by-expert/{expert_id}` | none | `UnitsRemoved` (`removed`); removes every `ingested` unit of the expert's assignments; when it removed any, audits `knowledge_withdrawn` on the user with `units` count | 404 `not_found` when the user is missing |

`KnowledgeSearchRequest`: `query` (length 1-4000), `mode` (`question` default, or `patient_text`), `k` (1-20, default 8). `KnowledgeHit`: `rank`, `score`, `similarity`, `matched_sentence`, `unit`. `score` is the retrievers' fusion score and orders the hits; `similarity` is the cosine between the query embedding and the stored one and is `None` when it cannot be computed.

## Knowledge: data model

| Model | Table | Columns |
|---|---|---|
| `KnowledgeUnit` | `knowledge_units` | `id`, `assignment_id` (FK), `submission_id` (FK), `ordinal`, `review_round` (default 1), `text`, `content_hash` String(64), `kind` (`fragment` or `case`), `highlight_id` (`h1`, `i1`; `None` for the case unit), `direction` (`toward`, `away`, `neutral`, `unclear`), `patient_words`, `sentence_ids` ARRAY, `context` ARRAY (co-cited highlights), `embed_text` (I1), `status` (indexed, default `pending`), `created_at`; unique (`assignment_id`, `review_round`, `ordinal`) |
| `AnswerFindings` | `answer_findings` | `assignment_id` (PK, FK, cascade delete), `record` JSONB, `version` (default 1), `check_outcome` (`completed` or `skipped`), `classifier`, `prompt`, `findings_version`, `created_at`, `updated_at` |

`UnitStatus` values: `pending`, `approved`, `rejected`, `ingested`, `superseded`, `removed`. A superseded unit was cut in an earlier review round. A removed unit was taken out of the knowledge base after ingestion.

`KnowledgeUnitListItem` carries the unit columns above plus `vignette_code`, `vignette_version`, `expert_id`, `expert_pseudonym`, `sentences` (`UnitSentence`: `id`, `question_id`, `assigned_by`), `context` (`CitedTogether`: `id`, `text`), `framing`, `classifier`, `prompt`, `findings_version`. `unit_items` builds it by joining the assignment, version, vignette and expert and reading the assignment's findings `record`; a sentence id that is absent from the record is left out. `IndexStatus.state` is `up_to_date`, `queued`, `running` or `failed`.

## Knowledge: functions

### Findings (`findings.py`, no models)

| Function | Behaviour |
|---|---|
| `is_filed(question_id) -> bool` | true for open questions except Q4 |
| `response_from_submission(payload, vignette_code, vignette_version) -> Response` | keeps the answers of filed questions, the highlights, the rating and `insufficient_information` |
| `match_in_text(piece, text) -> (start, end, ratio) or None` | needs at least `MIN_QUOTE_WORDS = 2` words; exact case-insensitive match first, then the best word window with difflib ratio at least `QUOTE_RATIO = 0.6` |
| `expert_highlights(highlights) -> list[dict]` | highlight records with id `h<chip>` and origin `expert` |
| `link_text(text, highlights, vignette) -> (targets, assigned_by)` | chips in the sentence give `chip`; otherwise quoted pieces that overlap a highlight (at least half of the shorter span) or match the vignette give `quote`, appending an implicit highlight `i<n>` when none overlaps; otherwise `([], None)` |
| `unresolved(sentences) -> list[str]` | ids of sentences without targets |
| `apply_classification(sentences, labels) -> list[str]` | applies classifier labels; `prev` copies the previous sentence's targets in the same answer; a missing or invalid label becomes `case`; returns the fallback ids; sets `assigned_by` to `llm` |
| `check(highlights, sentences) -> list[dict]` | flags of kind `coverage` (an expert highlight with no sentence) and `direction` (regex patterns `LOWERING` and `RAISING` against the marked direction); changes nothing |
| `build_units(rec) -> list[dict]` | one fragment unit per highlight that is the target of at least one sentence, plus a `case` unit when at least one sentence targets `case`; sets `body` and `i1` (header and sentences) |
| `record_from_lines(resp, lines, highlights, session_id, expert_id, role, framing, population) -> dict` | builds sentences from already linked lines, then `flags` and `units`; links nothing again |

`Highlight` (`chip`, `text`, `span`, `direction`) and `Response` (`vignette_id`, `vignette_version`, `answers`, `highlights`, `rating`, `insufficient_information`) are frozen dataclasses. The module re-exports helpers from `expert_knowledge_core.notes` and `CASE`, `FINDINGS_VERSION` from `expert_knowledge_core.records` (see [packages](packages.md)).

### Classifier (`classifier.py`)

| Name | Value / behaviour |
|---|---|
| `PROMPT` | `Expert_sentence_targets.v1` |
| `OPTIONS` | `temperature` 0.2, `num_predict` 600, `num_ctx` 8192 |
| `RETRIES` | 3 |
| `classify(vignette, highlights, sentences, left, *, retries=RETRIES, seed=1) -> (labels, info)` | one JSON-mode Ollama call per attempt, up to `retries + 1` attempts with seed `seed + attempt * 7919`; keeps the reply with the most valid labels; stops at the first reply without errors; returns `({}, info)` without a call when `left` is empty; `info` is `{attempts, errors}`; a model that cannot be reached raises |
| `check_labels(raw, sentences, left, allowed) -> (good, errors)` | accepts a non-empty list of strings per sentence id; rejects unknown ids, `prev` combined with other ids, and `prev` on the first sentence of an answer; a reply that is not a JSON object is one error |
| `ask(system, user, seed)` | calls `chat_json` with `settings.classifier_model` |

### Embedding (`embedding.py`)

`embed_texts(texts: list[str]) -> list[list[float]]` returns `[]` for no texts. Otherwise it embeds in a thread with the embedder built from `config/indexing.yaml` (cached with `lru_cache`) and raises `RuntimeError` when the result shape differs from (number of texts, `embeddings.dimensions`). The configuration is described in [indexing and proofread](backend-indexing-proofread.md#indexing-configuration).

### Ingestion (`ingest.py`)

| Name | Behaviour |
|---|---|
| `TIER` | `"app"`, the `tier` written to `chips.vignettes` |
| `BM25_LOCK` | `4_715_331_001`, the advisory lock key shared by `write`, `remove_units` and the refit job |
| `load(db, assignment_id) -> Ingestion` | reads the assignment's units with status `approved` or `ingested`; raises `NoUnits` when there are none, `UnitsNotEmbeddable` when a unit lacks `embed_text`, `NoFindings` when there is no `answer_findings` row; cuts the stored record down to the units' highlights and sentences |
| `embed(data) -> Ingestion` | embeds the I1 texts of the units and the highlight texts (I2) in one call; raises `RuntimeError` if the vector count differs from units + highlights |
| `write(db, data)` | takes the advisory lock, deletes the assignment's `chips.elicitation_sessions` row, then inserts into `chips.experts`, `chips.vignettes`, `chips.elicitation_sessions`, `chips.cue_keys`, `chips.highlights`, `chips.answer_sentences`, `chips.finding_units`, `chips.finding_unit_sentences`, `chips.unit_cues` and `chips.review_events`, then calls `refresh_sparse`; runs inside the caller's transaction |
| `refresh_sparse(db)` | refits BM25 over the unit texts I1 and the cue key texts, each with its own statistics, using the `sparse` section of `config/indexing.yaml`; writes `chips.finding_units.sparse` and `chips.cue_keys.sparse` |
| `Ingestion` | dataclass: `session_id`, `expert_id`, `created_at`, `vignette`, `document`, `events`, `segmenter`, `meta`, `track`, `vectors` |

`load` builds review events from the findings `record`: `record["flags_shown"]` entries become `flag_shown` events, and `record["corrections"]` entries of kind `sentence_moved` or `toggle_changed` become events of the same name; a `check_outcome` of `skipped` adds a `skipped` event. The proofread job writes `flags_shown` and an empty `corrections` list when it records the findings (`backend/app/jobs/handlers.py:79-88`); no code under `backend/app` fills `corrections` with entries.

### Removal and search

| Function | Behaviour |
|---|---|
| `removal.enqueue_refit(db)` | adds a `REFIT` job unless a queued one exists; a running one does not count |
| `removal.remove_units(db, units, actor_id) -> int` | ignores units that are not `ingested`; takes the `BM25_LOCK` advisory lock; deletes the units' `chips.finding_units` rows; deletes the session row when it has no units left, otherwise removes the units from the session `document`; deletes `chips.cue_keys` no highlight or unit cue points at, and `chips.experts` without a session; sets the status to `removed`; audits `unit_removed` per unit; queues a refit; returns the count |
| `search.search(db, request) -> KnowledgeSearchResponse` | runs `PatientTextRetriever` (mode `patient_text`) or `ExpertQuestionRetriever` (mode `question`) with `merge_shared=False` over `ExpertKnowledgeStore`; maps each note to an `ingested` unit and skips notes whose unit changed meanwhile; question mode computes the cosine against the stored I1 vector (`chips.finding_units.embedding`), patient mode takes the best cosine between a typed sentence and the unit's cue embedding and returns that sentence as `matched_sentence`; an embedding error (`httpx.HTTPError`, `OSError`, `RuntimeError`) becomes 503 `embedding_unavailable` |

The background job kinds that use these modules are registered in `backend/app/jobs/handlers.py`: `PROOFREAD`, `INGEST` (`prepare_ingest`, then `ingest`, which marks `approved` units `ingested`) and `REFIT` (takes `BM25_LOCK`, runs `refresh_sparse`).

## Configuration

| Setting (env name) | Type | Default | Used by |
|---|---|---|---|
| `classifier_model` (`CLASSIFIER_MODEL`) | `str` | `qwen3.5:9b` | `classifier.ask` |
| `project_root` | `Path` | the parent of `backend/` | location of `config/indexing.yaml` for `embedding` and `refresh_sparse` |
| `ollama_base_url` (`OLLAMA_BASE_URL`) | `str` | `http://localhost:11434` | the embedder and `chat_json` |
| `ollama_request_timeout` | `float` | `600` | Ollama chat calls (settings comment: one reply can include loading the model) |

`Settings` sets no environment prefix, and `.env.example` lists the upper-case names. The embedding model, batch size, dimensions and BM25 parameters come from `config/indexing.yaml` and are listed on the [indexing page](backend-indexing-proofread.md#indexing-configuration).

## Sources in code

- `backend/app/vignettes/router.py` - vignette endpoints
- `backend/app/vignettes/service.py` - content rules, publish rules, version lifecycle, listing
- `backend/app/vignettes/schemas.py` - request and view models and their constraints
- `backend/app/vignettes/models.py` - Vignette, VignetteVersion, VersionStatus
- `backend/app/vignettes/questions.py` - question set, Q4 wording, render_question, describe_shift
- `backend/app/vignettes/importing.py` - read_whatifs, plan_import, import_vignettes
- `backend/app/knowledge/router.py` - knowledge endpoints
- `backend/app/knowledge/schemas.py` - request and response models
- `backend/app/knowledge/models.py` - KnowledgeUnit, AnswerFindings, UnitStatus
- `backend/app/knowledge/service.py` - unit_items
- `backend/app/knowledge/findings.py` - linking, checks, unit building
- `backend/app/knowledge/classifier.py` - sentence classifier
- `backend/app/knowledge/embedding.py` - embed_texts
- `backend/app/knowledge/ingest.py` - load, embed, write, refresh_sparse
- `backend/app/knowledge/removal.py` - remove_units, enqueue_refit
- `backend/app/knowledge/search.py` - admin test search
- `backend/app/jobs/handlers.py:79-168` - findings record, units, job handlers
- `backend/app/main.py:19,53-62` - API prefix and router mounting
- `backend/app/core/errors.py:23-49` - status codes of error helpers
- `backend/app/settings.py` - settings fields and defaults
- `backend/app/cli.py` - import-vignettes command
- `.env.example` - upper-case environment names
