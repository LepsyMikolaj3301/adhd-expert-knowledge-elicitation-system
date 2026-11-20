---
title: Backend assignments and jobs
diataxis: reference
---

# Backend: `app.assignments` and `app.jobs`

`app.assignments` holds the per-expert workflow of one published vignette version: HTTP routes, a state machine whose only writer of `Assignment.state` is `transition()`, the answer payload models and the tables `assignments`, `answer_drafts` and `submissions`. `app.jobs` is a Postgres-backed job queue with leases, the handlers of each job kind and the worker process (`python -m app.jobs.worker`) that drains it. Peer-review routes are in [backend-reviews.md](backend-reviews.md); the way the pieces fit together is in [assignment-lifecycle.md](../explanation/assignment-lifecycle.md).

All routes are mounted under `/api/v1` (`API_PREFIX`) with the tag `assignments`. Errors use the shape `{code, message, details}`; a `DomainError` defaults to HTTP 409, `not_found` is 404, `invalid` is 422 and `forbidden` is 403.

## HTTP routes

The "Who" column names the actor: `admin`, `assignee` (the expert the assignment belongs to) or any viewer who may see the assignment. A viewer unrelated to an assignment gets 404 `not_found`, not 403.

| Route | Who | Behaviour |
|---|---|---|
| `POST /vignette-versions/{version_id}/assignments` | admin | Body `{expert_ids: UUID[1..500]}`. Returns 201 with a list of admin views. Errors: `version_not_published` (409), `invalid_assignee` (422, not an active expert), `reviewer_contaminated` (409, an expert has opened a review of this vignette), `already_assigned` (409, a non-cancelled assignment of the same version exists). |
| `GET /assignments` | any | Query `state`, `vignette_version_id`, `limit` (1..500, default 100), `offset` (>= 0, default 0). The admin sees all assignments, newest `updated_at` first. An expert sees their own, in a stable pseudo-random order (`md5(expert_id \|\| vignette_id)`, then version). Each summary carries `allowed_actions` and `job_running`. |
| `GET /assignments/{assignment_id}` | any | One view per audience (see Views). |
| `GET /assignments/{assignment_id}/events` | assignee, admin | Audit timeline. Reviewers get 404. The assignee does not see `REVIEW_CHATTER` events and sees each actor as `you`, `admin`, `reviewer` or `system`. |
| `GET /assignments/{assignment_id}/submission` | assignee, admin | The frozen submission. Reviewers and a missing submission give 404. |
| `POST /assignments/{assignment_id}/start` | assignee | `assigned -> in_progress`. Sets `started_at` and inserts an `AnswerDraft` with an empty payload. |
| `POST /assignments/{assignment_id}/cancel` | admin | Allowed from `assigned`, `in_progress`, `proofread_check` and `peer_review`; other states give 409 `illegal_transition`. |
| `PUT /assignments/{assignment_id}/draft` | assignee | Body `{version, payload}`. Only in `in_progress` (else 409 `not_editable`). A `version` that differs from the stored one gives 409 `draft_conflict` with `details.current_version`. Returns `{version, updated_at}` and increments the stored version. |
| `POST /assignments/{assignment_id}/submit` | assignee | Only in `in_progress`. Validates the draft with `clean_submission`, inserts the `Submission` row and moves to `proofreading`, which queues a `proofread` job. |
| `GET /assignments/{assignment_id}/findings` | admin | How the approved answers were filed: highlights, sentences, flags and `check_outcome`. Others and a missing record give 404 `not_found`. |
| `GET /assignments/{assignment_id}/proofread` | assignee, admin | Query `review_round`. Delegates to `app.proofread.service.view`. |
| `PUT /assignments/{assignment_id}/proofread` | assignee | Locks the assignment row, then delegates to `app.proofread.service.save`. |
| `POST /assignments/{assignment_id}/submit-for-review` | assignee | Delegates to `app.proofread.service.submit_for_review`: `proofread_check -> peer_review`. |
| `POST /assignments/{assignment_id}/retry` | admin | Runs again the kind of the most recent `failed` job of the assignment. With no failed job: 409 `illegal_transition`. |

Routes that change an assignment lock its row (`lock_assignment`, `SELECT ... FOR UPDATE`) before they act and commit afterwards.

