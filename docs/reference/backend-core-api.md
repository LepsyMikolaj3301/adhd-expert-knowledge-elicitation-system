---
title: Backend core and API surface
diataxis: reference
---

# Backend core: app factory, settings, auth, users, home, audit

The `backend/app` top level and the packages `core`, `auth`, `users`, `home` and `audit` provide the FastAPI application under `/api/v1`, the `Settings` object, the database and error plumbing, password and session handling, the readiness probe for the machine that runs Ollama and LanguageTool, the Ollama chat and embedding clients, the prompt loader, the audit trail and the operator CLI.

Routes of the other routers (`vignettes`, `assignments`, `reviews`, `knowledge`) are in [backend-vignettes-knowledge.md](backend-vignettes-knowledge.md), [backend-assignments-jobs.md](backend-assignments-jobs.md) and [backend-reviews.md](backend-reviews.md). Indexing configuration and proofreading are in [backend-indexing-proofread.md](backend-indexing-proofread.md). Deployment and runtime wiring are in [runtime-and-deploy.md](runtime-and-deploy.md); the component view is in [architecture](../explanation/architecture.md). The page list is in [docs/index.md](../index.md).

## Application (`app.main`)

`create_app()` returns a `FastAPI` app titled `ADHD Expert Knowledge RAG Backend`. `app.main:app` is the module-level instance of `create_app()`.

| Item | Value |
|---|---|
| `API_PREFIX` | `/api/v1` |
| Swagger UI | `/api/v1/docs` |
| OpenAPI document | `/api/v1/openapi.json` |
| ReDoc | switched off (`redoc_url=None`) |
| Default error model for 4XX | `ErrorResponse` |
| Routers included under the prefix | `auth`, `users`, `vignettes`, `assignments`, `reviews`, `knowledge`, `home` (in this order), plus `GET /health` |

The lifespan handler does nothing when `settings.require_compute` is false. When it is true, it starts `compute.watch()` as a background task and cancels it on shutdown.

## HTTP routes

Paths are relative to `/api/v1`. The session is the cookie `session`. "Admin" means `AdminUser`: a logged-in user with role `admin`, otherwise 403 `forbidden`. "Login" means `CurrentUser`: a valid, unexpired session of an active user, otherwise 401 `not_authenticated`.

| Method and path | Access | Body | Success response |
|---|---|---|---|
| `GET /health` | none | none | 200 `{"status": "ok"}` |
| `POST /auth/login` | none | `LoginRequest` | 200 `UserView`, sets the cookie |
| `POST /auth/logout` | none | none | 204, deletes the cookie |
| `POST /auth/check-invite` | none | `CheckInviteRequest` | 204 |
| `POST /auth/accept-invite` | none | `AcceptInviteRequest` | 200 `UserView`, sets the cookie |
| `GET /me` | login | none | 200 `UserView` |
| `GET /users` | admin | none | 200 list of `UserAdminView`, ordered by `created_at` |
| `GET /users/by-pseudonym/{pseudonym}` | login | none | 200 `PersonAdminCard` for an admin viewer, `PersonCard` otherwise |
| `POST /users` | admin | `UserCreate` | 201 `InvitedUser` |
| `PATCH /users/{user_id}` | admin | `UserUpdate` | 200 `UserAdminView` |
| `POST /users/{user_id}/invite` | admin | none | 200 `InviteIssued` |
| `GET /me/home` | login | none | 200 `HomeView` |
| `POST /me/activity/seen` | login | optional `ActivitySeen` | 204 |

### Auth routes

