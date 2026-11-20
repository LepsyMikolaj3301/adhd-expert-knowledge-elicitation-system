---
title: Runtime and deployment
diataxis: reference
---

# Runtime and deployment

Language: **English** · [Polski](../../pl/reference/runtime-and-deploy.md)

This page maps the files that run the stack: the local compose file and the Azure VM compose file, the Dockerfiles, the backend package metadata, the database setup and migrations, the prompt loader and prompt files, and the scripts outside `scripts/corpus/chunking`.

## Local stack: `docker-compose.yml`

### Services

| Service | Profile | Image or build | Host ports | Role |
|---|---|---|---|---|
| `ollama` | none | `ollama/ollama:latest` | `127.0.0.1:11434` | LLM server; models volume is `${OLLAMA_DATA_PATH:-ollama-data}`; GPU reservation (`driver: nvidia`, `count: all`) is active in the file |
| `languagetool` | none | `erikvl87/languagetool:6.8` | `127.0.0.1:8010` | Grammar checker; `Java_Xms` 512m, `Java_Xmx` 1g |
| `postgres` | none | `pgvector/pgvector:pg16` | `5432` | Database; mounts `backend/db/init.sql` into `docker-entrypoint-initdb.d`; healthcheck `pg_isready` |
| `minio` | none | `cgr.dev/chainguard/minio` pinned by digest | `${MINIO_API_HOST_PORT:-9000}`, `${MINIO_CONSOLE_HOST_PORT:-9001}` | S3-compatible storage; healthcheck `mc ready local` |
| `minio-init` | none | `cgr.dev/chainguard/minio-client:latest-dev` pinned by digest | none | One-shot: runs `backend/db/minio/init-bucket.sh`; `restart: "no"` |
| `dev` | none | build `.devcontainer/Dockerfile` | none | Dev workspace, `command: sleep infinity`, repo mounted at `/workspace`, GPU reservation, `PYTHONPATH=/workspace/backend` |
| `pgadmin` | `tools` | `dpage/pgadmin4:latest` | `${PGADMIN_HOST_PORT:-5050}` -> 80 | Postgres web UI; server mode off, master password off |
| `migrate` | `app` | build `backend/Dockerfile` | none | One-shot `alembic upgrade head`; waits for healthy `postgres` |
| `rag-backend` | `app` | build `backend/Dockerfile` | `8000` | API; waits for `postgres` healthy, `migrate` and `minio-init` completed, `ollama` started |
| `worker` | `app` | build `backend/Dockerfile` | none | `python -m app.jobs.worker`; mounts `./prompts` at `/workspace/prompts` and `./config` at `/workspace/config`, both read-only; waits for `postgres`, `migrate`, `ollama`, `languagetool` |
| `frontend` | `app` | build `./frontend`, target `dev` | `5173` | Vite dev server; `VITE_API_PROXY_TARGET=http://rag-backend:8000`; `node_modules` in a named volume |
| `playwright` | `browser` | `mcr.microsoft.com/playwright/mcp:latest` | none (`expose: 8931`) | Headless browser for Playwright MCP; command `--host 0.0.0.0 --port 8931 --allowed-hosts *` |
| `frontend-preview` | `preview` | build `./frontend` with `infra/frontend.Dockerfile` | `8080` | Production nginx image; `PORT=8080`, `API_UPSTREAM_URL=http://rag-backend:8000`, `API_HOST=rag-backend` |

Named volumes: `frontend-node-modules`, `ollama-data`, `postgres-data`, `pgadmin-data`, `minio-data`, `uv-cache`, `hf-cache`, `claude-config`.

### Start commands

| Command | Starts |
|---|---|
| `docker compose up -d` | `ollama`, `languagetool`, `postgres`, `minio`, `minio-init`, `dev` |
| `docker compose --profile app up` | adds `migrate`, `rag-backend`, `worker`, `frontend` |
| `docker compose --profile tools up -d pgadmin` | adds `pgadmin` |
| `docker compose --profile app --profile browser up -d` | adds `playwright` |
| `docker compose --profile preview up -d --build frontend-preview` | `frontend-preview` (it looks the backend up per request; nothing orders the start) |

For a walk-through, see [Run the stack locally](../tutorials/run-the-stack-locally.md).

## Azure VM stack: `infra/azure/docker-compose.yml`

The stack runs without Ollama and LanguageTool: the backend reaches them on the machine at `PC_HOST` (`http://${PC_HOST}:11434` and `http://${PC_HOST}:8010`). The memory limits add up to about 2 GB, sized for a 4 GB VM.

