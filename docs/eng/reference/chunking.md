---
title: Chunking and corpus configuration
diataxis: reference
---

# Chunking and corpus configuration

Language: **English** · [Polski](../../pl/reference/chunking.md)

`scripts/corpus/chunking` cuts parsed corpus documents into chunks with a semantic chunker, driven by `config/chunking.yaml`. This page also lists the keys of `config/indexing.yaml` (embedding and BM25 settings of the chunk index) and `config/sources.yaml` (the source manifest of the corpus fetch stage), with the defaults their pydantic models define. The design reasons are in [Retrieval and indexing](../explanation/retrieval-and-indexing.md); the package that supplies the BM25 settings is in [Packages](packages.md), and the backend module that validates `indexing.yaml` is in [Backend: indexing and proofreading](backend-indexing-proofread.md).

All four config models (`ChunkingConfig` and its parts, `IndexingConfig` and its parts, `Manifest` and its parts, `Bm25Config`) forbid unknown keys (`extra="forbid"`), so a misspelled key fails on load.

## Public API of `scripts/corpus/chunking`

| Name | Description |
|---|---|
| `build_chunker(cfg: ChunkingConfig) -> Chunker` | Builds a `TokenCounter(cfg.tokenizer)` and an `OllamaEmbedder(**cfg.embeddings.model_dump())`. For `method == "semantic"` it returns `SemanticChunker(cfg.semantic, embedder, count)`; any other value raises `ValueError`. |
| `load_chunking_config(path) -> ChunkingConfig` | `yaml.safe_load` of the file, then pydantic validation. |
| `ChunkingConfig` | Validated form of `config/chunking.yaml`. |
| `Chunk`, `Chunker` | The chunk dataclass and the chunker protocol (see below). |

`__all__` lists exactly these five names.

### `Chunker` protocol

`Chunker` has the attributes `name` and `version` and the method `chunk(document: dict) -> list[Chunk]`. The input is one parsed document, the JSON written by `parse_raw_documents.py`: `document["sections"]` is a list of sections with `id`, `path` (list of headings) and `blocks`; each block has `text`, `type` and optionally `page`.

### `Chunk` (dataclass)

| Field | Type | Description |
|---|---|---|
| `index` | `int` | Position of the chunk in the document. |
| `text` | `str` | The joined text of the chunk's units. |
| `contextual_text` | `str` | `text` preceded by `H1 > H2 > ...` and a blank line when `contextual_header` is true and the units share a heading path; otherwise equal to `text`. |
| `heading_path` | `list[str]` | Longest common prefix of the units' heading paths. |
| `section_ids` | `list[str]` | Distinct section ids, in order. |
| `block_types` | `list[str]` | Distinct block types, in order. |
| `pages` | `list[int]` | Sorted distinct page numbers of units that have one. |
| `n_tokens` | `int` | Token count of `text`. |
| `n_units` | `int` | Number of units in the chunk. |
| `breakpoint_distance` | `float \| None` | Embedding distance to the previous unit; `None` for the first chunk. Default `None`. |
| `extra` | `dict` | Empty by default; no code in the chunking package writes to it. |

### `Unit` (dataclass)

The smallest piece a chunker moves: `text`, `section_id`, `path`, `block` (running block number in the document; equal for sentences of one paragraph), `block_type`, `page` (`int | None`).

### `TokenCounter(tokenizer)`

Counts tokens with the Hugging Face tokenizer of that name (`Tokenizer.from_pretrained`, special tokens excluded). With `None`, or when the tokenizer cannot be loaded (a warning is printed), it counts whitespace-separated words.

### Helpers in `chunking.base`