- `POST /auth/login` lowercases the email and checks the password. An unknown email, a wrong password, an inactive account, an account without a password (invite not accepted) and a locked account all return 401 `invalid_credentials` with the same message. The password hash is verified in a thread pool even when the account cannot log in. Five failed attempts reset `failed_logins` to 0 and set `locked_until` to 15 minutes ahead. A successful login clears `failed_logins` and `locked_until`, replaces the stored hash when `needs_rehash` is true, deletes the user's expired sessions and creates a session. `login` commits itself so that a failed attempt is counted.
- `POST /auth/logout` deletes the `auth_sessions` row of the cookie token if a cookie is present, and deletes the cookie (path `/`). The status is 204 with or without a cookie.
- `POST /auth/check-invite` returns 204 when the invite exists, is unused, has not expired and belongs to an active user. Otherwise it returns 400 `invalid_invite`. It is a POST so that the token stays out of access logs.
- `POST /auth/accept-invite` hashes the password, then locks the invite row and validates it as above (400 `invalid_invite`). It sets `used_at`, stores the password hash, clears `failed_logins` and `locked_until`, deletes all sessions of the user, creates a new session and records the audit event `invite_accepted`.
- `GET /me` returns the current user.

The session cookie is set with `httponly`, `samesite="lax"`, path `/`, `max_age` of `session_ttl_hours * 3600` seconds, and `secure` when `settings.cookie_secure` is true or `settings.environment` is `production`.

### Users routes

- `POST /users` creates a user without a password, issues an invite and returns `InvitedUser`. A duplicate email returns 409 `email_taken`.
- `PATCH /users/{user_id}` changes `display_name` and `is_active` when given. Setting `is_active` to false for the acting admin's own account returns 409 `cannot_deactivate_self`. Deactivating another user deletes that user's sessions. A change of `is_active` records `user_activated` or `user_deactivated`. An unknown `user_id` returns 404 `not_found`.
- `POST /users/{user_id}/invite` deletes the user's unused invites, creates a new one and records `invite_issued`. Accepting it sets a new password, so the route also serves password reset.
- `GET /users/by-pseudonym/{pseudonym}` returns 404 `not_found` for an unknown pseudonym. `PersonAdminCard.cases` counts the person's assignments by state: `open` (ASSIGNED, IN_PROGRESS, PROOFREADING, PROOFREAD_CHECK), `in_review` (PEER_REVIEW), `done` (PROCESSING, PROCESSING_FAILED, INGESTING, INGESTION_FAILED, INGESTED) and `stopped` (CANCELLED, REJECTED).

The invite path has the form `/invite/<token>`; the token is returned once, and only its SHA-256 hash is stored.

### Home routes

`GET /me/home` returns `HomeView`, computed from the workflow tables on each call:

- `next_up` holds at most `NEXT_UP` assignments, newest `updated_at` first, with `next_up_total` the full count. An expert sees their own assignments in ASSIGNED (action `start`), IN_PROGRESS (`continue`) and PROOFREAD_CHECK (`check`). An admin sees all assignments in PROCESSING_FAILED or INGESTION_FAILED (action `retry`) and `expert_pseudonym` is filled only for the admin.
- `reviews_waiting` holds at most `WAITING` open reviews. For an admin these are all open reviews; for an expert, reviews where `relation` is `reviewer` and `my_votes < answer_count`. `reviews_waiting_total` is the full count. `recent_reviews` holds at most `RECENT` reviews of the viewer.
- `activity` holds at most `ACTIVITY` items, newest first, from two sources. Workflow events are `audit_events` of entity type `assignment` that the viewer did not cause. Comment items are comments by other people on the viewer's own assignments (`comment_on_mine`) or in threads the viewer took part in (`reply`); `excerpt` is the comment body cut to `EXCERPT` characters with `…` at the end.
- An item is `unread` when `activity_seen_at` is null or the item's `at` is later. `unread_activity` counts them.
- `system` is filled for admins and is null for experts.

Workflow events per viewer:

| Viewer | Events shown |
|---|---|
| Admin | `REVIEW_OPENED`, `REVIEW_CLOSED` and `JOB_FAILED` actions |
| Expert | `assigned` and `CHECK_READY` actions on their own assignments; `REVIEW_OPENED` on their own assignments or on vignettes that `access.blocked_vignettes` does not list; `REVIEW_CLOSED` on their own assignments or reviews they took part in |

`POST /me/activity/seen` sets `activity_seen_at` to `until`, or to the current time when the body or `until` is missing. The value is capped at the current time and never moves earlier than the stored value. `until` must carry a time zone (`AwareDatetime`) and the body forbids extra fields.

