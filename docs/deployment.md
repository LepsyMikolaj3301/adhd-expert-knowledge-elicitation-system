# Deploying: Render (two containers) + Neon (database)

```
browser --https--> Render "rag-frontend"  (nginx; serves the app, proxies /api/)
                        '--https--> Render "rag-backend"  (FastAPI)
                                         '--TLS, pooled--> Neon Postgres
```

The browser only talks to the frontend's address, so the session cookie is first-party and there is no
CORS. Everything deployment-specific is in `infra/` plus `render.yaml`:

| File | What |
|---|---|
| `infra/backend.Dockerfile` | production API image (no `--reload`, listens on Render's `PORT`, non-root) |
| `infra/frontend.Dockerfile` | production web image: build, then nginx |
| `render.yaml` | the two Render services (Blueprint) |
| `infra/.env.deploy.example` | settings the deploy script reads |
| `infra/deploy.sh` | migrate, deploy backend, deploy frontend, smoke test |

The development images stay `backend/Dockerfile` and `frontend/Dockerfile`.

## One-time setup

1. **Neon.** Create a project (pick a region next to Render's, e.g. Frankfurt for both). In *Connect*,
   copy two strings: the **pooled** one (host has `-pooler`) and the **direct** one (untick "Connection
   pooling"). The app schema needs no extensions.
2. **Render.** *New > Blueprint*, choose this repo, apply `render.yaml`. Then:
   - `rag-backend` > Environment: set `DATABASE_URL` to the **pooled** string.
   - Copy the backend's public URL (`https://rag-backend-xxxx.onrender.com`). In `rag-frontend` >
     Environment set `API_UPSTREAM_URL` to that URL (no trailing slash) and `API_HOST` to its host
     (`rag-backend-xxxx.onrender.com`).
   - On both services, *Settings > Deploy Hook*: copy the URL.
3. **Local settings.** `cp infra/.env.deploy.example infra/.env.deploy` and fill it in (it is gitignored).
4. **First data.** `infra/deploy.sh migrate`, then `infra/deploy.sh bootstrap` (creates the admin,
   asks for a password, imports the vignettes if `VIGNETTES_DIR` exists). These run from your machine
   against the direct Neon string, because the free Render tier has no shell.

## Every deploy

```bash
git push
infra/deploy.sh          # check, migrate, backend, frontend, smoke
```

Single steps: `infra/deploy.sh check | migrate | backend | frontend | smoke`. Render builds the commit
the script passes (`HEAD`, which must be pushed). Auto-deploy is off so the order is always:
migrate, backend, frontend.

- Migrations run before the new code starts, so keep each one compatible with the release still
  serving: add first, remove in a later release.
- The health wait cannot tell the old release from the new one while Render is still building, so
  it waits 20 s and then for three healthy answers in a row. If a build fails, Render keeps the old
  release running and the script may report success: check the Render dashboard for the deploy status.

## An answers-only round (branch `answers-only`)

For collecting the experts' answers to the vignettes and nothing else. With `ANSWERS_ONLY=true` (set in
`render.yaml`) the API has no reviews, knowledge base or home feed, and the web app offers only the
cases (expert) or vignettes, assignments and experts (admin). Nothing else changes: submitting still
stores the frozen answers in `app.submissions` and moves the case to `processing`, and the `process`
job waits in `app.jobs` because no worker runs. Nothing is classified, scrambled or rewritten, and the
schema is the one on `main`, so a snapshot of this database also restores under `main`'s code.

Later, on a local copy (below), start the worker (`python -m app.jobs.worker`) and the cases carry on
from `processing` exactly as they would have. Never point a worker at the Neon database from here.

### Setting it up

1. **Neon.** Create the project as **Postgres 16**, the major version of the local `pgvector/pgvector:pg16`
   image. `infra/gold.sh` dumps with that image's `pg_dump`, which refuses a newer server.
2. **Render.** *New > Blueprint*, pick the branch `answers-only`, then the steps of
   [One-time setup](#one-time-setup) (database URL, the frontend's two addresses, the deploy hooks).
3. **Settings.** `cp infra/.env.deploy.example infra/.env.deploy` and fill it in. Beyond the Neon and Render
   values, set `GOLD_DIR` (a folder outside the repository and outside Docker, e.g. `~/adhd-gold`),
   preferably `GOLD_MIRROR_DIR` (a second disk or a synced folder), and point `VIGNETTES_DIR` at the
   **real** vignettes: the default is the synthetic test set.
4. **Push and deploy.** `git push -u origin answers-only` (the branch carries `main`'s unpushed commits
   along), then `infra/deploy.sh` and `infra/deploy.sh bootstrap`. Run `infra/deploy.sh` from the dev
   container; it needs `uv` and `curl`.
5. **Vignettes.** Bootstrap imports them as drafts. In the app: publish the ones to use, then assign them
   to experts (*Vignettes*).
6. **Experts.** Add them on the *Experts* page. There is no e-mail: copy each expert's invite link and send
   it yourself. The page shows the link once; if it is lost, the same page issues a new one. Tell them
   the first page can take up to a minute to open (free tier), and that nothing is lost if it times
   out: the answers autosave.
7. **Rehearse before inviting anyone** (next section).

### Keeping the answers

The answers are the one thing that can't be recreated. `infra/gold.sh` runs on the host (WSL) where
docker compose runs, because `pg_dump` is not installed in the dev container:

```bash
docker compose up -d postgres        # the local server is only used for the checks
infra/gold.sh pull                   # dump Neon, prove the dump restores, write the answers as files
infra/gold.sh restore ~/adhd-gold/20261106T101500Z   # load a snapshot into a NEW local database
```

A snapshot is a folder `$GOLD_DIR/<UTC time>/`:

| File | What |
|---|---|
| `prod.dump` | `pg_dump -Fc` of the schemas `app` and `chips`. Includes the users (names, e-mails); leaves out login sessions and invite links |
| `submissions.jsonl` | one line per submitted case: the raw answers exactly as stored, the expert's pseudonym, and the vignette's text, version and hash |
| `drafts.jsonl` | answers not submitted yet |
| `manifest.txt` | time, migration version and the row count of every table |
| `SHA256SUMS` | checksums of the four files |

What it guarantees: Neon is only read (a read-only session); the dump is restored into a throwaway
database before the snapshot is accepted; the files are built in `<time>.partial` and renamed when all
checks pass; the finished folder is read-only; nothing here overwrites or deletes a snapshot; and it
exits with a warning if a table shrank on Neon after the dump, or if `app.submissions` has fewer rows
than in the previous snapshot. `restore` always makes a new database, `rag_gold_<time>`, and refuses if
it exists, so your development database (`rag`) is never touched. To use a restored copy:
`DATABASE_URL=postgresql://rag:rag@localhost:5432/rag_gold_<time>`.

What it does not do, and you must:

- **Run it.** Nothing runs it for you: do `pull` at the end of every day an expert may have answered, and
  before every `infra/deploy.sh migrate`.
- **Keep two copies.** Set `GOLD_MIRROR_DIR`, or copy `$GOLD_DIR` somewhere else by hand. A single disk
  is a single point of failure, and so is a folder inside WSL's virtual disk.
- **Protect them.** Snapshots hold names and e-mails. Don't commit them, e-mail them or put them in a
  shared folder. Use `submissions.jsonl` (pseudonyms only) for anything you share.
- **Keep Neon until it's safe to let go.** Don't delete the Neon project until two verified snapshots
  exist, one of them on the mirror. The free tier's own restore history is short and is not a backup.

### Rehearsal (do it once, before the first expert)

1. Add a test expert (tick *Test account (synthetic)*, so its answers can be told apart), answer a
   vignette as them and submit. The case should read *Submitted*, the side panel should have no
   *Reviews*, and `/reviews` should say the page isn't found.
2. `infra/gold.sh pull`. It must end with `done:` and no warning other than the missing mirror, if you
   haven't set one. The test answer must be in `submissions.jsonl`.
3. `infra/gold.sh restore <the snapshot folder>`, then check in the new database:
   `SELECT state, count(*) FROM app.assignments GROUP BY 1;` still says `processing`, and
   `SELECT count(*) FROM app.jobs WHERE status = 'queued';` equals the number of submissions.
4. `touch <snapshot>/x` must fail (read-only).

## Why two Neon strings

The pooled string goes through PgBouncer (transaction mode): right for the API, wrong for migrations
(session state, advisory locks). The backend notices a `-pooler` host and turns off asyncpg's
prepared-statement cache for it (`backend/app/core/db.py`), and converts Neon's libpq options
(`sslmode`, `channel_binding`) to what asyncpg accepts. Alembic uses `DATABASE_URL_UNPOOLED` when set
(the script sets `DATABASE_URL` to the direct string instead).

## Free-tier behaviour

Both Render services sleep after 15 minutes without traffic and Neon suspends its compute after 5, so
the first request after a pause can take 30 to 60 seconds (the frontend wakes, then the backend, then
the database). The backend can't be a private service on the free plan, which is why the frontend
reaches it by its public URL. On a paid plan make it a private service and set `API_UPSTREAM_URL` to
`http://<host>:<port>`, `API_HOST` to the host.

## Trying the images locally

```bash
docker build -f infra/backend.Dockerfile -t rag-backend .
docker run --rm -p 9000:9000 -e PORT=9000 -e DATABASE_URL='<a Neon dev branch, pooled>' rag-backend
curl localhost:9000/api/v1/health

docker compose --profile preview up -d --build frontend-preview   # http://localhost:8080
```

## Not covered yet

- The background worker (`python -m app.jobs.worker`). Its handlers are real now, but they call
  Ollama for the classifier (`CLASSIFIER_MODEL`) and bge-m3, which Render doesn't provide, so the
  worker needs a reachable Ollama (`OLLAMA_BASE_URL`) before it can be deployed there. A commented
  block in `render.yaml` is ready; Render workers need a paid plan. Migration `0003` also runs
  `CREATE EXTENSION vector` (Neon allows it) for the `chips` schema.
- nginx does not verify the backend's TLS certificate (`proxy_ssl_verify` is off).
- Ollama and S3 settings are only used by scripts, not by the API, so Render needs neither.
