---
title: Backend indexing and proofread
diataxis: reference
---

# Backend modules `app.indexing` and `app.proofread`

Language: **English** · [Polski](../../pl/reference/backend-indexing-proofread.md)

`app.indexing` loads and validates `config/indexing.yaml` and builds the Ollama embedder. `app.proofread` proofreads a submitted answer (garbage removal, LanguageTool grammar, optional model enhancement, one sentence per line), links each line to a citation, and holds the author's edit-and-submit step. `app.proofread` has no router of its own; the assignments router exposes its service functions.

Related pages: [vignettes and knowledge](backend-vignettes-knowledge.md), [assignments and jobs](backend-assignments-jobs.md), [reviews](backend-reviews.md), [shared packages](packages.md), [retrieval and indexing](../explanation/retrieval-and-indexing.md), [architecture](../explanation/architecture.md).

## Indexing: public API

| Name | Signature | Behaviour |
|---|---|---|
| `load_indexing_config` | `(path: Path) -> IndexingConfig` | parses the YAML with `yaml.safe_load` and validates it; unknown keys fail validation |
| `build_embedder` | `(cfg: IndexingConfig) -> Embedder` | returns `OllamaEmbedder(model, batch_size, truncate)`; `dimensions` is not passed to the embedder |
| `bm25` | module | re-export of `expert_knowledge_core.bm25` |
| `Bm25Config`, `IndexingConfig` | classes | re-exported from the package |

`OllamaEmbedder.embed(texts) -> np.ndarray` (`backend/app/embeddings.py`) posts batches of `batch_size` texts to `/api/embed` on `ollama_base_url` with `truncate`, raises `RuntimeError` on HTTP 404 (model not pulled), and returns L2-normalised rows. Its HTTP client timeout is 300 seconds.

## Indexing configuration

The file is `config/indexing.yaml`. `app.knowledge.embedding` and `app.knowledge.ingest` read it from `settings.project_root / "config" / "indexing.yaml"`.

| Key | Type | Code default | Value in `config/indexing.yaml` | Description |
|---|---|---|---|---|
| `embeddings.model` | `str` | required | `bge-m3` | Ollama embedding model |
| `embeddings.batch_size` | `int`, > 0 | `64` | `32` | texts per Ollama request |
| `embeddings.truncate` | `bool` | `True` | `true` | passed to Ollama as `truncate` |
| `embeddings.dimensions` | `int`, > 0 | required | `1024` | expected vector width; `embed_texts` raises `RuntimeError` on a different shape |
| `text_field` | `contextual_text` or `text` | `contextual_text` | `contextual_text` | validated and stored in `IndexingConfig`; no code reads it |
| `sparse.k1` | `float`, > 0 | `1.2` | `1.2` | BM25 term-frequency saturation |
| `sparse.b` | `float`, 0 to 1 | `0.75` | `0.75` | BM25 length normalisation |
| `sparse.stemmer` | `str` or `None` | `english` | `english` | Snowball language, or `null` for no stemming |

No Python file under `backend`, `scripts` or `packages` reads `text_field`; `backend/app/indexing/config.py:29` only declares it. The BM25 fields are defined in `packages/expert-knowledge-core/src/expert_knowledge_core/bm25.py` (`Bm25Config`).

The models `EmbeddingConfig`, `IndexEmbeddingConfig`, `IndexingConfig` and the base `Model` use `extra="forbid"`.

## Proofread: settings

| Setting (env name) | Type | Default | Effect |
|---|---|---|---|
| `require_compute` (`REQUIRE_COMPUTE`) | `bool` | `False` | when true, a transport error from LanguageTool or Ollama fails the job instead of skipping the pass |
| `classifier_model` (`CLASSIFIER_MODEL`) | `str` | `qwen3.5:9b` | model that files uncited sentences |
| `enhance_model` (`ENHANCE_MODEL`) | `str` | `qwen3.5:9b` | model for the enhancement pass; an empty string switches the pass off |
| `languagetool_url` (`LANGUAGETOOL_URL`) | `str` | `http://localhost:8010` | LanguageTool server |
| `languagetool_language` (`LANGUAGETOOL_LANGUAGE`) | `str` | `en-US` | `language` field of the check request |
| `languagetool_timeout` (`LANGUAGETOOL_TIMEOUT`) | `float` | `60` | request timeout in seconds |
| `ollama_base_url` (`OLLAMA_BASE_URL`) | `str` | `http://localhost:11434` | Ollama server |
| `ollama_request_timeout` | `float` | `600` | Ollama chat timeout (settings comment: one reply can include loading the model) |