## Request and response models

| Model | Fields |
|---|---|
| `LoginRequest` | `email: EmailStr`, `password` (max 1024 characters); extra fields forbidden |
| `AcceptInviteRequest` | `token` (max 256), `password` (12 to 1024 characters); extra fields forbidden |
| `CheckInviteRequest` | `token` (max 256); extra fields forbidden |
| `UserView` | `id`, `email`, `display_name`, `role`, `pseudonym`, `is_active`, `created_at` |
| `UserAdminView` | `UserView` plus `invite_pending` (true while `password_hash` is null) |
| `UserCreate` | `email: EmailStr`, `display_name` (1 to 200), `role`; extra fields forbidden |
| `UserUpdate` | `display_name` (optional, 1 to 200), `is_active` (optional); extra fields forbidden |
| `InvitedUser` | `user: UserAdminView`, `invite_path` |
| `InviteIssued` | `invite_path` |
| `PersonCard` | `audience="peer"`, `pseudonym`, `role` |
| `PersonAdminCard` | `audience="admin"`, `pseudonym`, `role`, `display_name`, `email`, `is_active`, `cases: CaseCounts` |
| `CaseCounts` | `open`, `in_review`, `done`, `stopped` |
| `PersonView` | `PersonAdminCard` or `PersonCard`, discriminated by `audience` |
| `HomeView` | `next_up`, `next_up_total`, `reviews_waiting`, `reviews_waiting_total`, `recent_reviews`, `activity`, `unread_activity`, `system` |
| `NextUpItem` | `assignment_id`, `vignette_code`, `vignette_version`, `state`, `action`, `expert_pseudonym`, `updated_at` |
| `ActivityItem` | `kind`, `assignment_id`, `vignette_code`, `at`, `unread`; optional `question_id`, `comment_id`, `speaker`, `excerpt`, `outcome` |
| `SystemStatus` | `compute` (`ComputeStatus` or null), `waiting`, `waiting_for_pc`, `oldest_waiting_minutes` (or null), `stuck`, `failed_last_day` |
| `ComputeStatus` | `missing: list[str]`, `checked_seconds_ago` |
| `ActivitySeen` | `until: AwareDatetime` or null; extra fields forbidden |

Literals in `app.home.schemas`: `NextAction` is `start`, `continue`, `check`, `retry`. `ActivityKind` is `case_assigned`, `check_ready`, `review_opened`, `review_closed`, `comment_on_mine`, `reply`, `job_failed`. `Outcome` is `accepted`, `rejected`, `sent_back`.

`SystemStatus` is computed by `home.service.system_status(db)`: `waiting` counts jobs that are QUEUED or RUNNING with an expired `locked_until`; `waiting_for_pc` counts those that the last compute probe marks as blocked; `stuck` is true when a waiting job that is not blocked has waited more than `STUCK_MINUTES`; `failed_last_day` counts FAILED jobs created in the last 24 hours. `compute` is null when `REQUIRE_COMPUTE` is off.

## Error envelope (`app.core.errors`)

Every error body is `ErrorResponse`: `code: str`, `message: str`, `details: dict | None`.

| Raised by | Status | `code` | `details` |
|---|---|---|---|
| `DomainError(code, message, status_code=409, details=None)` | `status_code` | the given code | the given dict |
| `not_found(what="Resource")` | 404 | `not_found` | `{"resource": what}` |
| `invalid(code, message, details=None)` | 422 | the given code | the given dict |
| `forbidden(message="You may not do this.")` | 403 | `forbidden` | none |
| `RequestValidationError` | 422 | `validation_error` | `{"errors": [{loc, type, msg}]}` (no `input`) |
| Starlette `HTTPException` | its status | `http_error` | none |
| Any other exception | 500 | `internal_error` | none |

`SafeErrorMiddleware` answers unhandled exceptions and logs `safe_traceback(exc)`: stack frames and exception type names along the cause and context chain, without messages. It sends the 500 response only if the response has not started.

Codes raised in the files covered here:

