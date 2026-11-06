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
the vignettes assigned to them, and can be asked to review colleagues' units.

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
| `building_units` | Background job: cuts units, asks the peers | System | `admin_review`, `peer_review`, `processing_failed` |
| `processing_failed` | The processing or unit job failed | Admin retries that job | `processing`, `building_units` |
| `admin_review` | Decision on each unit | Admin decides, asks peers (only if none were asked yet), or sends back | `ingesting`, `rejected`, `peer_review`, `expert_check` |
| `peer_review` | Decision on each unit | Peers decide; the admin may decide too, send back, or recall | `ingesting`, `rejected`, `admin_review`, `expert_check` |
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
5. **Route.** Every colleague who may review gets a review request at once (see *Who can review*).
   With none, the admin decides alone. Either way the admin sees the assignment in the queue.
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

Reviewers judge **knowledge units, not raw answers**, and for each one **approve, reject, or ask
for changes**. They can't edit units, which stay verbatim, except that chips are rendered as «the
first 8 words…» of their citation. The comment field of a decision exists in the API but has no
screen yet; asking for changes **requires** a comment (`comment_required`).

- **Asking for changes** means the unit could be right with another filing. The only things an
  author can change are which citations a sentence belongs to and each citation's direction, never
  the words. A peer's request goes to the admin like a rejection does. When the admin's own decision
  includes a request for changes, **the whole set goes back to the author** (`expert_check`),
  `review_round` goes up by one, the old units become `superseded` (history: the admin reads them
  with `GET /assignments/{id}/units?review_round=1`), and the peers' open requests close. The
  author reads the comments on `GET .../findings` (`feedback`: the unit, its text, the comment, and
  only whether a `reviewer` or the `admin` wrote it), corrects the filing, and approves. Units are
  cut again, numbered from 1 in the new round, and the colleagues who may review are asked again.
  Nothing from an earlier round is ever ingested.

- **Peers are asked automatically** when the units are built, with one approval required
  (`required_approvals` is 1). `POST /assignments/{id}/reviewers` can still ask for more, but only
  while nobody has been asked, which is the case only when no colleague was eligible then.
- **The admin can decide at any time**, in `admin_review` or `peer_review`. It is final, and closes
  the peers' open requests.
- **Peers:** when every unit has the required approvals and no rejections, the assignment moves
  on. Any rejection sends it back to the admin, who then decides every unit, seeing the peers'
  decisions and comments. The admin can also recall a stuck review. Peers are asked once per
  assignment.
- **A decision covers every unit in one call** (`decisions_incomplete` otherwise) and can't be
  changed afterwards. Each stores the hash of the text it was about, so if a unit's text changes, the
  old approval no longer counts.
- **Partial results:** rejected units stay out, approved ones are ingested. If the admin rejects
  every unit, the assignment ends as `rejected`.

**Who can review.** A peer must be an active expert and not the author, and must have **submitted
their own answers to that vignette first** (`reviewer_has_not_answered`; any version counts). So peer
review needs at least two experts on the vignette, and otherwise the admin decides alone. The
first expert to finish a vignette is therefore reviewed by the admin only, and each later one by
all who finished before. Reading a
colleague's answers would also contaminate any answer still to come, so someone with an unsubmitted
assignment on any version of the vignette can't review it (`reviewer_contaminated`), and someone who
was asked to review it can't later be assigned another version.

## Who sees what

| | Author | Peer | Admin |
|---|---|---|---|
| Vignette text | Yes | Yes | Yes |
| Hidden `design` block | No | No | Yes |
| Raw answers | Own | No | Read-only |
| Requests for changes | Comments by role only, never who | Own decision | All, with who |
| How they were filed (`findings`) | Own, correctable until approved | No | Read-only |
| Units | Own, with status | Text, and own decision | With all decisions |
| Who the author is | | No | Pseudonym |
| Who the reviewers are | No | No | Yes |
| Timeline | Actors as roles only | No | Full |

An unrelated expert gets a 404 for anything about someone else's assignment. Submissions and units
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
  reviews/         peer requests, unit decisions, who can review
  knowledge/       findings.py (sentences, citations, units: pure, no models), classifier.py
                   (the model call), embedding.py, ingest.py (writes `chips`), the units table
  audit/           append-only events
  jobs/            queue.py, worker.py (lease, heartbeat), handlers.py (prepare + record per job)
backend/migrations/  Alembic, manages only the `app` Postgres schema
```

Each feature has `router.py` (HTTP only), `schemas.py` (one view per audience), `models.py` and
`service.py` (rules and transactions; routers commit). The new code doesn't import
`app.elicitation` or `scripts/`: those keep working for the fixtures and experiments.

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

There is no sign-up. An admin creates a user with `POST /users`, and passes on the one-time link it
returns. The same link type resets a forgotten password (`POST /users/{id}/invite`). Email isn't
built yet. With `ENVIRONMENT=production` the session cookie is HTTPS-only, so production must be
served over HTTPS or logins won't stick. `COOKIE_SECURE=true` turns this on in other environments too.

API docs are at `/api/v1/docs`.

**After changing the API**, regenerate the frontend's types. A test fails until you do:

```bash
cd backend && python -m app.cli export-openapi --out ../frontend/openapi.json
cd ../frontend && npm run gen:api
```

**Tests:** `uv run pytest` uses a separate `rag_test` database (created automatically, or
`TEST_DATABASE_URL`), and is skipped if Postgres isn't reachable. `npm run test:unit` covers the
frontend.