| Service | Profile | Image | Ports | Limits | Health check |
|---|---|---|---|---|---|
| `caddy` | none | `caddy:2-alpine` | `80`, `443` | 64m, 0.5 CPU | none; waits for healthy `frontend` |
| `frontend` | none | `${REGISTRY}/frontend:${IMAGE_TAG:-latest}` | none published | 64m, 0.5 CPU | `wget` on `http://127.0.0.1:8080/healthz` every 15 s |
| `rag-backend` | none | `${REGISTRY}/backend:${IMAGE_TAG:-latest}` | none published | 512m, 1.0 CPU | Python `urlopen` on `http://127.0.0.1:8000/api/v1/health` every 15 s |
| `worker` | none | same backend image; command `python -m app.jobs.worker` | none | 512m, 1.0 CPU | passes while `/tmp/worker-alive` was modified within 60 s |
| `migrate` | none | same backend image; command `alembic upgrade head` | none | 384m | none; `restart: "no"` |
| `postgres` | none | `pgvector/pgvector:pg16` | none published | 768m, 1.0 CPU | `pg_isready -U rag -d rag` every 5 s |
| `cli` | `tools` | same backend image; entrypoint `python -m app.cli` | none | 384m | none; mounts `./import` at `/import` read-only |

- `rag-backend` and `worker` wait for `postgres` healthy and `migrate` completed; `migrate` waits for `postgres` healthy.
- Postgres starts with `shared_buffers=128MB`, `max_connections=30`, `work_mem=8MB`.
- The shared `logging` anchor (json-file, `max-size` 10m, `max-file` 3) applies to all seven services: `caddy`, `frontend` and `postgres` set it directly, `rag-backend`, `worker`, `migrate` and `cli` inherit it from `x-backend`.
- Volumes: `postgres-data`, `caddy-data` (the TLS certificate), `caddy-config`.
- The one-shot commands of `cli` are `create-admin` and `import-vignettes`; the compose file comments show `docker compose --profile tools run --rm cli create-admin --email ... --name ...` and `... cli import-vignettes --dir /import/vignettes --whatifs /import/chip_whatifs.json --admin-email ...`. The commands themselves are listed in [Backend core API](backend-core-api.md).

Environment of the backend-image services (`x-backend`):

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql://rag:${POSTGRES_PASSWORD}@postgres:5432/rag` |
| `ENVIRONMENT` | `${ENVIRONMENT:-production}` |
| `COOKIE_SECURE` | `${COOKIE_SECURE:-true}` |
| `SESSION_TTL_HOURS` | `${SESSION_TTL_HOURS:-12}` |
| `OLLAMA_BASE_URL` | `http://${PC_HOST}:11434` |
| `LANGUAGETOOL_URL` | `http://${PC_HOST}:8010` |
| `CLASSIFIER_MODEL`, `ENHANCE_MODEL` | `${...:-qwen3.5:9b}` |
| `REQUIRE_COMPUTE` | `"true"` (fixed in the file) |

`frontend` receives `PORT=8080`, `API_UPSTREAM_URL=http://rag-backend:8000` and `API_HOST=rag-backend`.

### `infra/azure/Caddyfile`

Site address `{$DOMAIN}`; directives `encode gzip` and `reverse_proxy frontend:8080`. Caddy requests the TLS certificate itself; the comment states that ports 80 and 443 must be open to the internet.

### `infra/azure/env.example`

| Key | Value in the template |
|---|---|
| `DOMAIN` | empty; the public name of the VM |
| `REGISTRY` | `ghcr.io/owner/repo` |
| `IMAGE_TAG` | `latest` |
| `PC_HOST` | empty; Tailscale IP of the PC that runs Ollama and LanguageTool |
| `POSTGRES_PASSWORD` | empty |
| `CLASSIFIER_MODEL`, `ENHANCE_MODEL` | `qwen3.5:9b` |
| `ENVIRONMENT`, `COOKIE_SECURE`, `SESSION_TTL_HOURS` | `production`, `true`, `12` |

### VM scripts

| Script | Runs on | What it does |
|---|---|---|
| `infra/azure/vm.sh start\|stop\|status` | developer PC (needs `az`, logged in) | `az vm start`, `az vm deallocate` or only the power-state query for VM `rag-vm` in resource group `rag-rg`, subscription named `Azure for Students`; prints `rag-vm: <state>` |
| `infra/azure/setup-vm.sh` | the VM, as root | Adds a 2 GB `/swapfile` and `vm.swappiness=10`; installs Docker and Tailscale if missing; installs `unattended-upgrades` and `anacron`; creates `/opt/rag` and `/opt/rag/import`; copies `docker-compose.yml`, `Caddyfile`, `env.example`, `deploy.sh`, `backup.sh` there; links `/opt/rag/backup.sh` to `/etc/cron.daily/rag-backup` |
| `infra/azure/deploy.sh [IMAGE_TAG]` | the VM, in `/opt/rag` | Requires `.env`; with a tag matching `^[A-Za-z0-9._-]+$` writes `IMAGE_TAG` to `.env`; runs `docker compose pull --quiet`, then `docker compose up -d --remove-orphans`; waits up to 180 s each for `rag-backend`, `worker` and `frontend` to be healthy (prints the last 40 log lines on failure); runs `docker image prune -f`; prints `docker compose ps` |
| `infra/azure/backup.sh` | the VM, as root (daily) | Runs `docker compose exec -T postgres pg_dump -U rag -Fc rag` in `${RAG_DIR:-/opt/rag}` to `/var/backups/rag/rag-<date>.dump` (directory mode 700); logs to the journal tag `rag-backup`; deletes `rag-*.dump` older than 7 days |
| `infra/ts-serve.sh up [service...]\|fix\|status` | developer PC (WSL) | Resets `tailscale serve`, runs `docker compose up -d` (recreates `ollama` and `languagetool` when they do not answer on `127.0.0.1`), waits until `:11434/api/version` and `:8010/v2/languages` answer, then serves TCP ports 11434 and 8010 with `tailscale serve --bg --tcp`; `fix` recreates the two services and serves again; `status` prints `tailscale serve status` and the HTTP code of each local port |