| Function | Description |
|---|---|
| `split_sentences(text) -> list[str]` | Splits after `.`, `!` or `?` followed by whitespace, an optional quote or bracket, and a capital letter or digit. Periods in decimals and after the abbreviations `e.g`, `i.e`, `et al`, `vs`, `cf`, `Fig`, `Figs`, `Tab`, `Dr`, `Mr`, `Mrs`, `Ms`, `Prof`, `approx`, `no`, `ca` (case-insensitive) do not split. |
| `document_units(document, split=True) -> list[Unit]` | Flattens sections and blocks into units. Blocks with empty text are skipped. Only blocks of type `paragraph` are split into sentences (when `split`); list items and tables stay whole. |
| `split_oversized(unit, max_tokens, count) -> list[Unit]` | Returns the unit unchanged when it fits; otherwise cuts it into windows that are closed before they exceed `max_tokens` tokens; the pieces are words, or lines when the text contains a line break. |
| `join_units(units) -> str` | Joins texts with a blank line between sections, a line break between blocks and a space otherwise. |
| `common_prefix(paths) -> list[str]` | Longest shared prefix of heading paths. |
| `build_chunk(index, units, count, contextual_header, breakpoint_distance) -> Chunk` | Fills a `Chunk` from its units. |

### `SemanticChunker(cfg, embedder, count)`

`name` is `"semantic"` and `version` is `CHUNKER_VERSION`. `chunk(document)` runs these steps and returns `[]` for a document without units:

1. `document_units(document, cfg.sentence_split)`, then `split_oversized` on every unit with `cfg.max_tokens`.
2. For each unit, builds a text from the unit and up to `buffer_size` neighbours on each side (only neighbours of the same section when `respect_sections` is true) and embeds the texts with `embedder.embed`. The distance between unit i and i+1 is `1 - dot(vector_i, vector_i+1)`.
3. A boundary between units of different sections is a hard break when `respect_sections` is true. On the remaining boundaries `breakpoint_mask` marks the topic shifts; each shift ends a chunk.
4. A chunk longer than `max_tokens` (and with at least two units) is cut recursively at its largest internal distance.
5. Chunks shorter than `min_tokens` are merged, smallest first, with the eligible neighbour whose shared boundary has the smaller distance. A merge needs both chunks to share the first `merge_scope_level` heading-path entries (of their first units) and the merged size to stay within `max_tokens`. Merging repeats until no merge is possible.
6. Each chunk is built with `build_chunk`; its `breakpoint_distance` is the distance at its start boundary.

`breakpoint_mask(distances, cfg)` returns a boolean array, true where a distance is a topic shift, and an empty array for empty input:

| `type` | A distance is a shift when |
|---|---|
| `percentile` | it is above the `amount`-th percentile of the distances |
| `std_dev` | it is above `mean + amount * std` |
| `interquartile` | it is above `mean + amount * (q3 - q1)` |
| `gradient` | the gradient of the distances is above the `amount`-th percentile of the gradient |

## Constants

| Name | Value | Meaning |
|---|---|---|
| `CHUNKER_VERSION` | `"1"` | Part of `config_hash()`; changes the hash of a config when the chunker output changes for the same config. |

## `config/chunking.yaml`

Model: `ChunkingConfig` in `scripts/corpus/chunking/config.py`. The file header names `scripts/corpus/chunk_parsed_documents.py` as its consumer, reading `s3://$S3_BUCKET/parsed/` and writing `s3://$S3_BUCKET/chunked/`.

| Key | Type | Default in model | Value in file | Description |
|---|---|---|---|---|
| `method` | `Literal["semantic"]` | required | `semantic` | Chunking method; the block of the same name must be present, otherwise validation fails. |
| `documents.skip_roles` | `list[str]` | `[]` | `[]` | Documents whose `source.metadata.role` is listed are not chunked. |
| `embeddings.model` | `str` | required | `bge-m3` | Ollama model used for the distances. |
| `embeddings.batch_size` | `int` (`> 0`) | `64` | `64` | Texts per embedding request. |
| `embeddings.truncate` | `bool` | `true` | `true` | Passed to Ollama as `truncate`. |
| `tokenizer` | `str \| None` | `None` | `BAAI/bge-m3` | Hugging Face tokenizer that measures chunk size; `null` counts words. |
| `semantic.sentence_split` | `bool` | `true` | `true` | Split paragraphs into sentences. |
| `semantic.buffer_size` | `int` (`>= 0`) | `1` | `1` | Neighbours on each side joined into a unit's embedding text. |
| `semantic.breakpoint.type` | `percentile`, `std_dev`, `interquartile` or `gradient` | `percentile` | `percentile` | Rule of `breakpoint_mask`. |
| `semantic.breakpoint.amount` | `float` | `90` | `90` | Percentile or multiplier of the rule. |
| `semantic.min_tokens` | `int` (`>= 0`) | `80` | `80` | Chunks below this size are merged. Must not exceed `max_tokens`. |
| `semantic.max_tokens` | `int` (`> 0`) | `512` | `512` | Upper size of a chunk and of a unit. |
| `semantic.respect_sections` | `bool` | `true` | `true` | Section boundaries are hard breaks. |
| `semantic.merge_scope_level` | `int` (`>= 0`) | `1` | `1` | Undersized chunks merge only with neighbours that share the first N heading-path entries. |
| `semantic.contextual_header` | `bool` | `true` | `true` | Store the heading path in `contextual_text`. |