### Access rules

`actor_for` maps the viewer to an `Actor`: an admin user is `admin`, the owner of the assignment is `assignee`, an expert for whom `reviews.access.may_review` is true is `reviewer`; anyone else gets 404. A reviewer who has not opened the review gets 409 `review_not_opened` from `load` and `lock`, except on `POST .../review/open`.

### `allowed_actions`

`allowed_actions(state, actor)` returns a sorted list built from the transition table (`USER_ACTION_NAMES`) plus four extra names:

| Name | Added when |
|---|---|
| `save_draft` | state `in_progress` and actor `assignee` |
| `edit_proofread` | state `proofread_check` and actor `assignee` |
| `comment` | state `peer_review`, any actor |
| `vote` | state `peer_review` and actor `reviewer` |

`USER_ACTION_NAMES` maps `start`, `cancel`, `submit` and `submit_for_review` to themselves, the three `retry_*` actions to `retry`, and `approve_answers`, `reject_all_answers` and `request_changes` to `decide_answers`.

### Views

`AssignmentView` is a union discriminated by `audience`, so hidden data has no field to leak through.

| `audience` | Model | Content beyond `id`, `state`, `review_round`, `allowed_actions`, `updated_at` |
|---|---|---|
| `expert` | `ExpertAssignment` | `vignette` (`ExpertVignette`, with `content_hash` and the visible `questions`), `draft`, `started_at`, `submitted_at` |
| `peer` | `PeerAssignment` | `vignette` (`PeerVignette`: code, version, text, framing, patient summary, word count); no author identity |
| `admin` | `AdminAssignment` | `expert_id`, `expert_pseudonym`, vignette code and version, `vignette_version_id`, `vignette`, `started_at`, `submitted_at` |

`AssignmentSummary` (list items) has `job_running`, true when the state is in `JOB_STATES`. The event models are `EventAdminView` (`actor_id`, `meta`) and `EventAuthorView` (`actor` reduced to a role).

## State machine

States, actions and actors are `StrEnum`s in `states.py`; the rules are in `state_machine.py`.

| `State` | Value | Class |
|---|---|---|
| `ASSIGNED` | `assigned` | |
| `IN_PROGRESS` | `in_progress` | |
| `PROOFREADING` | `proofreading` | job state |
| `PROOFREAD_CHECK` | `proofread_check` | |
| `PEER_REVIEW` | `peer_review` | |
| `PROCESSING` | `processing` | job state |
| `PROCESSING_FAILED` | `processing_failed` | |
| `INGESTING` | `ingesting` | job state |
| `INGESTION_FAILED` | `ingestion_failed` | |
| `INGESTED` | `ingested` | terminal |
| `REJECTED` | `rejected` | terminal |
| `CANCELLED` | `cancelled` | terminal |

`TERMINAL_STATES` is `{ingested, rejected, cancelled}`. `JOB_STATES` is `{proofreading, processing, ingesting}`. `Actor` has `assignee`, `admin`, `reviewer` and `system`.

### Transitions

`TRANSITIONS` maps `(state, action)` to a `Rule(to, actors)`. It has 19 entries.

| From | Action | To | Actor |
|---|---|---|---|
| `assigned` | `start` | `in_progress` | assignee |
| `assigned` | `cancel` | `cancelled` | admin |
| `in_progress` | `cancel` | `cancelled` | admin |
| `in_progress` | `submit` | `proofreading` | assignee |
| `proofreading` | `proofread_succeeded` | `proofread_check` | system |
| `proofreading` | `proofread_failed` | `processing_failed` | system |
| `proofread_check` | `cancel` | `cancelled` | admin |
| `proofread_check` | `submit_for_review` | `peer_review` | assignee |
| `peer_review` | `cancel` | `cancelled` | admin |
| `peer_review` | `approve_answers` | `processing` | admin |
| `peer_review` | `reject_all_answers` | `rejected` | admin |
| `peer_review` | `request_changes` | `proofread_check` | admin |
| `processing` | `processing_succeeded` | `ingesting` | system |
| `processing` | `processing_failed` | `processing_failed` | system |
| `processing_failed` | `retry_proofread` | `proofreading` | admin |
| `processing_failed` | `retry_processing` | `processing` | admin |
| `ingesting` | `ingestion_succeeded` | `ingested` | system |
| `ingesting` | `ingestion_failed` | `ingestion_failed` | system |
| `ingestion_failed` | `retry_ingestion` | `ingesting` | admin |