`Settings` sets no environment prefix; `.env.example` lists the upper-case names `REQUIRE_COMPUTE`, `CLASSIFIER_MODEL`, `ENHANCE_MODEL`, `LANGUAGETOOL_URL` and `OLLAMA_BASE_URL`.

## Proofread: pipeline (`pipeline.py`)

`proofread_answer(question: str, answer: str, quotes: dict[int, str], vignette: str) -> Proofread` runs, in order:

1. `garbage.drop_garbage` with the vignette's vocabulary as protected words.
2. `grammar.check` (pass key `grammar`).
3. `enhance.enhance`, when the text left is not blank.
4. `grammar.check` again on the enhanced text (pass key `grammar_after`), when the enhancement is accepted.
5. `layout`, which puts one sentence per line using `split_sentences`.

`Proofread` is a dataclass with `text`, `dropped` (sentences removed) and `passes`.

`passes` entries:

| Key | Value |
|---|---|
| `dropped` | number of sentences dropped |
| `grammar`, `grammar_after` | number of edits applied, or `"unavailable"` when the check was skipped |
| `languagetool` | LanguageTool software version from the reply, when present |
| `enhanced` | `True` when the enhanced text is used, `False` when no enhancement ran or it was refused, `"unavailable"` when the model call failed |
| `enhance_rejected` | refusal code from `enhance.rejection` |

A pass is skipped and recorded when `SERVICE_ERRORS = (httpx.HTTPError, OSError, KeyError, ValueError)` is raised, except that with `require_compute` a `httpx.TransportError` is re-raised. Other exceptions propagate.

### Garbage removal (`garbage.py`)

| Name | Value / behaviour |
|---|---|
| `MIN_LETTERS` | `3` |
| `UNKNOWN_SHARE` | `0.5` |
| `ACRONYM_LETTERS` | `5` |
| `unknown(word, vignette_words) -> bool` | false for words shorter than `MIN_LETTERS`, words in the vignette, and all-caps words of at most `ACRONYM_LETTERS` letters; otherwise true when `wordfreq.zipf_frequency(word, "en")` is `0` |
| `is_garbage(sentence, vignette_words) -> bool` | counts words of at least `MIN_LETTERS` letters outside chips; true when the unknown share is at least `UNKNOWN_SHARE`; false for a sentence without such words |
| `drop_garbage(text, vignette_words) -> (text, dropped)` | splits each line into pieces after `.`, `!` or `?`, drops garbage pieces, keeps line breaks, removes lines left empty |

### Grammar (`grammar.py`)

`check(text, protected) -> Checked` returns `Checked(text=text)` for blank text. Otherwise it posts to `{languagetool_url}/v2/check` with `language` and `data` (annotated text in which each chip `⟦hN⟧` is markup read as `"…"`, constant `CHIP_READS_AS`), and applies the reply with `apply`.

`apply(text, reply, protected) -> Checked` goes through matches from the end of the text backwards, applies the first replacement of each wanted match, and skips matches that extend past the start of an already applied replacement (`end > edge`) and matches that overlap a chip; a match that only abuts a chip is kept. Offsets are converted from UTF-16 units to code points.

| Name | Value / behaviour |
|---|---|
| `APPLIED_CATEGORIES` | `GRAMMAR`, `PUNCTUATION`, `CASING`, `CONFUSED_WORDS`, `COMPOUNDING`, `TYPOS` |
| `SPELLING_CATEGORY` | `TYPOS` |
| `SPELLING_GAP` | `1.4` (zipf scale) |
| `CLINICAL_TERMS` | `frozenset` of clinical words (for example `adhd`, `ritalin`, `dopamine`) never spell-corrected |
| `spelling_fix_wanted(word, replacement, protected) -> bool` | false for blank words, words in `protected` or `CLINICAL_TERMS`; true when the written word has zipf frequency 0 or the replacement is at least `SPELLING_GAP` more frequent |
| `vocabulary(text) -> set[str]` | lower-case words of a text |
| `Checked` | dataclass: `text`, `edits`, `version`, `skipped` (rule ids seen and not applied) |