For the step sequence, see [How to deploy to the Azure VM](../how-to/deploy-to-azure-vm.md).

## Images

| File | Base | Build context | Notes |
|---|---|---|---|
| `backend/Dockerfile` | `python:3.12-slim` | repo root | Dev image: apt packages `git`, `ca-certificates`, `tesseract-ocr` (`eng`, `pol`), `libgl1`, `libglib2.0-0`; `uv sync --frozen --package rag-backend --no-default-groups` into `/opt/venv`; user `vscode` (uid 1000); copies `backend`, `prompts`, `config`; `EXPOSE 8000`; `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` |
| `infra/backend.Dockerfile` | `python:${PYTHON_VERSION}-slim` (3.12) | repo root | Production API image, two stages; `uv sync ... --no-editable`; system user `app`; `ENVIRONMENT=production`, `PORT=8000`; `CMD` runs uvicorn on `${PORT}` with `--proxy-headers --forwarded-allow-ips='*'`, no reload; migrations are not run in the image |
| `frontend/Dockerfile` | `node:${NODE_VERSION}-slim` (24) | `frontend/` | Dev image, stage `dev`; user `node`; `EXPOSE 5173`; `CMD npm install && exec npm run dev` |
| `infra/frontend.Dockerfile` | build `node:${NODE_VERSION}-slim` (24), run `nginx:1.28-alpine` | `frontend/` | `npm ci`, `npm run build`; copies `nginx/default.conf.template` and `dist`; defaults `PORT=8080`, `API_UPSTREAM_URL=http://rag-backend:8000`, `API_HOST=rag-backend`, `NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1` |

`docker build -f infra/backend.Dockerfile -t rag-backend .` builds the production API image; `docker build -f infra/frontend.Dockerfile -t rag-frontend frontend/` builds the production web image. Both commands are written in the Dockerfile headers.

## Python packaging

| File | Content |
|---|---|
| `backend/pyproject.toml` | Package `rag-backend` 0.1.0, `requires-python >=3.12`, `[tool.uv] package = false`; dependencies `fastapi>=0.115`, `uvicorn[standard]>=0.32`, `asyncpg>=0.30`, `pgvector>=0.3`, `pydantic-settings>=2.6`, `httpx>=0.27`, `numpy>=2.0`, `sqlalchemy[asyncio]>=2.0`, `alembic>=1.14`, `argon2-cffi>=23.1`, `email-validator>=2.2`, `pyyaml>=6.0`, `wordfreq>=3.1`, `expert-knowledge-core`, `expert-knowledge-rag` (both `workspace = true`) |
| `pyproject.toml` | Virtual workspace `rag-workspace` 0.0.0; members `backend` and `packages/*`; `default-groups = ["dev", "notebooks", "scripts"]`; groups `dev` (pytest, pre-commit, ruff, ty, pytest-asyncio, pytest-cov), `notebooks` (ipykernel, ipywidgets, jupyterlab), `scripts` (beautifulsoup4, boto3, docling, tokenizers, lxml, prompt-toolkit, pyyaml, langchain-ollama), `experiments` (empty); ruff `line-length = 100`, rules `E, F, I, UP, B, ASYNC, SIM`; pytest `testpaths`, `pythonpath`, `asyncio_mode = "auto"` and the markers `integration`, `regression`, `scale` |

See [How to run tests and checks](../how-to/run-tests-and-checks.md) for the test commands.

## Database setup

### `backend/db/init.sql`

Idempotent DDL, applied by Postgres on the first start of a data volume and by `scripts/db/init_db.py` on an existing database.