`ChunkingConfig.config_hash()` is the first 12 hex characters of the SHA-256 of a JSON document holding `CHUNKER_VERSION`, `method`, the method block, `embeddings` and `tokenizer`. The `documents` filter is not part of it. The `chunking.yaml` header states that the hash is stored on every output object and that changing a key used by the active method re-chunks all documents.

## `config/indexing.yaml`

Model: `IndexingConfig` in `backend/app/indexing/config.py`, loaded by `load_indexing_config`. The file header names `scripts/corpus/index_chunks.py` as its consumer, reading `s3://$S3_BUCKET/chunked/` and writing the Postgres table `chunks`.

| Key | Type | Default in model | Value in file | Description |
|---|---|---|---|---|
| `embeddings.model` | `str` | required | `bge-m3` | Ollama embedding model. |
| `embeddings.batch_size` | `int` (`> 0`) | `64` | `32` | Texts per embedding request. |
| `embeddings.truncate` | `bool` | `true` | `true` | Passed to Ollama as `truncate`. |
| `embeddings.dimensions` | `int` (`> 0`) | required | `1024` | Expected vector width. When the model returns another width, `index_chunks.py` records that file as `FAILED` and continues with the next file. When `chunks.embedding` has a different `vector(N)` type, it exits before it indexes any file. |
| `text_field` | `contextual_text` or `text` | `contextual_text` | `contextual_text` | Chunk field that is embedded and that BM25 is fitted on. |
| `sparse.k1` | `float` (`> 0`) | `1.2` | `1.2` | BM25 saturation. |
| `sparse.b` | `float` (`0..1`) | `0.75` | `0.75` | BM25 length normalisation. |
| `sparse.stemmer` | `str \| None` | `english` | `english` | Snowball language, or `null` for none. |

`sparse` is a `Bm25Config` from the core package. `build_embedder(cfg)` builds `OllamaEmbedder(**cfg.embeddings.model_dump(exclude={"dimensions"}))`.

`OllamaEmbedder(model, batch_size=64, truncate=True, base_url=None)` posts batches of texts to the Ollama endpoint `/api/embed` and raises `RuntimeError` when Ollama answers 404 (model not pulled). `base_url` defaults to `settings.ollama_base_url`.

## `config/sources.yaml`

Model: `Manifest` in `scripts/corpus/sources.py`, loaded by `load_manifest`. The file header names `scripts/corpus/fetch_sources.py` (download to `data/raw/<id>/`) and `scripts/corpus/upload_raw_documents.py` as consumers. The header states: `attempts` are tried in order and the first response that passes its `expect` check is saved unmodified; at most one request per second per host, with a User-Agent carrying `CONTACT_EMAIL`; secrets come from the environment only.

### Top level

| Key | Type | Default | Description |
|---|---|---|---|
| `sources` | `list[Source]` | required | Sources to fetch. Ids must be unique. |
| `excluded` | `list[Excluded]` | `[]` | Sources kept out of every stage. An id must not appear in both lists. |

### `sources[]`

