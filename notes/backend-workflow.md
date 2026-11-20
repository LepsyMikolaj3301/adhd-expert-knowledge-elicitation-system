# Backend workflow

How the expert and admin application works: who does what to an answer, from assignment to the
knowledge base. For the answering screen, see [frontend-vignettes.md](frontend-vignettes.md).

A submitted answer goes through a pipeline of background jobs, described in
[From answer to knowledge](#from-answer-to-knowledge): its sentences are filed under the expert's
citations, the expert checks that, units are cut and reviewed, and the approved ones are embedded
into the RAG tables (schema `chips`). Nothing reads those tables at query time yet. GDPR erasure
isn't built. It will have two levels: one unit, or a whole submission or expert with the answers.

## Roles

There are two roles, set per user. **Admins** are application users, not developers. They write
vignettes, invite and assign experts, and decide what enters the knowledge base. **Experts** answer
the vignettes assigned to them, and read, discuss and vote on colleagues' units.

An assignment is one expert on one vignette version, and holds the workflow state. One version can
go to many experts. A vignette itself only has `draft → published → retired`, and only `published`
versions can be assigned.

## States

| State | What happens | Who acts | Next |
|---|---|---|---|
| `assigned` | Waiting for the expert | Expert starts, admin cancels | `in_progress`, `cancelled` |
| `in_progress` | Answering, autosaved | Expert submits, admin cancels | `processing`, `cancelled` |
| `processing` | Background job: files the sentences | System | `expert_check`, `processing_failed` |
| `expert_check` | Expert reads the filing, may correct it. Waits as long as needed. Entered again, with the reviewers' comments, when the admin sends units back | Expert completes or skips, admin skips | `building_units` |
| `building_units` | Background job: cuts units | System | `peer_review`, `processing_failed` |
| `processing_failed` | The processing or unit job failed | Admin retries that job | `processing`, `building_units` |
| `peer_review` | Open review: colleagues read, discuss and vote; only the admin decides on each unit | Everyone comments, reviewers vote, the admin decides or sends back | `ingesting`, `rejected`, `expert_check` |
| `ingesting` | Background job: embeds the approved units | System | `ingested`, `ingestion_failed` |
| `ingestion_failed` | The ingestion job failed | Admin retries | `ingesting` |
| `ingested`, `rejected`, `cancelled` | Finished | Nobody | |

The rules live in one table, `TRANSITIONS` in `backend/app/assignments/state_machine.py`, and
`transition()` there is the only code that changes a state. In one transaction, it updates the state,
writes the audit event and queues the next job. Every response carries `allowed_actions`, so the
frontend doesn't need its own copy of the rules.

**Nothing reopens after submission.** A submission is immutable, and a database trigger enforces
that. The expert check can correct which citations a sentence belongs to and each citation's
direction, but never the answer text.

## Answering

Every vignette asks Q1–Q6, with a what-if for Q4 that its author must write. Q1–Q3 form a gate.
Q4–Q6, and the what-if inside Q4, are not sent to the browser until
`POST /assignments/{id}/pass-gate`, and after that the Q1–Q3 answers and the citations made so far
can't change. Citations added after the gate stay editable until submitting, and the number that were
locked is frozen with the submission. Drafts save with a
version number, so a stale tab gets `draft_conflict` instead of overwriting newer text.

**Every question asked must be answered.** Saving a draft allows anything, but passing the gate and
submitting don't: blank answers fail (`gate_not_passed`, `empty_answer`). Length is not checked: an
expert may answer as briefly as they like.

Every citation needs a direction, and every chip a citation:
those made before the gate are checked there, the rest at submit.

Q1–Q3 are checked at the gate because they can't be corrected after it.

Submitting freezes a trimmed copy of the saved draft and queues processing. It returns immediately:
the expert can close the page, and the assignment appears as ready to check once the job is done.

## From answer to knowledge

The design and its reasons are in [new-chips-knowledge.md](new-chips-knowledge.md), the test that
backed it in [chips-test-findings.md](chips-test-findings.md). This is what the application does,
one job at a time. Every job has a slow part that runs with no transaction and no lock (the model
calls) and a short part that records the result under the assignment's lock. A heartbeat renews the
job's lease while it runs, so a long job isn't taken over, and a crashed one still is.

1. **Submit.** The frozen submission is saved and a `process` job is queued.
2. **Process** (`processing`). The open answers (Q1, Q2, Q3, Q5; not Q4's why, not the rating) are
   cut into sentences. A sentence is filed under the citation it contains, or one it quotes; a
   quote that matches the vignette but no citation becomes an *implicit* citation. Sentences still
   unfiled go to a local model (`CLASSIFIER_MODEL`, default `qwen3.5:9b`) that returns **ids only**,
   never text: citation ids, `case` (about the text as a whole) or `prev` (continues the previous
   sentence). A bad reply is asked again up to three times with a new seed, and a sentence it still
   can't file goes under `case`. If the model can't be reached, the job fails and retries instead of
   quietly filing everything under `case`. Then two checks only flag: a citation nobody wrote about,
   and a direction that contradicts the sentences about it ("more likely … than" under `toward`).
   Saved in `answer_findings`, apart from the immutable submission.
3. **Expert check** (`expert_check`). `GET /assignments/{id}/findings` shows each sentence with the
   citations it was filed under and who filed it (chip, quote, model, you), plus the flags.
   `PUT` corrects it, with a version number like drafts (`findings_conflict`): which citations a
   sentence belongs to (one or more, or `case`) and each citation's direction. Corrections are
   logged as ids and kinds, never text. Then the expert approves (`expert-check/complete`) or skips.
4. **Build units** (`building_units`). One **fragment unit** per citation that has sentences
   (everything said about it, from every answer) and one **case unit**. Citations cited together
   become each other's `context`. A unit stores what reviewers read (`text`: its sentences verbatim,
   chips as «short quotes») and the two texts that will be embedded: `embed_text` (a header and
   the sentences) and `embed_text_combined` (the same with the patient's words). Its
   `content_hash` covers both, so an approval is for exactly what gets embedded.
5. **Open the review.** The assignment goes to `peer_review`. Nobody is asked: every colleague who
   may read it sees it in their list (see *Who can read*).
6. **Review.** See below. If the admin asks for changes, the units are history and the author is
   back at step 3 (a new *review round*); steps 3 to 6 repeat on the corrected filing.
7. **Ingest** (`ingesting`). Only approved units. They are embedded with bge-m3 (the units' two
   texts, and the patient's words of each citation), then in one transaction the assignment's rows
   in `chips` are replaced and BM25 is refitted over the whole schema. If anything fails, `chips`
   is untouched. The stored `document` is cut down to the approved units' sentences and citations:
   what was rejected is not in `chips` at all (a sentence two units share stays if either is
   approved). Review events hold ids and kinds, never words.

**Models.** The worker calls Ollama for the classifier and for bge-m3, so both must be pulled
(`ollama pull qwen3.5:9b`, `ollama pull bge-m3`). Settings: `CLASSIFIER_MODEL`, `OLLAMA_BASE_URL`,
`OLLAMA_REQUEST_TIMEOUT`. The worker also reads `prompts/` and `config/indexing.yaml`, next to
`backend/` (`PROJECT_ROOT` overrides where).

**The `chips` schema** is created by migration `0003` (it needs the pgvector extension) and is where
approved answers live. The earlier synthetic experiment data was taken out of it and is in
`data/backup/chips_synthetic_2026-11-05/`; `scripts/db/chips_backup.py restore` puts it back into
empty tables. `scripts/db/load_chips_pg.py` now loads experiment data into `chips_eval` and refuses
`chips`. Removing an answer from the knowledge base by hand isn't built: deleting the session's row
in `chips.elicitation_sessions` removes everything under it.

**To review: the structure of units.** See "To review: the unit structure" in
[new-chips-knowledge.md](new-chips-knowledge.md); the code carries `TODO(unit-structure)`.

## Review

A review is open: the units of a submission are read, discussed and voted on by colleagues, and
**only the admin closes it**. Reviewers judge **knowledge units, not raw answers**. They can't edit
units, which stay verbatim, except that chips are rendered as «the first 8 words…» of their citation.

- **Reading is explicit.** A reviewer opens a review (`POST /assignments/{id}/review/open`, 204, safe
  to repeat) before any of its text is sent. Until then every other route answers `409
  review_not_opened`, even `GET /assignments/{id}`, because the vignette text is also reading. The
  call is recorded (`review_participants`, audit event `review_opened`), and from then on the reader
  can't be assigned that vignette (`reviewer_contaminated`). The author and the admin need not open
  anything.
- **Discussion.** `POST /assignments/{id}/units/{unit_id}/comments` with `body` (1 to 5,000
  characters after trimming), an optional `parent_id` and an optional `stance`. Everyone in the
  review may comment: the reviewers, the author and the admin. Only reviewers take a `stance`
  (`support`, `challenge`, `question`; `stance_not_allowed` otherwise), because the author taking a
  side on their own work would be a vote for it. Replies are one level deep: `parent_id` must be a
  top-level comment on the same unit (`invalid_parent`). Comments can't be edited or deleted:
  decisions rest on them. They are read with the units (`GET /assignments/{id}/units`, each unit has
  `comments`).
- **Vote.** `PUT /assignments/{id}/vote` with `vote` (`accept` or `decline`) and the `review_round`
  the reviewer was reading, for the whole submission. One per reviewer and round, changeable until
  the review closes. `GET /assignments/{id}/votes` has the tally and who voted what. A vote is
  **advice**: it never moves the assignment, whatever the numbers. The author and the admin don't
  vote (403). A vote for a round that has since been cut again is refused (`stale_round`).
- **Closed means closed.** Comments and votes need `peer_review` (`review_closed` otherwise). They
  take the assignment lock, so one can't slip in beside the admin's decision.
- **The admin decides.** `POST /assignments/{id}/unit-decisions` covers every unit in one call
  (`decisions_incomplete` otherwise) with approve, reject or request changes, and can't be changed
  afterwards. Partial results work: rejected units stay out and approved ones are ingested; if
  every unit is rejected the assignment ends as `rejected`. Each decision stores the hash of the
  text it was about. The admin can decide at any time, without waiting for votes.
- **Asking for changes** means the unit could be right with another filing. The only things an
  author can change are which citations a sentence belongs to and each citation's direction, never
  the words, and a comment is required (`comment_required`). When any decision asks for changes,
  **the whole set goes back to the author** (`expert_check`), `review_round` goes up by one, and the
  old units become `superseded`. The admin and the author can read them, with their discussion, by
  `GET /assignments/{id}/units?review_round=1`. The author reads the admin's comments on
  `GET .../findings` (`feedback`), corrects the filing, and approves. Units are cut again, numbered
  from 1, and the new round starts with no comments or votes. Nothing from an earlier round is
  ever ingested.
- **The lists.** `GET /reviews?status=open|closed` has the submissions a person can follow, each
  with its tally, comment count and `my_vote`: for an expert their own and every one they may read,
  for the admin all. Open means the admin has yet to decide.

**Who can read.** Every active expert, except the author and anyone who still has to answer the
vignette themselves (an `assigned` or `in_progress` assignment on any version of it): what they read
would colour their own answer. This is checked when someone asks, not when the units are cut, so an
expert who joins later, or finishes later, sees the review too. The first expert to finish a vignette
is therefore read by everyone not still answering, not only by the admin. Nobody else gets more than
a 404.

## Home

`GET /me/home` has what the home page shows, computed when read from the workflow's own records:

- `next_up`: up to 5 of the viewer's cases to do (an expert's `assigned`, `in_progress` and
  `expert_check`; for the admin the failed jobs), most recently changed first, with `next_up_total`.
  Each has an `action` (`start`, `continue`, `check`, `retry`) chosen by the server.
- `reviews_waiting`: up to 5 open reviews the viewer hasn't voted on (every open one for the admin).
- `recent_reviews`: up to 10 reviews, open and closed, newest first.
- `activity`: up to 30 changes that concern the viewer, newest first, each `unread` if newer than
  the last time they looked. A person's own actions are never news to them.

  | `kind` | Reaches | From |
  |---|---|---|
  | `case_assigned`, `check_ready` | The author | the audit trail |
  | `review_opened` | Whoever may read it, and the admin | the units being built |
  | `review_closed` (`accepted`, `rejected`, `sent_back`) | The author and those who opened it | the admin's decision |
  | `comment_on_mine` | The author | a comment on their units |
  | `reply` | Anyone in the thread | a reply in a thread they wrote in |
  | `job_failed` | The admin | a failed job |

`POST /me/activity/seen` (204) marks it read; give `until`, the time of the newest item the page
showed, so that what arrived while it loaded stays unread. The mark never moves back or ahead of now.
Excerpts are the first 140 characters of a comment. Audit events never hold comment text.

## Who sees what

| | Author | Reviewer | Admin |
|---|---|---|---|
| Vignette text | Yes | Yes, after opening | Yes |
| Hidden `design` block | No | No | Yes |
| Raw answers | Own | No | Read-only |
| Requests for changes | Comments by role only, never who | No | All, with who |
| How they were filed (`findings`) | Own, correctable until approved | No | Read-only |
| Units | Own, with status, and earlier rounds | Text, after opening | With the admin's decisions |
| Comments | All, reviewers by pseudonym | All, other reviewers by pseudonym | All, everyone by pseudonym |
| Votes | Tally and who voted what | Tally and who voted what | Tally and who voted what |
| Who the author is | | No | Pseudonym |
| Who a reviewer is | By pseudonym, in comments and votes | By pseudonym | By pseudonym |
| Timeline | Actors as roles only; the discussion is left out | No | Full |

Reviewers are known to each other and to the author only by pseudonym (`E03`), never by email or
user id. The author and the admin appear in a discussion as a role, except to the admin.

Someone who may not read an assignment gets a 404 for anything about it. Submissions and units
carry the pseudonym (`E01`), never the email. Audit events, job errors and the application's logs
never hold answer text: when something fails, the logs get the stack and the error type, without the
error's message, because Postgres quotes row data in its messages.

## Layout

```
backend/app/
  core/            database session, error format, password and token helpers
  auth/ users/     sessions, invites, require_role(), user accounts
  vignettes/       versions, publishing, the question wording
  assignments/     states.py and state_machine.py (the workflow), answers.py (the answer rules),
                   check.py (the expert check)
  reviews/         access.py (who may read), comments, votes, the admin's unit decisions
  home/            what the home page shows: next up, reviews waiting, activity
  knowledge/       findings.py (sentences, citations, units: pure, no models), classifier.py
                   (the model call), embedding.py, ingest.py (writes `chips`), the units table
  audit/           append-only events
  jobs/            queue.py, worker.py (lease, heartbeat), handlers.py (prepare + record per job)
backend/migrations/  Alembic, manages only the `app` Postgres schema
```

Each feature has `router.py` (HTTP only), `schemas.py` (one view per audience), `models.py` and
`service.py` (rules and transactions; routers commit). The backend doesn't import
`scripts/`: the fixture schema, unit builder and experiments live there.

## Running it

```bash
# With Docker: Postgres, migrations, API on :8000 and the worker.
docker compose --profile app up

# Or by hand, from backend/.
alembic upgrade head
uvicorn app.main:app --reload
python -m app.jobs.worker

# Create the first admin (asks for the password).
python -m app.cli create-admin --email you@example.com --name "Your Name"
# Reserved domains such as .local and .test are refused, here and at login.

# Load ready-made vignette files as drafts (all or nothing; codes that exist are skipped).
# Each needs a what-if, given in a JSON file {"V001": "the writer ..."}. Publish them afterwards.
python -m app.cli import-vignettes --dir ../data/fixtures_chips/synthetic/silver/vignettes \
  --whatifs ../scripts/elicitation/chip_whatifs.json --admin-email you@example.com

# Frontend: http://localhost:5173 proxies /api to the backend.
cd frontend && npm run dev
```

There is no sign-up. An admin creates a user with `POST /users` (`GET /users` says who still has an
`invite_pending`), and passes on the one-time link it returns. The same link type resets a forgotten password (`POST /users/{id}/invite`). Email isn't
built yet. With `ENVIRONMENT=production` the session cookie is HTTPS-only, so production must be
served over HTTPS or logins won't stick. `COOKIE_SECURE=true` turns this on in other environments too.

API docs are at `/api/v1/docs`.

**After changing the API**, regenerate the frontend's types. A test fails until you do:

```bash
cd backend && python -m app.cli export-openapi --out ../frontend/openapi.json
cd ../frontend && npm run gen:api
```

**Tests:** `uv run pytest` gives each run its own database, `rag_<pid>_test` (created and dropped
automatically; or `TEST_DATABASE_URL`), and is skipped if Postgres isn't reachable. `npm run test:unit` covers the
frontend.

| Folder | What | Needs |
|---|---|---|
| `tests/unit/` | Pure backend logic: answer rules, error helpers, security, Ollama clients, prompts, vignette import, search helpers, job tables | nothing |
| `tests/scripts/` | The scripts the silver data came from (chip findings, fixture builders, judgments) | nothing |
| `tests/*.py` | Classifier, links, proofreading, findings, state machine, retrieval metrics | nothing |
| `tests/api/` | The API end to end, one real database per test run (all marked `integration`) | Postgres |
| `tests/integration/` | Retrieval-quality regression on the frozen silver snapshot (marked `integration`, `regression`) | Postgres |
| `packages/*/tests/` | The two packages; `integration/` runs the retrievers on a V001 example and on the silver snapshot | Postgres for `integration/` |

```bash
uv run pytest -m "not integration"                      # fast, no database (about 20 s)
uv run pytest -m "not integration" --cov --cov-report=term-missing
uv run pytest tests/api                                 # the API, about 10 minutes
uv run pytest -m regression -s                          # retrieval quality, prints the table
```

Coverage when this was written (2026-11-16; statements and branches of `backend/app` and the two
packages, frontend `src/`): everything with Postgres **89%**, `-m "not integration"` alone **69%**,
frontend **91% statements, 82% branches** (`npm run test:cov`). Two specs depend on timing:
`answerView.spec` "follows what is typed…" and `intro.spec` "goes on to the case…" fail when the
machine is busy, which is why `test:cov` uses two workers.

**The silver snapshot** (`tests/fixtures/retrieval_silver/`, committed, about 2 MB) is the silver
units with their real bge-m3 vectors, the 40 questions with their original and pooled labels, and the
bge-m3 vector of every text the tests send as a query, so no test calls a model. Rebuild it after the
units or the questions change (needs `data/` and Ollama with bge-m3):

```bash
uv run python scripts/db/chips_snapshot.py freeze     # rewrites tables.json, vectors.npz, queries.json
uv run python scripts/db/chips_snapshot.py check      # consistent?
UPDATE_RETRIEVAL_BASELINE=1 uv run pytest -m regression -s   # accept the new scores as the baseline
```

`tests/integration/test_retrieval_regression.py` runs the package's retrievers on it and scores them
with `scripts/rag/expert_metrics.py` (recall@k, hit@k, MRR, nDCG, token-budget recall, the ceiling).
Without an oracle it runs the retrievers as the application does; with one it reads the labels'
ceiling (the best any four units could reach) and restricts the search to the vignettes the labelled
claims come from. A metric falling more than 0.02 below `baseline.json` fails the run.

**Many experts on one vignette.** The silver data has only two experts per vignette, and their
answers are alike but not near-duplicates (cosine 0.70-0.90), so it cannot show a top k that fills
with one vignette's answers. `chips_snapshot.crowded` adds synthetic copies of every expert (same
words, vectors moved a little), and `packages/expert-knowledge-rag/tests/integration/
test_crowded_vignette.py` runs the retrievers on that: down-weighting stops a repeated whole-case
answer from taking the places, but the same fragment said by many experts still does (a strict
`xfail` records it). Real answers from four or more experts on the same vignettes would replace the
copies; until then those tests show mechanics, never quality.

`tests/fixtures/silver_chips/` is a committed copy of the silver chip documents, vignettes and the
platform seed that `tests/api/test_api_silver_workflow.py` and `test_cli.py` use.