| `code` | Status | Source of the error |
|---|---|---|
| `invalid_credentials` | 401 | `auth.service.login` |
| `not_authenticated` | 401 | `auth.dependencies.current_user` |
| `invalid_invite` | 400 | `auth.service` (check and accept invite) |
| `email_taken` | 409 | `users.service.create_user` |
| `cannot_deactivate_self` | 409 | `users.service.update_user` |
| `compute_unavailable` | 503 | `compute.require_compute` |
| `not_an_admin` | 422 | `app.cli` import-vignettes (printed, not an HTTP response) |

## Settings (`app.settings`)

`settings` is an instance of `Settings(BaseSettings)`. The class sets no env prefix, alias or env file, so each field is read from the environment variable named like the field in upper case: `.env.example` lists the names `DATABASE_URL`, `ENVIRONMENT`, `COOKIE_SECURE`, `REQUIRE_COMPUTE`, `SESSION_TTL_HOURS`, `OLLAMA_BASE_URL`, `CLASSIFIER_MODEL`, `ENHANCE_MODEL`, `LANGUAGETOOL_URL` and `LANGUAGETOOL_LANGUAGE`. The other fields follow the same rule (`OLLAMA_REQUEST_TIMEOUT`, `LANGUAGETOOL_TIMEOUT`, `PROJECT_ROOT`).

| Field | Type | Default | Description |
|---|---|---|---|
| `database_url` | `str` | `postgresql://rag:rag@localhost:5432/rag` | PostgreSQL URL; `to_async_url` replaces the first `postgresql://` with `postgresql+asyncpg://` |
| `ollama_base_url` | `str` | `http://localhost:11434` | Ollama server for chat, embeddings and probes |
| `require_compute` | `bool` | `False` | Turns on the readiness check and the background probe (see Compute) |
| `classifier_model` | `str` | `qwen3.5:9b` | Model that files sentences without a citation |
| `ollama_request_timeout` | `float` | `600` | Timeout in seconds of `chat_json` |
| `languagetool_url` | `str` | `http://localhost:8010` | LanguageTool server |
| `languagetool_language` | `str` | `en-US` | LanguageTool language |
| `languagetool_timeout` | `float` | `60` | Timeout in seconds of the LanguageTool client; `backend/app/proofread/grammar.py:93` reads it |
| `enhance_model` | `str` | `qwen3.5:9b` | Model that turns fragments into sentences; an empty string switches enhancement off |
| `project_root` | `Path` | `Path(__file__).resolve().parents[2]` of `settings.py` (the folder that contains `backend/`) | Folder with `prompts/` and `config/` |
| `environment` | `"development"` or `"production"` | `development` | Any other value stops the app at startup; `production` forces the secure cookie |
| `cookie_secure` | `bool` | `False` | Marks the session cookie HTTPS-only |
| `session_ttl_hours` | `int` | `12` | Lifetime of a session row and of the cookie |

## Compute readiness (`app.compute`)

The module probes the machine that hosts Ollama and LanguageTool. It is inactive unless `settings.require_compute` is true.

| Function | Behaviour |
|---|---|
| `probe() -> Probe` | Calls `GET /api/tags` on Ollama and `GET /v2/languages` on LanguageTool concurrently (timeout `TIMEOUT`) and stores the result as the last probe. `Probe.models` is null when Ollama is unreachable. |
| `watch() -> None` | Loops: `probe()`, then sleeps `WATCH_EVERY`. An exception is logged with `safe_traceback` and the loop continues. |
| `require_compute(kind: JobKind) -> None` | Returns when the check is off or neither `kind` nor its `FOLLOWED_BY` kind needs compute. Otherwise it uses the last probe, redone when older than `API_TRUSTS`, and raises `DomainError` 503 `compute_unavailable` with `details={"missing": [...]}` when something is missing. |
| `ready_kinds() -> set[JobKind] or None` | Job kinds with nothing missing, from a probe at most `WORKER_TRUSTS` old; `None` when the check is off. |
| `is_down_for(kind) -> bool` | Probes again and returns whether `kind` is blocked; `False` when the check is off or `kind` needs no compute. |
| `latest() -> Probe or None` | The last probe (redone after `API_TRUSTS`); `None` when the check is off. |
| `missing_now(seen)` and `blocked(seen, kind)` | Missing items over all `JobKind` values, and whether one kind is blocked by a probe. |
| `forget()` | Drops the last probe. |
| `client(base_url)` | Builds the `httpx.AsyncClient` used for probes; the source marks it as the replacement point for tests. |