| Object | Definition |
|---|---|
| extension | `vector` |
| `public.documents` | `id` uuid, `origin` (`manifest` or `user_upload`), `source_id`, `title`, `s3_bucket`, `s3_key`, `filename`, `content_type`, `size_bytes`, `sha256`, `source_url`, `retrieved_at`, `release_or_version`, `metadata` jsonb, `status` (`uploaded`, `parsing`, `parsed`, `indexed`, `failed`), `status_detail`, `uploaded_by`, timestamps; `UNIQUE (s3_bucket, s3_key)`; indexes on `sha256` and `source_id` |
| `public.chunks` | `id` text, `document_id` (cascade delete), `chunk_index`, `text`, `contextual_text`, `heading_path`, `section_ids`, `block_types`, `pages`, `n_tokens`, `metadata`, `embedding vector(1024)`, `embedding_model`, `chunked_key`, `chunked_sha256`, `index_config`, `created_at`; `UNIQUE (document_id, chunk_index)`; HNSW index `vector_cosine_ops` on `embedding` |
| `chunks.sparse` | `sparsevec(1048576)`, BM25 term weights; no index (exact scan) |

### `backend/db/minio/init-bucket.sh`

Requires `MINIO_URL`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`. Creates the bucket with `mc mb --ignore-existing`, adds the app user and attaches the `readwrite` policy.

### Alembic

| File | Content |
|---|---|
| `backend/alembic.ini` | `script_location = %(here)s/migrations`; `file_template = %%(rev)s_%%(slug)s`; logging to stderr |
| `backend/migrations/env.py` | Creates schema `app` if missing; autogenerate covers schema `app` only (`include_name`); version table stored in schema `app`; URL from the `sqlalchemy.url` option or `settings.database_url`, converted by `to_async_url` |

Schema `chips` and the tables in `public` are not autogenerated; schema `chips` is created by migration 0003 with plain SQL.

### Migrations

The revisions form one chain from `0001` (`down_revision = None`) to `0009`.

| Revision | File | Change |
|---|---|---|
| 0001 | `0001_initial.py` | Schema `app`: sequence `user_pseudonym_seq` and tables `users`, `audit_events`, `auth_sessions`, `invites`, `vignettes`, `vignette_versions`, `assignments`, `answer_drafts`, `jobs`, `review_requests`, `submissions`, `knowledge_units`, `unit_decisions` |
| 0002 | `0002_citations.py` | Adds `assignments.locked_highlights`; removes the `quoted_fragments` key from `answer_drafts.payload` |
| 0003 | `0003_pipeline.py` | Adds `answer_findings`, the unit columns of `knowledge_units`, nullable `review_requests.requested_by`; creates extension `vector` and schema `chips` with `experts`, `vignettes`, `elicitation_sessions`, `cue_keys`, `highlights`, `answer_sentences`, `finding_units`, `finding_unit_sentences`, `unit_cues`, `review_events` |
| 0004 | `0004_review_rounds.py` | Adds `review_round` to `assignments` and `knowledge_units`; unit status `superseded`; decision value `request_changes`; drops `knowledge_units.question_id` |
| 0005 | `0005_open_review.py` | Open review: state `admin_review` dropped, `review_requests` replaced by `review_participants`, `assignments.required_approvals` dropped; adds `unit_comments`, `submission_votes`, `users.activity_seen_at` and an audit index by action |
| 0006 | `0006_proofread.py` | Proofread flow: drops `assignments.gate_passed_at` and `locked_highlights`; adds `proofread_rounds`, `answer_revisions`, `answer_comments`, `answer_votes`, `answer_decisions`; reorders the assignment states (`processing` after `peer_review`); `expert_check` and `building_units` are not states |
| 0007 | `0007_patient_summary.py` | Adds `vignette_versions.patient_summary` (text, default empty) |
| 0008 | `0008_unit_removal.py` | Allows unit status `removed` and job kind `refit`; makes `jobs.assignment_id` nullable |
| 0009 | `0009_drop_synthetic.py` | Drops `users.is_synthetic` with its check constraint and `is_synthetic` from `chips.experts`, `chips.elicitation_sessions`, `chips.finding_units` |

`alembic upgrade head` is the `command` of the `migrate` service in both compose files.

## Configuration keys

### Backend `Settings` (`backend/app/settings.py`)

| Key | Type | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | str | `postgresql://rag:rag@localhost:5432/rag` | Postgres DSN |
| `OLLAMA_BASE_URL` | str | `http://localhost:11434` | Ollama endpoint |
| `REQUIRE_COMPUTE` | bool | `false` | When true, a request that would queue a job first asks the compute machine and answers 503 `compute_unavailable` if it is not ready |
| `CLASSIFIER_MODEL` | str | `qwen3.5:9b` | Model that files sentences without a citation (prompt `Expert_sentence_targets.v1`) |
| `ENHANCE_MODEL` | str | `qwen3.5:9b` | Model that turns fragments into sentences (prompt `Answer_enhance.v2`); empty switches enhancement off |
| `OLLAMA_REQUEST_TIMEOUT` | float | `600` | Seconds one Ollama reply may take |
| `LANGUAGETOOL_URL` | str | `http://localhost:8010` | Grammar checker |
| `LANGUAGETOOL_LANGUAGE` | str | `en-US` | LanguageTool language |
| `LANGUAGETOOL_TIMEOUT` | float | `60` | Seconds |
| `PROJECT_ROOT` (field `project_root`) | Path | two levels above `backend/app` (the repo root; `/workspace` in the images) | Folder holding `prompts/` and `config/` |
| `ENVIRONMENT` | `development` or `production` | `development` | Any other value stops the app at startup; `production` forces the HTTPS-only cookie |
| `COOKIE_SECURE` | bool | `false` | HTTPS-only session cookie |
| `SESSION_TTL_HOURS` | int | `12` | Session lifetime |

