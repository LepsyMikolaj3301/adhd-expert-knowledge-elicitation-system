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
- S3 settings are only used by scripts, not by the API, so Render needs none.
- The API needs Ollama for one thing: the admin's test search (Knowledge base > Test search)
  embeds what the admin types with bge-m3. Without a reachable `OLLAMA_BASE_URL` that search
  answers 503 `embedding_unavailable` and says so; the list of units and everything else work.
  The search also reads `chips` through its own connection to `DATABASE_URL` (the pooled Neon
  URL works: prepared statements are off).