What each kind needs (`_models`, `needs_compute`):

| Kind | Needs |
|---|---|
| `PROOFREAD` | `classifier_model` and `enhance_model` (an empty name is skipped) in Ollama, and LanguageTool |
| `INGEST` | the embeddings model named in `config/indexing.yaml` (`embeddings.model`) |
| `PROCESS` | nothing itself; `FOLLOWED_BY` maps it to `INGEST`, so `require_compute(PROCESS)` checks the embedding model |

Entries in `missing` are `ollama`, `model <name>` and `languagetool`. A model name without a tag matches `<name>:latest` in Ollama's list.

| Constant | Value |
|---|---|
| `TIMEOUT` | `3.0` seconds, per probe request |
| `WATCH_EVERY` | `10.0` seconds |
| `API_TRUSTS` | `30.0` seconds |
| `WORKER_TRUSTS` | `15.0` seconds |
| `FOLLOWED_BY` | `{JobKind.PROCESS: JobKind.INGEST}` |

`Probe` is a frozen dataclass: `at` (monotonic time), `models` (`frozenset[str]` or `None`), `languagetool` (`bool`).

## Ollama and embedding clients

| Signature | Behaviour |
|---|---|
| `ollama.chat_json(model: str, system: str or None, user: str, options: dict) -> str` | `POST /api/chat` with `stream=False`, `think=False`, `format="json"` and the given `options`. A system message is sent when `system` is non-empty. Returns `message.content`. Raises on an HTTP error status. |
| `ollama.parse_json_object(raw: str) -> dict or None` | Strips a surrounding code fence and parses JSON. Returns `None` for invalid JSON or a value that is not an object. |
| `embeddings.Embedder` | `Protocol` with `embed(texts: list[str]) -> np.ndarray`, one L2-normalised row per text. |
| `embeddings.OllamaEmbedder(model, batch_size=64, truncate=True, base_url=None)` | Synchronous client (timeout 300 seconds, `base_url` defaults to `settings.ollama_base_url`). `embed(texts)` posts batches to `/api/embed` with `model`, `input` and `truncate`, and returns a `float32` array with rows divided by their norm (norm floor `1e-12`). A 404 raises `RuntimeError` naming `ollama pull <model>`. Other HTTP errors raise. |

## Prompt loader (`app.prompts`)

`PROMPTS_DIR` is `settings.project_root / "prompts"`. `PromptError` is a `ValueError`. `Prompt` is a frozen dataclass: `id`, `version` (int), `meta` (dict), `system` (str or None), `user` (str).

- `load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt` reads `<name>.md`. The file must start with `---\n` and a front matter block that contains `id` and `version`. A `# Template` section gives `user` with `system=None`. Otherwise a `# User` section is required and a `# System` section is optional; without either, `PromptError` is raised. Front matter is parsed as `key: value` per line, split at the first colon; a line without a colon raises `PromptError`; a value that starts with `{` or `[` is parsed as YAML and falls back to the string.
- `Prompt.fill(**variables) -> Prompt` replaces `{{NAME}}` (upper case letters, digits, underscore) in `system` and `user` and strips the result. A placeholder without a value, or a variable that appears in neither section, raises `PromptError`. A hint after a placeholder (two or more spaces or tabs, then text in parentheses) is dropped. A `{{IF_VARIANT}} ... {{END_IF}}` block is kept when `IF_VARIANT` is truthy and removed otherwise.

## Database layer (`app.core.db`)

