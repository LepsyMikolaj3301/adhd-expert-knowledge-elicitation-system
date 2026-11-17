# Deploying: one Azure VM, the models on your own PC

Step by step setup, with costs and limits: [azure-setup-guide.md](azure-setup-guide.md). This page is
the technical reference.

```
visitor --https--> Caddy :443  (certificate for <label>.<region>.cloudapp.azure.com)
                     '--> frontend (nginx: the built app, proxies /api/)
                             '--> rag-backend (FastAPI)  --+
                                  worker (python -m app.jobs.worker) --+--> postgres (pgvector)
                                                              |
                       Tailscale -----------------------------+--> your PC: Ollama :11434, LanguageTool :8010
```

Everything on the VM is one compose project, `infra/azure/docker-compose.yml`. The browser only
talks to the one address, so the session cookie is first-party and there is no CORS. Ollama and
LanguageTool (the GPU work) stay on the owner's PC; the VM reaches them over Tailscale at `PC_HOST`.

| File | What |
|---|---|
| `infra/backend.Dockerfile` | production API and worker image (non-root, no `--reload`) |
| `infra/frontend.Dockerfile` | production web image: build, then nginx |
| `infra/azure/docker-compose.yml` | caddy, frontend, rag-backend, worker, migrate, postgres, cli (profile `tools`) |
| `infra/azure/Caddyfile` | TLS for `${DOMAIN}`, proxies to the frontend |
| `infra/azure/env.example` | the VM's `.env` (domain, registry, PC address, passwords, models) |
| `infra/azure/deploy.sh` | on the VM: pull, migrate, restart, wait healthy |
| `infra/azure/setup-vm.sh` | first boot of the VM: swap, Docker, Tailscale, updates, backup job |
| `infra/azure/backup.sh` | daily `pg_dump`, 7 days kept |
| `.github/workflows/ci.yml`, `deploy.yml` | the checks, and the manual deploy |

The development images stay `backend/Dockerfile` and `frontend/Dockerfile`, and the root
`docker-compose.yml` is the PC and dev setup (Ollama, LanguageTool, MinIO, Postgres, dev container).

## The services and their limits

Sized for a 4 GB VM (B2s). The limits add up to about 2.2 GB; the rest is the OS, the page cache and the
2 GB swap file.

| Service | Memory limit | Notes |
|---|---|---|
| postgres | 768 MB | `shared_buffers=128MB`, `max_connections=30`; not published |
| rag-backend | 512 MB | one uvicorn process, trusts `X-Forwarded-*` (it sits behind nginx and Caddy) |
| worker | 512 MB | the same image; polls the `jobs` table, so it also works across restarts |
| migrate | 384 MB | one-shot, `alembic upgrade head`; the API and worker wait for it |
| frontend | 64 MB | nginx |
| caddy | 64 MB | ports 80 and 443 only |

Logs rotate (3 files of 10 MB per container) so the 30 GB disk does not fill up. If the worker is
killed for memory on a big ingestion, raise its limit first.

## When the PC is not set up

`REQUIRE_COMPUTE=true` (set by the compose file) turns on `backend/app/compute.py`. Before a person
moves an assignment into a step that queues a job, `transition()` in
`backend/app/assignments/state_machine.py` asks the PC (3 second timeout):

| Job queued | Needs |
|---|---|
| proofread (author submits, or an admin retries) | Ollama with the classifier and enhancement models, LanguageTool |
| ingest (an admin retries an ingestion) | Ollama with the embedding model of `config/indexing.yaml` |
| process (admin approves the answers) | nothing: it cuts text into units with no model |

If something is missing the request answers **503 `compute_unavailable`** (`details.missing` lists
`ollama`, `languagetool` or `model <name>`), before anything is changed: the assignment keeps its state
and no job is queued. The worker's own moves are not checked, and neither is the BM25 refit (no model).
The admin's test search keeps its own 503, `embedding_unavailable`.

Without this check, proofreading would skip an unreachable LanguageTool or enhancement model and give
the author an unchecked answer (`app/proofread/pipeline.py`). A job that is already queued when the PC
goes away still follows the worker's rules: three attempts, then failed, retryable by an admin.

## CI/CD

Nothing runs by itself: it is a one-person repository that works on main.

- **CI** (`ci.yml`, Actions > CI > Run workflow): ruff, `ty`, the tests that need no database
  (`-m "not integration"`), then the frontend lint, type-check, tests and build. CI starts no
  Postgres: everything marked `integration` (`tests/api`, `tests/integration`, the package
  integration tests) runs locally, against the compose Postgres: `uv run pytest -m integration`.
  Run that before a deploy that touches the backend.
- **Deploy** (`deploy.yml`, Actions > Deploy > Run workflow), with two switches: *run CI first* and
  *deploy to the VM*. It builds both images for `linux/amd64`, pushes them to GHCR
  (`ghcr.io/<owner>/<repo>/backend|frontend`, tags `sha-<short>` and `latest`), joins the tailnet as
  `tag:ci`, copies `infra/azure/` to `/opt/rag` over Tailscale SSH, runs `deploy.sh sha-<short>` and
  smoke-tests `/api/v1/health` and `/` through Caddy. The VM has no open SSH port.

Migrations run before the new code starts (`migrate` service), so keep each one compatible with the
release still serving: add first, remove in a later release.

## Backups and restore

`backup.sh` runs from `/etc/cron.daily`, which anacron also runs after a boot, so a VM that is off at
night still gets its dump. Dumps are in `/var/backups/rag` (custom format, 7 days). Restore with
`pg_restore --clean --if-exists` (see the guide, step 11). They are on the same disk as the database:
copy one home now and then.

## Not covered

- **High availability.** One VM, one database container. Fine for a demo; a VM that is off is a site that is off.
- **The certificate needs ports 80 and 443 open** and the VM on. A static IP keeps the name, and the
  certificate is kept in a volume.
- **nginx talks plain HTTP to the backend** on the compose network, so no certificate checks inside the VM.
- **S3 settings** (MinIO) are only used by scripts, not by the API, so the VM has none.
- **The admin's test search** embeds what the admin types through the PC's Ollama; with the PC off it
  answers 503 `embedding_unavailable`.