### Compose and `.env.example` keys

| Key | Default | Used by |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `rag`, `rag`, `rag` | `postgres` and the `DATABASE_URL` built for `dev`, `migrate`, `rag-backend`, `worker` |
| `OLLAMA_DATA_PATH` | unset (named volume `ollama-data`) | `ollama` models mount |
| `OLLAMA_LOAD_TIMEOUT`, `OLLAMA_KEEP_ALIVE` | `5m`, `5m` | `ollama` environment |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | `minioadmin`, `minioadmin` | `minio`, `minio-init` |
| `MINIO_API_HOST_PORT`, `MINIO_CONSOLE_HOST_PORT` | `9000`, `9001` | `minio` ports |
| `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | `documents`, `rag-app`, `rag-app-secret` | `minio-init`, `dev`, `rag-backend` |
| `S3_REGION` | `us-east-1` | `dev`, `rag-backend` |
| `S3_ENDPOINT_URL` | `http://minio:9000` in compose; `http://localhost:9000` in `.env.example` | `dev`, `rag-backend` |
| `PGADMIN_HOST_PORT`, `PGADMIN_EMAIL`, `PGADMIN_PASSWORD` | `5050`, `admin@local.dev`, dev value in the file | `pgadmin` |
| `VITE_API_PROXY_TARGET` | `http://rag-backend:8000` in compose | `dev`, `frontend` |
| `CONTACT_EMAIL`, `ICD_CLIENT_ID`, `ICD_CLIENT_SECRET` | empty | `scripts/corpus/fetch_sources.py` |

The `dev` and `app`-profile backend services read `.env` through `env_file`; `DATABASE_URL`, `OLLAMA_BASE_URL`, `LANGUAGETOOL_URL` and the S3 endpoint are overridden in the compose file with in-network host names.

### Corpus storage settings (`scripts/corpus/storage.py`)

`S3Settings` reads `S3_ENDPOINT_URL` (default `http://localhost:9000`; empty targets AWS S3), `S3_ACCESS_KEY_ID` (`rag-app`), `S3_SECRET_ACCESS_KEY` (`rag-app-secret`), `S3_REGION` (`us-east-1`) and `S3_BUCKET` (`documents`).

## Prompt loader: `backend/app/prompts.py`

`scripts/elicitation/prompt_loader.py` re-exports `PROMPTS_DIR`, `Prompt`, `PromptError` and `load_prompt` from it.

### `load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt`

Reads `<prompts_dir>/<name>.md`; `name` is the file stem, for example `Synthetic_expert_answer.v1`. The file starts with `---\n` front-matter (`key: value` per line, split at the first colon; values starting with `{` or `[` are parsed as YAML and kept as strings when that fails), then either `# System` and `# User` sections or a `# Template` section. `id` and `version` are read from the front-matter. Raises `PromptError` when the front-matter is missing, a front-matter line has no colon, or neither a `# User` nor a `# Template` section exists; a missing `id` or `version` key raises `KeyError`.

### `Prompt`

Frozen dataclass: `id: str`, `version: int`, `meta: dict`, `system: str | None`, `user: str` (the whole raw prompt for a `# Template` file).

### `Prompt.fill(**variables) -> Prompt`

Drops a `(e.g. ...)` hint after a placeholder, keeps text between `{{IF_VARIANT}}` and `{{END_IF}}` only when `IF_VARIANT` is truthy, substitutes `{{VAR}}` (names `[A-Z0-9_]+`) and strips the result. Raises `PromptError` for a missing variable and for a variable the template does not use.

### Constants

| Name | Value |
|---|---|
| `PROMPTS_DIR` | `settings.project_root / "prompts"` |
| `PromptError` | subclass of `ValueError` |

### Prompt files

The backend loads two prompts: `Expert_sentence_targets.v1` (`backend/app/knowledge/classifier.py`, constant `PROMPT`) and `Answer_enhance.v2` (`backend/app/proofread/enhance.py`, constant `PROMPT`). The other files serve the scripts.

