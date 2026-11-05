# Backend workflow

How the expert and admin application works: who does what to an answer, from assignment to the
knowledge base. For the answering screen, see [frontend-vignettes.md](frontend-vignettes.md).

Processing and ingestion are **stubs** for now: `backend/app/jobs/handlers.py` passes straight
through, builds one verbatim unit per answered open question, and marks approved units as ingested.
Nothing is written to the RAG tables yet, so `ingested` is only a status. GDPR erasure isn't built
either. It will have two levels: one unit, or a whole submission or expert with the answers.

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
| `processing` | Background job | System | `expert_check`, `processing_failed` |
| `expert_check` | Waits as long as needed | Expert completes or skips, admin skips | `building_units` |
| `building_units` | Background job | System | `admin_review`, `processing_failed` |
| `processing_failed` | The processing or unit job failed | Admin retries that job | `processing`, `building_units` |
| `admin_review` | Decision on each unit | Admin decides or asks peers | `ingesting`, `rejected`, `peer_review` |
| `peer_review` | Decision on each unit | Peers decide, admin recalls | `ingesting`, `admin_review` |
| `ingesting` | Background job, approved units only | System | `ingested`, `ingestion_failed` |
| `ingestion_failed` | The ingestion job failed | Admin retries | `ingesting` |
| `ingested`, `rejected`, `cancelled` | Finished | Nobody | |

The rules live in one table, `TRANSITIONS` in `backend/app/assignments/state_machine.py`, and
`transition()` there is the only code that changes a state. In one transaction, it updates the state,
writes the audit event and queues the next job. Every response carries `allowed_actions`, so the
frontend doesn't need its own copy of the rules.

**Nothing reopens after submission.** A submission is immutable, and a database trigger enforces
that. The expert check will be able to correct groupings and direction toggles once processing
exists, but never the answer text.

## Answering

Every vignette asks Q1–Q6, with a what-if for Q4 that its author must write. Q1–Q3 form a gate.
Q4–Q6, and the what-if inside Q4, are not sent to the browser until
`POST /assignments/{id}/pass-gate`, and after that the Q1–Q3 answers and the citations made so far
can't change. Citations added after the gate stay editable until submitting, and the number that were
locked is frozen with the submission. Drafts save with a
version number, so a stale tab gets `draft_conflict` instead of overwriting newer text.

**Every question asked must be properly answered.** Saving a draft allows anything, but passing the
gate and submitting don't. Blank answers fail, and so do answers below the minimum number of different
words, so "test test test" counts as one (`answer_too_short`). This only filters out empty and filler
answers: it can't judge quality.

| Answer | Minimum different words | Checked at |
|---|---|---|
| Q1 | 15 | The gate |
| Q2, Q3 | 10 | The gate |
| Q4 hypothesis | 3 | Submit |
| Q4 why (when the shift isn't 0) | 5 | Submit |
| Q5 | 10 | Submit |

Chips (`⟦hN⟧`) don't count as words. Every citation needs a direction, and every chip a citation:
those made before the gate are checked there, the rest at submit.

Q1–Q3 are checked at the gate because they can't be corrected after it. The minimums are in
`backend/app/vignettes/questions.py`, and the API sends them with each question, for a counter on the
screen.

Submitting freezes a trimmed copy of the saved draft and queues processing. It returns immediately:
the expert can close the page, and the assignment appears as ready to check once the job is done.

## Review

Reviewers judge **knowledge units, not raw answers**, and approve or reject each one. They can't
edit units, which stay verbatim, except that chips are rendered as «the first 8 words…» of their
citation.

- **One admin approval is enough.** The admin either decides every unit, or sends them to peers
  first. These are the only two paths.
- **Peers:** the number of required approvals is set per request, at least 1. When every unit has
  that many and no rejections, the assignment moves on. Any rejection sends it back to the admin,
  who then decides every unit, seeing the peers' decisions and comments. The admin can also recall a
  stuck review. Peers can only be asked once per assignment.
- **A decision covers every unit in one call** (`decisions_incomplete` otherwise) and can't be
  changed afterwards. Each stores the hash of the text it was about, so if a unit's text changes, the
  old approval no longer counts.
- **Partial results:** rejected units stay out, approved ones are ingested. If the admin rejects
  every unit, the assignment ends as `rejected`.

**Who can review.** A peer must be an active expert and not the author, and must have **submitted
their own answers to that vignette first** (`reviewer_has_not_answered`; any version counts). So peer
review needs at least two experts on the vignette, and otherwise the admin decides alone. Reading a
colleague's answers would also contaminate any answer still to come, so someone with an unsubmitted
assignment on any version of the vignette can't review it (`reviewer_contaminated`), and someone who
was asked to review it can't later be assigned another version.

## Who sees what

| | Author | Peer | Admin |
|---|---|---|---|
| Vignette text | Yes | Yes | Yes |
| Hidden `design` block | No | No | Yes |
| Raw answers | Own | No | Read-only |
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
  assignments/     states.py and state_machine.py (the workflow), answers.py (the answer rules)
  reviews/         peer requests, unit decisions, who can review
  knowledge/       the units table, and the admin's list of units
  audit/           append-only events
  jobs/            queue.py, worker.py, handlers.py (the stubs to replace)
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