| Key | Type | Default | Description |
|---|---|---|---|
| `id` | `str` | required | Source id; folder name under `data/raw/`. |
| `title` | `str` | required | Title. |
| `doi`, `pmid`, `pmcid`, `release_or_version` | `str \| None` | `None` | Identifiers and version. |
| `metadata.role` | `str` | required | Role copied to `meta.json`: `level0_structured` (ICD-11 MMS) or `literature_claims` in the file. |
| `metadata.licence`, `citation`, `evidence_level`, `population` | `str \| None` | `None` | Descriptive fields. |
| `attempts` | `list` | `None` | Ordered download attempts (below). |
| `manual` | object | `None` | Files placed by hand, given as `manual.paths` (`list[str]`, required inside `manual`); the first existing path is copied into `data/raw/<id>/`. |
| `auth` | object | `None` | API behind credentials (below). |
| `required_headers` | `dict[str, str]` | `None` | Request headers of an API source. |
| `endpoints` | `dict[str, str]` | `None` | Named API URLs of an API source. |

Exactly one of `attempts`, `manual` and `auth` is required per source. The file has seven sources: `icd11_mms_6a05` (`auth`), `wfadhd_consensus_2021`, `euro_consensus_adult_adhd_2019`, `nice_ng87`, `discourse_review_lifespan` and `carruthers_2021_pragmatics` (`attempts`), and `aadpa_guideline_2022` (`manual`).

### `attempts[]`

| Key | Type | Default | Description |
|---|---|---|---|
| `kind` | `http` or `europepmc_resolve` | required | Attempt type. |
| `expect` | `pdf`, `xml`, `html` or `json` | required for `http` | Expected response type. |
| `name` | `str` | `source` | Saved file name (`http` with `url`). |
| `url` / `urls` | `str` / `dict[str, str]` | `None` | Exactly one is required for `http`; with `urls`, every target must download. |
| `query` | `str` | required for `europepmc_resolve` | Europe PMC search; if the hit has a PMCID its full-text XML is fetched. |

### `auth`

| Key | Type | Description |
|---|---|---|
| `type` | `oauth2_client_credentials` | Only value the model accepts. |
| `token_url`, `scope` | `str` | OAuth endpoint and scope. |
| `env` | `list[str]` | Environment variables with the credentials: `ICD_CLIENT_ID`, `ICD_CLIENT_SECRET` in the file. |
| `token_ttl_minutes` | `int` | Token lifetime; `55` in the file. |

### `excluded[]`

| Key | Type | Default | Description |
|---|---|---|---|
| `id` | `str \| None` | `None` | Source id; when set, `excluded_source_ids()` returns it so stages skip that source. |
| `name` | `str` | required | Name. |
| `reason` | `str` | required | Why the source is excluded. |

The file excludes five entries: the ICD-11 Foundation entity 6A05 (`id` `icd11_foundation_6a05_diagnostic_requirements`), the ICD-11 CDDR PDF (`id` `icd11_cddr_pdf`), DSM-5-TR, the CADDRA guidelines 4.1 and NCBI Bookshelf NBK53659.

## Sources in code

- `scripts/corpus/chunking/__init__.py` - build_chunker, exports
- `scripts/corpus/chunking/base.py` - Unit, Chunk, Chunker, TokenCounter, sentence and unit helpers
- `scripts/corpus/chunking/config.py` - ChunkingConfig, SemanticConfig, BreakpointConfig, CHUNKER_VERSION, config_hash
- `scripts/corpus/chunking/semantic.py` - SemanticChunker, breakpoint_mask
- `config/chunking.yaml` - active method and hyperparameters
- `config/indexing.yaml` - embedding and BM25 settings
- `config/sources.yaml` - source manifest values
- `scripts/corpus/sources.py` - manifest models, defaults and validators
- `backend/app/indexing/config.py` - IndexingConfig, EmbeddingConfig and their defaults
- `backend/app/indexing/__init__.py` - build_embedder
- `backend/app/embeddings.py` - OllamaEmbedder request behaviour
- `scripts/corpus/index_chunks.py:54-66,193-198` - dimension checks against the table and the model output
- `packages/expert-knowledge-core/src/expert_knowledge_core/bm25.py:21-26` - Bm25Config defaults