| Family | Files (id, version) | Target in the front-matter |
|---|---|---|
| Persona texts | `Persona_base_fewshot.v1.md` (`persona_base_fewshot`), `Persona_claude.v1.md`, `Persona_claude.v2.md` (`persona_claude`) | base model with raw completion; Claude |
| Synthetic expert answers | `Synthetic_expert_answer.v1.md` to `v5.md` (`synthetic_expert_answer`, versions 1-5) | v1-v3 Claude; v4 Claude (silver) or a local model (bronze); v5 local instruct models, one per expert |
| Expert personas | `expert_personas/E21.v1.md` to `E32.v1.md` (12 files, `expert_persona`, version 1) | model named inside each file |
| Expert unit retrieval | `Expert_unit_keys.v1.md`, `Expert_unit_queries.v1.md`, `Expert_unit_pooling.v1.md` (`expert_unit_keys`, `expert_unit_queries`, `expert_unit_pooling`) | local model; Claude; Claude |
| Sentence classification | `Expert_sentence_targets.v1.md` (`expert_sentence_targets`) | local instruct model, JSON mode |
| Answer enhancement | `Answer_enhance.v1.md`, `Answer_enhance.v2.md` (`answer_enhance`), `Enhance_fidelity_judge.v1.md` (`enhance_fidelity_judge`) | local instruct model; local instruct model; Claude |
| Corpus and reference text | `Reddit_post_screen.v1.md` (`reddit_post_screen`), `Gold_reference_claims.v1.md` (`gold_reference_claims`) | local instruct model; Claude |

## Scripts

Run from the repository root (`scripts/README.md`). Scripts inside one folder import each other by module name.

### `scripts/corpus/` (apart from `chunking/`)

| File | Purpose |
|---|---|
| `fetch_sources.py` | Downloads the sources of `config/sources.yaml` into `data/raw/<id>/` with a `meta.json` per source |
| `upload_raw_documents.py` | Uploads the files under `data/raw/` to the S3 bucket (objects whose remote sha256 matches are skipped unless `--force`) and upserts a `documents` row for each file described by a `meta.json` |
| `parse_raw_documents.py` | Reads the `raw/<source_id>/` objects of the S3 bucket and writes `parsed/<source_id>/<stem>.json` and `<stem>.md` for each file described by a `meta.json`; HTML, JATS XML and PDF go through Docling, ICD-API JSON is parsed without it |
| `chunk_parsed_documents.py` | Chunks parsed documents into `chunked/` JSON and Markdown using `config/chunking.yaml` |
| `index_chunks.py` | Embeds chunks with the model of the indexing config into `chunks` and refits the BM25 sparse vectors |
| `purge_sources.py` | Removes sources from Postgres and S3 (`raw/`, `parsed/`, `chunked/`); `--dry-run` |
| `sources.py` | Typed model of `config/sources.yaml` |
| `storage.py` | `S3Settings` and a cached `get_s3_client()` |

The pipeline order is fetch, upload, parse, chunk, index (`scripts/README.md`).

### `scripts/db/`

| File | Purpose |
|---|---|
| `init_db.py` | Applies `backend/db/init.sql` to `settings.database_url` |
| `psql.sh` | `psql` in the `postgres` container (or through `DATABASE_URL` when `docker` is absent); `overview` prints extensions, table sizes, indexes, documents by status, chunk counts per embedding model and sample chunks; other arguments go to `psql` |
| `chips_backup.py` | Backs up, checks, restores and empties the tables of schema `chips` through binary COPY |
| `chips_schema.sql` | Tables of the chips test with a `{schema}` placeholder |
| `chips_snapshot.py` | `freeze` and `check` of a silver chip snapshot in `tests/fixtures/retrieval_silver/` |
| `explore_chips.sql` | Read-only SELECT tour of schema `chips` and the `app` tables that feed it |
| `load_chips_pg.py` | Loads built chip units into a schema (default `chips_eval`) |
| `seed_silver_reviews.py` | Development data: silver answers submitted by two experts and peer-reviewed by two more |

### `scripts/rag/`

| File | Purpose |
|---|---|
| `ask.py` | Answers one question with retrieval over `chunks` |
| `eval_retrieval.py` | Scores retrieval against the bronze QA dataset |
| `eval_generation.py` | Generates answers with several Ollama models and scores them |
| `judge_generations.py` | LLM-as-judge scoring of a generation run |
| `report_eval.py` | Summarises a run as Markdown |
| `compare_runs.py` | Compares evaluation runs as one Markdown file |
| `rag_common.py` | Helpers shared by `ask.py`, the `eval_*.py` scripts, `judge_generations.py` and `report_eval.py` (the module docstring) |
| `eval_expert_units.py` | Compares ways to index expert answers, in memory |
| `expert_retrieval.py` | Building blocks shared by `eval_expert_units.py` and `eval_expert_generation.py` |
| `expert_metrics.py` | Retrieval metrics, numpy only |
| `eval_expert_generation.py` | Answers questions from expert notes with a local 9B model |
| `chat_expert.py` | Chat with the expert-notes generator and human rating of answers |
| `try_expert_rag.py` | Runs the `expert-knowledge-rag` package end to end: retrieve from Postgres, generate, save for grading |
| `chip_retrieval.py` | Retrieval over chip units |
| `eval_chip_units.py` | Chip units against the B1 baseline, retrieval only, in memory |
| `eval_chip_generation.py` | Answers from chip notes and from B1 notes with a local model |
| `eval_scale_retrieval.py` | Retrieval as the experts per vignette grow, on schema `chips_scale` |
| `eval_style_diversity.py` | How differently the scale-fixture experts write, before and after proofreading |