| Name | Description |
|---|---|
| `APP_SCHEMA` | `app`, the schema of every table declared on `Base` |
| `NAMING_CONVENTION` | name patterns for `ix`, `uq`, `ck`, `fk` and `pk` constraints |
| `Base` | `DeclarativeBase` with `MetaData(schema="app", naming_convention=...)` |
| `utcnow() -> datetime` | current time in UTC |
| `enum_column(enum_class, name)` | non-native enum column of length 32 with a CHECK constraint, stored by member value |
| `to_async_url(url)` | adds the `+asyncpg` driver to the URL |
| `configure_engine(url=None, **engine_options)` | creates the async engine (`hide_parameters=True`) and a session factory with `expire_on_commit=False`; `url` defaults to `settings.database_url` |
| `session_factory()` | the session factory; calls `configure_engine()` first when none exists |
| `database_url()` | the URL the engine was configured with, or `settings.database_url` |
| `get_session()` and `DbSession` | request-scoped session dependency; routers commit explicitly |

`app.models` imports the ORM classes `AnswerComment`, `AnswerDecision`, `AnswerDraft`, `AnswerRevision`, `AnswerVote`, `AnswerFindings`, `Assignment`, `AuditEvent`, `AuthSession`, `Invite`, `Job`, `KnowledgeUnit`, `ProofreadRound`, `ReviewParticipant`, `Submission`, `User`, `Vignette` and `VignetteVersion`, so that `Base.metadata` holds every table.

## Security helpers (`app.core.security`)

| Function | Behaviour |
|---|---|
| `hash_password(password) -> str` | Argon2 hash with `argon2.PasswordHasher()` defaults |
| `verify_password(password_hash or None, password) -> bool` | Verifies against a dummy hash when the hash is `None` and returns `False` in that case; `False` on a verification or invalid-hash error |
| `needs_rehash(password_hash) -> bool` | `check_needs_rehash` of the hasher |
| `run_hash(function, *args)` | Runs a hash function in a `ThreadPoolExecutor` of 4 workers |
| `new_token() -> str` | `secrets.token_urlsafe(32)` |
| `hash_token(token) -> str` | SHA-256 hex digest |
| `content_hash(text) -> str` | SHA-256 hex digest of the UTF-8 text |

## Auth constants and dependencies

| Name | Value |
|---|---|
| `SESSION_COOKIE` | `session` |
| `MAX_FAILED_LOGINS` | `5` |
| `LOCKOUT` | 15 minutes |
| `INVITE_TTL` | 7 days |
| `MIN_PASSWORD_LENGTH` / `MAX_PASSWORD_LENGTH` | `12` / `1024` |

`auth.dependencies` defines `current_user`, `CurrentUser`, `require_role(role)` and `AdminUser`. `auth.service` also provides `create_session`, `set_session_cookie`, `end_all_sessions` and `issue_invite`.

## Tables

| Class (table) | Columns |
|---|---|
| `User` (`users`) | `id` UUID; `email` String(320), unique, CHECK `email = lower(email)`; `display_name` String(200); `role` (`Role`); `pseudonym` String(32), unique; `password_hash` String(255), null until the invite is accepted; `is_active` (default true); `failed_logins` (default 0); `locked_until`; `activity_seen_at`; `created_at` |
| `AuthSession` (`auth_sessions`) | `token_hash` String(64), primary key; `user_id` FK to `users` (cascade); `expires_at`; `created_at` |
| `Invite` (`invites`) | `id`; `user_id` FK to `users` (cascade); `token_hash` String(64), unique; `expires_at`; `used_at`, null until used |
| `AuditEvent` (`audit_events`) | `id`; `actor_id` FK to `users`, null for the system; `entity_type` String(32); `entity_id`; `action` String(64); `from_state`, `to_state` String(32); `meta` JSONB in the column `metadata`; `at`. Indexes on (`entity_type`, `entity_id`, `at`) and (`action`, `at`) |

`Role` is a `StrEnum` with `ADMIN = "admin"` and `EXPERT = "expert"`. `PSEUDONYM_SEQUENCE` is the sequence `user_pseudonym_seq`; a pseudonym is `A` (admin) or `E` (expert) followed by the sequence number with at least two digits. The `AuditEvent` docstring states that a database trigger rejects UPDATE and that the table must not hold answer or unit text; the trigger is not defined in the files covered here.