### Enhancement (`enhance.py`)

| Name | Value / behaviour |
|---|---|
| `PROMPT` | `Answer_enhance.v2` |
| `OPTIONS` | `temperature` 0.2, `num_ctx` 8192, `num_predict` 1200; the call also sends `seed` 1 |
| `GROWTH`, `SLACK_WORDS` | `2.5`, `40` |
| `LEAK_WORDS` | `2` |
| `enhance(question, answer, quotes) -> (text or None, refusal or None)` | `(None, None)` when `enhance_model` is empty or the answer is blank; otherwise one model call and `rejection` on the reply |
| `rejection(raw, answer, quotes) -> str or None` | returns the first failing code of the list below |
| `leaked(reply, answer, quotes) -> list[str]` | stems of the reply that occur in a cited passage and not in the answer |
| `narrated(text) -> int` | count of first-person narration patterns outside quotation marks |

Refusal codes, in the order checked:

| Code | Condition |
|---|---|
| `not_json` | the reply is not a JSON object with a string `answer` |
| `empty` | the `answer` is blank |
| `chips` | the chips in the reply differ from those in the answer (counted with repeats) |
| `too_long` | the reply has more than `GROWTH` x the answer's words + `SLACK_WORDS` |
| `leak` | at least `LEAK_WORDS` leaked stems |
| `voice` | `narrated(reply)` is greater than `narrated(answer)` |

The prompt receives the question and the answer; the cited passages are passed to the checks only.

## Proofread: linking (`links.py`)

A line is a dict `{text, targets, assigned_by}`. `targets` holds highlight ids (`h1`, `i1`) and `case`; it is empty while the line is unlinked.

| Function | Behaviour |
|---|---|
| `lines_of(text) -> list[str]` | stripped non-empty lines |
| `link_lines(answers, highlights, vignette) -> dict[str, list[Line]]` | layers 1 and 2 through `findings.link_text`; appends implicit highlights to `highlights` |
| `as_sentences(linked) -> list[dict]` | lines in sentence shape with ids `Q<n>.<index>` |
| `classify_rest(linked, highlights, vignette) -> dict` | layer 3: calls `classifier.classify` for lines without targets, applies the result, updates `linked` in place; returns `{left, attempts}` |
| `relink(old, text, overrides, highlights, vignette) -> list[Line]` | per line, the first that applies: author override (`assigned_by` `expert`), links of an old line with the same text, `findings.link_text`; never calls a model |
| `unlinked(lines) -> list[int]` | zero-based positions of lines without targets |

## Proofread: service (`service.py`)

| Function | Behaviour | Errors |
|---|---|---|
| `view(db, assignment, actor, review_round=None) -> ProofreadView` | the round `review_round`, or the assignment's current round | 404 `not_found` for a reviewer or a missing round |
| `save(db, assignment, actor, body: ProofreadSave) -> ProofreadView` | locks the open round; checks `body.version`; for each given answer checks chips (`check_chips`); relinks the lines of filed answers with the overrides; recomputes flags with `findings.check`; increments `version` | 403 `forbidden` for a non-author; 409 `not_editable` outside state `PROOFREAD_CHECK`; 409 `proofread_conflict` (details `current_version`); 422 `question_not_answered`, `no_target`, `unknown_target` |
| `submit_for_review(db, assignment, actor, viewer)` | checks the transition `SUBMIT_FOR_REVIEW`, then that no answer is blank and no filed line is unlinked; sets `submitted_at` and transitions the assignment | 422 `empty_answer` (details `question_ids`), 422 `links_missing` (details `lines`) plus the errors of `check_transition` and the editability checks (403 `forbidden`, 409 `not_editable`) |
| `open_next_round(db, assignment, feedback)` | adds a round numbered `assignment.review_round` that copies the previous round's highlights, flags, passes, classifier, prompt and each answer's text and lines; `feedback` is stored on the round | |
| `prepare(assignment_id) -> dict` | job part without a transaction: runs `proofread_answer` for each answered question in question order, links filed answers (`link_lines`, then `classify_rest`), computes flags | |
| `record(db, assignment, prepared)` | deletes the round for `assignment.review_round` and inserts the round and its `AnswerRevision` rows with `final` equal to `proposed` | |
| `get_round`, `revisions`, `answer_hash`, `highlight_views`, `line_views` | helpers: read a round, read its answers in question order, hash text plus link targets, build view models | |

