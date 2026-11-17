# Azure for Students deployment, AI compute on the owner's PC

Date: 2026-11-17. Size: small-to-medium (compose file, proxy config, one backend check, one doc).

## Intent and why

Run the app for outside users on an Azure for Students VM, cheaply and with a plain link, while the
GPU work (Ollama: classifier, enhancement, bge-m3 embeddings; LanguageTool) stays on the owner's PC.
The container structure of `docker-compose.yml` stays: frontend, backend, worker, migrate, postgres.
If the PC is not reachable, the backend must fail loudly instead of quietly degrading.

## Goals

- Users open one HTTPS link and use the frontend; logins work (production forces secure cookies).
- The VM's backend and worker call Ollama and LanguageTool on the owner's PC over a private tunnel.
- Requests that would queue a job fail with 503 `compute_unavailable` when the PC is unreachable.

## Non-goals / anti-goals

- No custom domain, no Cloudflare, no new worker protocol (the worker still polls the `jobs` table).
- Ollama and LanguageTool are never exposed on the public internet (Ollama has no authentication).
- No change to retry behaviour of jobs already queued (3 attempts, then failed).
- No Render or Neon: their files, docs and code are removed (`docs/deployment.md` now describes Azure).

## Approaches considered

1. **Tailscale between VM and PC (chosen).** Free, no domain, private, no proxy timeout, no extra
   auth code. Cost: install Tailscale on both machines; on WSL2 the PC side needs Tailscale inside
   WSL or mirrored networking so published ports are reachable on the Tailscale IP.
2. Cloudflare Tunnel on the PC. URL-based, but needs a domain on Cloudflare, an Access service
   token sent as headers from four call sites, and the free plan cuts requests at ~100 s (524),
   which cold model loads can exceed. Rejected: owner does not want a domain.
3. Public port on the PC with an allow-list. Rejected: home IP changes, Ollama unauthenticated.

The VM's public entry is Caddy on Azure's free DNS label
(`<name>.<region>.cloudapp.azure.com`), which gets a Let's Encrypt certificate with no domain.

## Design

**VM (`docker-compose.azure.yml`, new, standalone):**
`caddy` (80/443, auto-TLS, proxies to `frontend`), `frontend` (`infra/frontend.Dockerfile`,
`API_UPSTREAM_URL=http://rag-backend:8000`), `rag-backend` and `worker` (`infra/backend.Dockerfile`;
worker overrides command to `python -m app.jobs.worker`), `migrate` (`alembic upgrade head`),
`postgres` (`pgvector/pgvector:pg16`, port not published, init.sql mounted). `OLLAMA_BASE_URL` and
`LANGUAGETOOL_URL` point at the PC's Tailscale IP (`http://100.x.x.x:11434`, `:8010`), set in a
`.env` on the VM. Not included: ollama, languagetool, minio, pgadmin, dev, playwright.
Tailscale runs on the VM host (containers reach `100.x` through the host's routing).

**Azure:** VM with at least 4 GB RAM (e.g. B2s, subject to what the subscription allows), static
public IP with a DNS label, NSG: 80/443 from anywhere, 22 from the owner's IP only. A nightly
`pg_dump` cron on the VM.

**PC:** Tailscale installed; `docker compose up -d ollama languagetool` with the models pulled and a
long `OLLAMA_KEEP_ALIVE`; ports 11434 and 8010 reachable on the Tailscale interface only (firewall).

**Backend check (code):** `require_compute()` in the backend: GET Ollama `/api/tags` and
LanguageTool `/v2/languages` with a short timeout (~3 s), raising
`DomainError("compute_unavailable", ..., 503)`. Added to the endpoints whose state transition
enqueues a job (`JOB_ON_ENTRY` in `app/assignments/state_machine.py`, and the knowledge refit
enqueue in `app/knowledge/router.py`). The exact endpoint list is for the plan to determine. A
test replaces the check, the way tests replace `embed_texts`.

**Docs:** `docs/deployment-azure.md`: Azure steps, Tailscale on both ends, `.env` for the VM, first
migration and admin bootstrap (through the `cli` compose profile), how to update (`git pull && docker compose -f docker-compose.azure.yml up -d --build`).

## Left to the builder

Caddyfile details, which endpoints get the check, whether the check is cached for a few seconds,
exact firewall commands for the PC, log/restart settings.

## Known risks

- PC offline mid-job: classifier retries then fails; proofreading skips an unreachable pass
  (existing behaviour, deliberately unchanged).
- Student credit and region/size limits vary by subscription; verify when creating the VM.

## Revisions after planning (same day)

- **Uptime and budget:** B2s, started only when needed (about $6/month while stopped). Budget alerts,
  auto-shutdown and the stop/start routine are in `docs/azure-setup-guide.md`.
- **Neon removed from the code too:** pooler detection, sslmode rewriting, `DATABASE_URL_UNPOOLED`.
- **CI/CD:** `.github/workflows/ci.yml` (manual) and `deploy.yml` (manual; skippable tests and deploy).
  Images are built on GitHub, pushed to GHCR and pulled by the VM. The runner reaches the VM over
  Tailscale SSH, so port 22 is closed. Files: `infra/azure/`.
- **What the check needs, per job** (`backend/app/compute.py`): proofread = classifier and enhancement
  models + LanguageTool; ingest = the embedding model; process = nothing (it calls no model).
  Approving (process) also checks what the ingestion after it needs. The API's check sits in
  `transition()`, reads a probe that a background task renews every 10 s, and skips the worker's
  own (SYSTEM) moves. The worker claims only jobs whose machine is up, and a job that fails while
  the PC is down goes back to the queue without using an attempt.
- **PC side:** the root compose publishes Ollama and LanguageTool on `127.0.0.1`; `tailscale serve
  --tcp` forwards the tailnet ports to them. (A bind to the Tailscale IP failed when Docker started
  before tailscaled, and can't work under Docker Desktop.)