### `scripts/elicitation/`

| File | Purpose |
|---|---|
| `make_fixtures.py` | Builds synthetic ElicitationDocuments and reference claims |
| `fetch_reddit_pool.py` | Downloads an r/ADHD post dump as the pool for `make_fixtures.py --source reddit` |
| `reddit_posts.py` | Example-only helper: r/ADHD posts as vignette texts |
| `screen_reddit_posts.py` | Labels cleaned posts with a local model and shortlists them |
| `llm_clients.py` | Text-generation sources behind one interface: `OllamaGenerator`, `FileGenerator`, `InboxGenerator`, `CachedGenerator` |
| `prompt_loader.py` | Re-exports the loader of `backend/app/prompts.py` |
| `leak_terms.py` | Words a vignette must not contain (`LEAK_TERMS`) |
| `export_schema.py` | Writes the ElicitationDocument JSON Schema to `data/schemas/elicitation_document.schema.json` |
| `elicitation_schema.py` | Session schema handed over by the web platform (`ElicitationDocument`, `ReferenceClaim`) |
| `elicitation_lifecycle.py` | Record status rules (`DocumentStatus`) |
| `elicitation_units.py` | Turns expert answers into retrievable units, no model calls |
| `answer_vignettes.py` | A clinician answers the vignettes in the terminal (gold tier) |
| `chip_answers.py` | Rules behind `notebooks/answer_vignettes.ipynb`: citations, chips, lock-in, document |
| `make_gold_claims.py` | Reference claims for gold answers, written by a Claude agent through the inbox |
| `make_unit_keys.py` | Retrieval keys for expert units with a local model |
| `migrate_q4_whatif.py` | One-off, idempotent: Q4 fixtures from schema 1.0 to 1.1 |
| `chips_schema.py` | Chip documents: highlights, direction toggles, `⟦hN⟧` chips |
| `make_chip_fixtures.py` | Chip fixtures: shared vignettes, then expert answers |
| `classify_sentence_targets.py` | Step 3 of the chips pipeline: a local model files sentences without a chip |
| `chip_findings.py` | Chip answers to fragment units, no models; re-exports `backend/app/knowledge/findings.py` |
| `build_chip_units.py` | Chip documents and classifier labels to units, cue keys and embeddings |
| `make_scale_fixtures.py` | Local scale fixture: 32 experts, 24 vignettes; stages `seed`, `vignettes`, `answers`, `proofread`, `build` |
| `export_scale_answers.py` | Writes all scale-fixture answers to one JSON file (`data/exports/scale_answers.json` by default) |
| `eval_enhance.py` | Compares `Answer_enhance` v1 and v2 under two sets of reply checks |

## Sources in code