`prepare` stores `classifier` and `prompt` on the round only when `classify_rest` reported lines left (`info["left"]`). `passes` holds one entry per question (the pipeline's `passes`) and a `links` entry.

`view` sets `editable` to true when the actor is the assignee, the assignment state is `PROOFREAD_CHECK` and `submitted_at` is empty.

### HTTP surface

The assignments router mounts these under `/api/v1` (`backend/app/assignments/router.py`):

| Method and path | Service function |
|---|---|
| `GET /assignments/{assignment_id}/proofread` (query `review_round`) | `view` |
| `PUT /assignments/{assignment_id}/proofread` (body `ProofreadSave`) | `save` |
| `POST /assignments/{assignment_id}/submit-for-review` | `submit_for_review` |

## Proofread: schemas (`schemas.py`)

| Model | Fields |
|---|---|
| `ProofreadSave` (`extra="forbid"`) | `version: int`, `answers: dict[QuestionId, AnswerText]`, `overrides: dict[QuestionId, dict[LineText, list[TargetId]]]` (default empty) |
| `ProofreadView` | `review_round`, `version`, `editable`, `submitted_at`, `feedback`, `highlights`, `flags`, `passes`, `items` |
| `ProofreadItem` | `question_id`, `question`, `original`, `proposed`, `final`, `linked`, `lines`, `dropped` |
| `AnswerLine` | `text`, `targets`, `assigned_by` (`chip`, `quote`, `llm`, `expert` or `None`) |
| `LinkedHighlight` | `id`, `chip` (`None` for an implicit highlight), `text`, `span`, `origin`, `direction` |
| `ProofreadFlag` | `kind`, `highlight`, `message` |
| `ProofreadFeedback` | `question_id`, `comment` |

`LineText` has a maximum length of 5000; `TargetId` matches `^(h\d+|i\d+|case)$`. `linked` is true for questions that `findings.is_filed` accepts (open questions except Q4).

## Proofread: data model (`models.py`)

| Model | Table | Columns |
|---|---|---|
| `ProofreadRound` | `proofread_rounds` | PK (`assignment_id` FK cascade delete, `review_round`); `version` (default 1, incremented by each save), `highlights` JSONB, `flags` JSONB, `passes` JSONB, `classifier`, `prompt`, `feedback` JSONB (`[{question_id, comment}]`), `submitted_at`, `created_at`, `updated_at` |
| `AnswerRevision` | `answer_revisions` | PK (`assignment_id`, `review_round`, `question_id`) with a composite FK to `proofread_rounds` (cascade delete); `original`, `proposed`, `final`, `lines` JSONB, `dropped` JSONB |

## Sources in code

- `backend/app/indexing/__init__.py` - re-exports and build_embedder
- `backend/app/indexing/config.py` - IndexingConfig models and load_indexing_config
- `backend/app/embeddings.py` - OllamaEmbedder behaviour and defaults
- `config/indexing.yaml` - configured values
- `packages/expert-knowledge-core/src/expert_knowledge_core/bm25.py:21-26` - Bm25Config fields and defaults
- `backend/app/knowledge/embedding.py` - where the config file is read
- `backend/app/proofread/pipeline.py` - proofread_answer, passes, skip rules
- `backend/app/proofread/garbage.py` - garbage removal
- `backend/app/proofread/grammar.py` - LanguageTool client and fix rules
- `backend/app/proofread/enhance.py` - enhancement and refusal codes
- `backend/app/proofread/links.py` - line linking
- `backend/app/proofread/service.py` - view, save, submit, rounds, job halves
- `backend/app/proofread/schemas.py` - view and save models
- `backend/app/proofread/models.py` - ProofreadRound, AnswerRevision
- `backend/app/assignments/router.py:112-138` - proofread endpoints
- `backend/app/settings.py` - settings fields and defaults
- `backend/app/main.py:19` - API prefix
- `.env.example` - upper-case environment names