`audit.service.record_event(db, *, actor_id, entity_type, entity_id, action, from_state=None, to_state=None, meta=None) -> None` adds an `AuditEvent` to the open transaction without committing. `meta` defaults to `{}`.

Audit actions recorded in the files covered here: `user_created` (meta `{"role": ...}`), `user_activated`, `user_deactivated`, `invite_issued`, `invite_accepted`.

## Home constants (`app.home.service`)

| Name | Value |
|---|---|
| `NEXT_UP` | `5` |
| `WAITING` | `5` |
| `RECENT` | `10` |
| `ACTIVITY` | `30` |
| `EXCERPT` | `140` |
| `STUCK_MINUTES` | `5` |
| `REVIEW_OPENED` | `submit_for_review`, `units_built`, `units_built_for_peers` |
| `REVIEW_CLOSED` | `approve_answers` and `approve_units` (accepted), `reject_all_answers` and `reject_all_units` (rejected), `request_changes` (sent_back) |
| `JOB_FAILED` | `proofread_failed`, `processing_failed`, `units_failed`, `ingestion_failed` |
| `CHECK_READY` | `proofread_succeeded` |

## CLI (`python -m app.cli`)

The module docstring gives the invocation `python -m app.cli <command>`. The options listed for each command are required. Errors are printed to stderr and the exit code is 1.

| Command | Options | Behaviour |
|---|---|---|
| `create-admin` | `--email`, `--name` | Validates the email with `EmailStr` (the same rule as login, so reserved domains such as `.local` are refused), prompts for the password with `getpass`, checks that it has 12 to 1024 characters, creates a user with role `admin` and that password, and prints `Created admin <pseudonym>`. A duplicate email prints the message of the `email_taken` error. |
| `export-openapi` | `--out PATH` | Writes `create_app().openapi()` to `PATH` as JSON with 2-space indent and sorted keys, ending in a newline. |
| `import-vignettes` | `--dir DIR`, `--whatifs FILE`, `--admin-email EMAIL` | Reads the what-if texts from `FILE`, finds the user by lowercased email and requires an active admin (`not_an_admin`, 422, otherwise), calls `app.vignettes.importing.import_vignettes` and commits. Prints the created codes and, when present, the skipped codes. The docstring states that `DIR` holds `V*.json` files loaded as drafts, that `FILE` maps codes to texts (`{"V001": "..."}`), that the import is all or nothing and that existing codes are skipped. |

## Sources in code

- `backend/app/main.py` - app factory, prefix, router list, lifespan
- `backend/app/cli.py` - CLI commands and options
- `backend/app/settings.py` - Settings fields and defaults
- `.env.example` - environment variable names set for the backend
- `backend/app/compute.py` - probe, gates, constants
- `backend/app/ollama.py` - chat_json, parse_json_object
- `backend/app/embeddings.py` - Embedder, OllamaEmbedder
- `backend/app/prompts.py` - prompt loader and fill rules
- `backend/app/models.py` - ORM class registry
- `backend/app/core/db.py` - Base, engine, session dependency
- `backend/app/core/errors.py` - error envelope, handlers, middleware
- `backend/app/core/security.py` - hashing and token helpers
- `backend/app/auth/router.py` - auth routes and /me
- `backend/app/auth/service.py` - login, lockout, invites, cookie, constants
- `backend/app/auth/schemas.py` - request bodies and password limits
- `backend/app/auth/dependencies.py` - current_user and role dependencies
- `backend/app/auth/models.py` - AuthSession and Invite tables
- `backend/app/users/router.py` - users routes
- `backend/app/users/service.py` - user creation, update, person card
- `backend/app/users/models.py` - User table, Role, pseudonym sequence
- `backend/app/users/schemas.py` - user and person view models
- `backend/app/home/router.py` - home routes
- `backend/app/home/schemas.py` - home view models and literals
- `backend/app/home/service.py` - home feed, system status, constants
- `backend/app/audit/models.py` - AuditEvent table
- `backend/app/audit/service.py` - record_event