`processing_failed` is entered both from a failed proofread job and from a failed process job; `retry` picks the action from the kind of the latest failed job (`RETRY_BY_JOB`).

### `transition(db, assignment, action, actor, actor_id, meta=None) -> None`

The only writer of `Assignment.state`. The caller holds the row lock and commits. It:

1. calls `check_transition`, which raises 409 `illegal_transition` (with `details.state` and `details.action`) when the pair has no rule, or 403 `forbidden` when the actor is not in the rule;
2. when the target state has a job (`JOB_ON_ENTRY`) and the actor is not `system`, awaits `app.compute.require_compute(kind)`, which raises 503 `compute_unavailable` when `REQUIRE_COMPUTE` is on and the needed machine is not ready;
3. sets the new state and records an audit event (`record_event`) with the action name, `from_state`, `to_state` and `meta`;
4. adds a `Job` row for the entered state.

`JOB_ON_ENTRY`: `proofreading -> proofread`, `processing -> process`, `ingesting -> ingest`.

### Helpers

| Function | Description |
|---|---|
| `check_transition(state, action, actor) -> Rule` | Validates a move without applying it. |
| `user_actions(state, actor) -> set[str]` | Names of the user actions available to the actor in the state. |
| `lock_assignment(db, assignment_id) -> Assignment` | `SELECT ... FOR UPDATE` with `populate_existing`; 404 `not_found` when missing. |

## Answer payload (`answers.py`)

| Model | Fields |
|---|---|
| `Highlight` | `chip` (>= 1), `text` (1..2000 chars), `span` (start, end; code-point offsets in the vignette text), `direction` (`toward`, `away`, `neutral`, `unclear`, or `None` while drafting) |
| `Q4Answer` | `hypothesis`, `shift` (-2..2, `None` means no answer), `toward` (`more_adhd`, `less_adhd`, `other`), `other_explanation` |
| `AnswerPayload` | `answers` (per question id, max 20 000 chars each), `highlights` (max 200), `q4`, `rating` (1..5), `insufficient_information` (bool, default false) |

All three models forbid extra fields. `PAYLOAD_FORMAT = 2` is stored in `Submission.payload_format`.

Draft checks (`check_draft`, lenient about completeness): `question_not_asked`, `answer_to_rating_question`, `chip_numbers` (citations are numbered 1..n in order), `highlight_not_in_vignette` (422).

Submission checks (`clean_submission`, raises the first problem found, all as 422): `question_not_asked` and `answer_to_rating_question`; every question of kind `open` has a non-blank answer (`empty_answer`); `chip_numbers` and `highlight_not_in_vignette`; every chip `⟦hN⟧` in an answer points at a citation (`unknown_chip`); every citation has a direction (`highlight_no_direction`); a rating and `insufficient_information` are exclusive (`rating_conflict`); when Q6 is asked, one of them is required (`submission_incomplete`). For Q4: `submission_incomplete` for a missing scale point, hypothesis, direction or explanation, plus `q4_why_without_shift`, `toward_without_change` and `other_without_name`. The returned payload has answers and Q4 text trimmed.

The submission payload also stores `vignette_code`, `vignette_version`, `expert_pseudonym`, `started_at` and `submitted_at`; `Submission.vignette_hash` is the version's `content_hash`.

## Findings view (`check.py`)

`check.get` reads the `AnswerFindings` row of the assignment and returns `FindingsView`: `version`, `review_round`, `check_outcome` (`completed`, `skipped` or `None`), `highlights` (`FindingHighlight`: `id`, `chip`, `text`, `origin` `expert` or `implicit`, `direction`), `sentences` (`FindingSentence`: `id`, `question_id`, `text`, `targets`, `assigned_by` one of `chip`, `quote`, `llm`, `expert`) and `flags` (`FindingFlag`: `kind` `coverage` or `direction`, `highlight`, `sentence`, `message`).

## Tables