- `docker-compose.yml` - local services, profiles, ports, environment, volumes
- `backend/Dockerfile` - dev API image
- `backend/pyproject.toml` - backend package and dependencies
- `backend/alembic.ini` - alembic settings
- `backend/migrations/env.py` - alembic environment, schema scope
- `backend/migrations/versions/0001_initial.py` - app schema tables
- `backend/migrations/versions/0002_citations.py` - locked_highlights, payload key removal
- `backend/migrations/versions/0003_pipeline.py:1-120,161` - findings, chips schema, vector extension
- `backend/migrations/versions/0004_review_rounds.py:1-10` - review rounds
- `backend/migrations/versions/0005_open_review.py:1-19` - open review
- `backend/migrations/versions/0006_proofread.py:1-24` - proofread flow
- `backend/migrations/versions/0007_patient_summary.py` - patient summary column
- `backend/migrations/versions/0008_unit_removal.py` - removed status, refit kind
- `backend/migrations/versions/0009_drop_synthetic.py` - synthetic flag removal
- `backend/db/init.sql` - documents and chunks DDL
- `backend/db/minio/init-bucket.sh` - bucket and app user creation
- `backend/app/settings.py` - Settings keys and defaults
- `backend/app/prompts.py` - prompt loader
- `backend/app/knowledge/classifier.py:20,42` - classifier prompt constant and use
- `backend/app/proofread/enhance.py:24,96` - enhancement prompt constant and use
- `pyproject.toml` - workspace, groups, ruff, pytest
- `.env.example` - local environment template
- `infra/backend.Dockerfile` - production API image
- `infra/frontend.Dockerfile` - production web image
- `frontend/Dockerfile` - dev web image
- `infra/azure/docker-compose.yml` - VM stack
- `infra/azure/Caddyfile` - TLS reverse proxy
- `infra/azure/env.example` - VM environment template
- `infra/azure/deploy.sh` - VM deploy script
- `infra/azure/backup.sh` - database dump script
- `infra/azure/setup-vm.sh` - first-boot VM setup
- `infra/azure/vm.sh` - VM start, stop, status
- `infra/ts-serve.sh` - Tailscale serve for Ollama and LanguageTool
- `prompts/Answer_enhance.v2.md` - front-matter id, version and target (the other prompt files follow the same layout)
- `scripts/README.md` - run rules and folder map
- `scripts/corpus/chunk_parsed_documents.py:1-17` - module docstring
- `scripts/corpus/fetch_sources.py:1-12` - module docstring
- `scripts/corpus/index_chunks.py:1-15` - module docstring
- `scripts/corpus/parse_raw_documents.py:1-15` - module docstring
- `scripts/corpus/purge_sources.py:1-8` - module docstring
- `scripts/corpus/sources.py:1` - module docstring
- `scripts/corpus/storage.py:10-30` - S3 settings and client
- `scripts/corpus/upload_raw_documents.py:1-14` - module docstring
- `scripts/db/chips_backup.py:1` - module docstring
- `scripts/db/chips_schema.sql:1-7` - header comment
- `scripts/db/chips_snapshot.py:1-8` - module docstring
- `scripts/db/explore_chips.sql:1-6` - header comment
- `scripts/db/init_db.py` - applies init.sql
- `scripts/db/load_chips_pg.py:1-8` - module docstring
- `scripts/db/psql.sh:1-39` - psql wrapper and overview
- `scripts/db/seed_silver_reviews.py:1-2` - module docstring
- `scripts/elicitation/answer_vignettes.py:1-9` - module docstring
- `scripts/elicitation/build_chip_units.py:1-6` - module docstring
- `scripts/elicitation/chip_answers.py:1-6` - module docstring
- `scripts/elicitation/chip_findings.py:1-6` - module docstring
- `scripts/elicitation/chips_schema.py:1-6` - module docstring
- `scripts/elicitation/classify_sentence_targets.py:1-6` - module docstring
- `scripts/elicitation/elicitation_lifecycle.py:1-6` - module docstring
- `scripts/elicitation/elicitation_schema.py:1-6` - module docstring
- `scripts/elicitation/elicitation_units.py:1-6` - module docstring
- `scripts/elicitation/eval_enhance.py:1-8` - module docstring
- `scripts/elicitation/export_scale_answers.py:1-6` - module docstring
- `scripts/elicitation/export_schema.py:1-6` - module docstring
- `scripts/elicitation/fetch_reddit_pool.py:1-6` - module docstring
- `scripts/elicitation/leak_terms.py:1-6` - module docstring
- `scripts/elicitation/llm_clients.py:1-6` - module docstring
- `scripts/elicitation/make_chip_fixtures.py:1-6` - module docstring
- `scripts/elicitation/make_fixtures.py:1-8` - module docstring
- `scripts/elicitation/make_gold_claims.py:1-6` - module docstring
- `scripts/elicitation/make_scale_fixtures.py:1-12` - module docstring
- `scripts/elicitation/make_unit_keys.py:1-6` - module docstring
- `scripts/elicitation/migrate_q4_whatif.py:1-6` - module docstring
- `scripts/elicitation/prompt_loader.py:1-5` - re-export
- `scripts/elicitation/reddit_posts.py:1-6` - module docstring
- `scripts/elicitation/screen_reddit_posts.py:1-6` - module docstring
- `scripts/rag/ask.py:1` - module docstring
- `scripts/rag/chat_expert.py:1` - module docstring
- `scripts/rag/chip_retrieval.py:1` - module docstring
- `scripts/rag/compare_runs.py:1` - module docstring
- `scripts/rag/eval_chip_generation.py:1` - module docstring
- `scripts/rag/eval_chip_units.py:1` - module docstring
- `scripts/rag/eval_expert_generation.py:1` - module docstring
- `scripts/rag/eval_expert_units.py:1` - module docstring
- `scripts/rag/eval_generation.py:1` - module docstring
- `scripts/rag/eval_retrieval.py:1` - module docstring
- `scripts/rag/eval_scale_retrieval.py:1-8` - module docstring
- `scripts/rag/eval_style_diversity.py:1-6` - module docstring
- `scripts/rag/expert_metrics.py:1` - module docstring
- `scripts/rag/expert_retrieval.py:1` - module docstring
- `scripts/rag/judge_generations.py:1` - module docstring
- `scripts/rag/rag_common.py:1` - module docstring
- `scripts/rag/report_eval.py:1` - module docstring
- `scripts/rag/try_expert_rag.py:1-6` - module docstring