| Table (`Model`) | Columns |
|---|---|
| `assignments` (`Assignment`) | `id`, `vignette_version_id`, `expert_id`, `assigned_by`, `state`, `review_round` (default 1), `started_at`, `submitted_at`, `created_at`, `updated_at` |
| `answer_drafts` (`AnswerDraft`) | `assignment_id` (PK, cascade delete), `payload` JSONB, `version` (default 1), `updated_at` |
| `submissions` (`Submission`) | `assignment_id` (PK), `payload` JSONB, `payload_format`, `vignette_hash` (64 chars), `submitted_at` |
| `jobs` (`Job`) | `id`, `kind`, `assignment_id` (nullable), `status`, `attempts` (default 0), `locked_until`, `last_error` (200 chars), `created_at` |

Indexes: `uq_assignments_active` is unique on (`vignette_version_id`, `expert_id`) where `state <> 'cancelled'`. `uq_jobs_active` is unique on (`assignment_id`, `kind`) where `status IN ('queued', 'running')`. `ix_jobs_claim` is on (`status`, `created_at`). The docstring of `Submission` states that a database trigger rejects UPDATE; the trigger is in the initial migration, which this page does not cover.

## Job queue

`JobKind`: `proofread`, `process`, `ingest`, `refit` (corpus-wide, no assignment). `JobStatus`: `queued`, `running`, `done`, `failed`.

### `next_job(db, kinds=None) -> Job | None`

Returns the oldest job (by `created_at`) that is `queued`, or `running` with `locked_until` in the past. `kinds` restricts the result to those kinds; `None` means any. The query uses `FOR UPDATE SKIP LOCKED`, so several workers do not take the same row.

## Worker (`python -m app.jobs.worker`)

`main()` loops over `run_once()` and sleeps `POLL_SECONDS` when it returns False or raises. A separate task touches `ALIVE_FILE` every `ALIVE_SECONDS`. The module imports `app.models` so that every table is known without `app.main`.

### `run_once() -> bool`

Claims and runs one job; returns False when there was none.

1. `compute.ready_kinds()` gives the kinds that can run (`None` when `REQUIRE_COMPUTE` is off); `next_job` claims one of them.
2. A claimed job whose `attempts` is already `MAX_ATTEMPTS` (its worker died) is failed with `last_error = "LeaseExpired"`.
3. Otherwise the job becomes `running`, `attempts` is incremented, `locked_until = now + LEASE`, and the claim is committed.
4. A heartbeat task renews `locked_until` every `LEASE / 3` while the job runs; a renewal error is logged and does not stop the job.
5. A corpus job (`assignment_id` is None) runs `CORPUS_HANDLERS[kind](db)` and is marked `done`.
6. An assignment job runs `PREPARE[kind](assignment_id)` (if the kind has one) with no transaction and no lock open. Then, in one transaction, it locks the assignment, re-reads the job with `_current` (which returns None when the lease expired and another worker took the job), runs `HANDLERS[kind]`, marks the job `done` and calls `transition` with `SUCCESS_ACTION[kind]` as `system`.
7. On an exception: the error class name is logged with a traceback without messages and stored as `last_error`.
   - If the exception is not a `PermanentJobError` and `compute.is_down_for(kind)` is true, the job returns to `queued` and the attempt is not counted.
   - If it is a `PermanentJobError` or `attempt >= MAX_ATTEMPTS`, `_fail` marks the job `failed`, clears the lease and, for an assignment job, moves the assignment with `FAILURE_ACTION[kind]`.
   - Otherwise the job returns to `queued`.

| `JobKind` | `SUCCESS_ACTION` | `FAILURE_ACTION` |
|---|---|---|
| `proofread` | `proofread_succeeded` | `proofread_failed` |
| `process` | `processing_succeeded` | `processing_failed` |
| `ingest` | `ingestion_succeeded` | `ingestion_failed` |

### Handlers (`handlers.py`)

| Kind | `PREPARE` | Handler |
|---|---|---|
| `proofread` | `app.proofread.service.prepare` | `app.proofread.service.record` |
| `process` | none | `process` |
| `ingest` | `prepare_ingest` | `ingest` |
| `refit` | none | `refit` (in `CORPUS_HANDLERS`) |

- `process(db, assignment, prepared=None)` loads the submission, the proofread round and the question ids whose `AnswerDecision` for the current round is `approve`, and builds an `AnswerFindings` record from the author's final lines (`findings.record_from_lines`). It stores the record on the `AnswerFindings` row (created with `version=1` when absent) with `check_outcome = "completed"`, and inserts one `KnowledgeUnit` per unit with status `approved`. It raises `NoFindings` when the submission or the round is missing and `NoUnits` when the record has no units.
- `prepare_ingest(assignment_id)` loads what was approved (`ingest.load`) and embeds it (`ingest.embed`), outside the worker's transaction.
- `ingest(db, assignment, prepared)` writes the prepared units with `ingest.write` and sets the assignment's `approved` units to `ingested`.
- `refit(db)` takes `pg_advisory_xact_lock(BM25_LOCK)` and calls `ingest.refresh_sparse`. The module comment says it refits BM25 over the whole knowledge base; the comment names the removal of units as the trigger.
- `unit_content_hash(embed_text, embed_text_combined) -> str` hashes both texts joined by a newline.

### Errors (`errors.py`)

| Class | Meaning |
|---|---|
| `PermanentJobError` | Retrying cannot help: the job fails at once. Base class. |
| `NoFindings` | Subclass: nothing to build from. |
| `NoUnits` | Subclass: the record has no units. |
| `UnitsNotEmbeddable` | Subclass: stored units have no text to embed. |

## Constants and configuration

| Name | Value | Meaning |
|---|---|---|
| `MAX_ATTEMPTS` | `3` | Attempts before a job fails. |
| `LEASE` | `timedelta(minutes=5)` | Lease length; the heartbeat renews it every `LEASE / 3`. |
| `POLL_SECONDS` | `2.0` | Idle wait between claim attempts. |
| `ALIVE_FILE` | `/tmp/worker-alive` | File the worker touches for the container healthcheck. |
| `ALIVE_SECONDS` | `10.0` | Interval of the touch. |
| `PAYLOAD_FORMAT` | `2` | Format number of a stored submission payload. |
| `REVIEW_CHATTER` | `("review_opened", "comment_added", "vote_cast")` | Audit actions hidden from the author's timeline. |
| `LEGACY_PEER_ACTIONS` | `{"peers_approved", "peer_rejected"}` | Event actions shown to the author as `reviewer`. |
| `REQUIRE_COMPUTE` | `false` | Setting `require_compute`. When true, `transition` returns 503 for user actions that enter a job state while the compute machine is not ready, and the worker holds back jobs whose machine is down. Default in `.env.example`. |

Other limits: `AnswerText` 20 000 chars, `ShortText` 2 000 chars, `highlights` 200 items, `AssignRequest.expert_ids` 1..500.

## Sources in code

- `backend/app/assignments/router.py` - routes and their locking and commit pattern
- `backend/app/assignments/service.py` - access checks, views, assigning, drafts, submit, retry, timeline, allowed_actions
- `backend/app/assignments/state_machine.py` - TRANSITIONS, JOB_ON_ENTRY, transition, lock_assignment
- `backend/app/assignments/states.py` - State, Action, Actor, TERMINAL_STATES, JOB_STATES
- `backend/app/assignments/models.py` - Assignment, AnswerDraft, Submission and the partial unique index
- `backend/app/assignments/answers.py` - payload models, draft and submission checks, PAYLOAD_FORMAT
- `backend/app/assignments/check.py` - findings view
- `backend/app/assignments/schemas.py` - views per audience, request and event models
- `backend/app/jobs/models.py` - Job, JobKind, JobStatus, indexes
- `backend/app/jobs/queue.py` - next_job, MAX_ATTEMPTS, LEASE
- `backend/app/jobs/worker.py` - run_once, heartbeat, failure handling, constants
- `backend/app/jobs/handlers.py` - PREPARE, HANDLERS, CORPUS_HANDLERS and the handlers
- `backend/app/jobs/errors.py` - PermanentJobError and subclasses
- `backend/app/main.py:19,53-63` - API_PREFIX and router mounting
- `backend/app/compute.py:138-170` - require_compute, ready_kinds, is_down_for
- `backend/app/core/errors.py:23-49` - DomainError and its status codes
- `.env.example:20` - REQUIRE_COMPUTE default
