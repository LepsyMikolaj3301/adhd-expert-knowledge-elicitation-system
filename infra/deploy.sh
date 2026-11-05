#!/usr/bin/env bash
# Deploys the app: Neon (database migrations), then the Render backend, then the Render frontend.
#
#   infra/deploy.sh [all]     check, migrate, backend, frontend, smoke   (default)
#   infra/deploy.sh check     validate settings and git state, change nothing
#   infra/deploy.sh migrate   alembic upgrade head on the Neon direct URL
#   infra/deploy.sh backend   trigger the backend deploy and wait until it is healthy
#   infra/deploy.sh frontend  trigger the frontend deploy and wait until it is healthy
#   infra/deploy.sh smoke     request /api/v1/health through the frontend (proves the proxy)
#   infra/deploy.sh bootstrap first admin (asks for a password) and, if VIGNETTES_DIR exists, the vignettes
#
# Settings come from infra/.env.deploy (see infra/.env.deploy.example). Render builds the commit you
# pushed, so push first. Migrations run BEFORE the new code starts: keep them backward compatible with
# the release that is still serving (add columns first, remove them in a later release).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT/infra/.env.deploy}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-600}"   # seconds; a free Render build plus cold start is slow

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

load_env() {
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found (copy infra/.env.deploy.example)"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

require() {
  local missing=()
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || missing+=("$name")
  done
  ((${#missing[@]} == 0)) || die "missing in $ENV_FILE: ${missing[*]}"
}

# libpq-style URL with the direct (non-pooled) host. Migrations and the CLI must not use the pooler.
require_direct() {
  [[ "$NEON_DATABASE_URL_DIRECT" != *-pooler* ]] || die "NEON_DATABASE_URL_DIRECT has a -pooler host; use the direct string"
}

cmd_check() {
  load_env
  require NEON_DATABASE_URL_DIRECT RENDER_BACKEND_DEPLOY_HOOK RENDER_FRONTEND_DEPLOY_HOOK BACKEND_URL FRONTEND_URL
  require_direct
  command -v curl >/dev/null || die "curl is required"
  command -v uv >/dev/null || die "uv is required (migrations run locally)"
  cd "$ROOT"
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "uncommitted changes: Render builds what is pushed, commit and push first"
  git fetch --quiet origin
  local head; head="$(git rev-parse HEAD)"
  git branch -r --contains "$head" | grep -q . || die "commit ${head:0:8} is not pushed to origin"
  echo "settings ok, deploying commit ${head:0:8}"
}

cmd_migrate() {
  load_env; require NEON_DATABASE_URL_DIRECT; require_direct
  log "migrating the database (direct connection)"
  (cd "$ROOT/backend" && DATABASE_URL="$NEON_DATABASE_URL_DIRECT" uv run alembic upgrade head)
}

# $1 label, $2 deploy hook, $3 health URL
deploy_service() {
  local label="$1" hook="$2" health="$3" sha
  sha="$(git -C "$ROOT" rev-parse HEAD)"
  log "deploying $label at ${sha:0:8}"
  # The hook URL carries a secret: keep it out of the output.
  curl -fsS -o /dev/null -X POST "${hook}&ref=${sha}" || die "$label: deploy hook request failed"
  wait_healthy "$label" "$health"
}

# Render only swaps the running instance once the new build passes its health check, so the old release
# answers until then. Wait for a 200 a few times in a row after the build had time to start.
wait_healthy() {
  local label="$1" url="$2" waited=0 ok=0
  echo "waiting for $label at $url (up to ${HEALTH_TIMEOUT}s)"
  sleep 20
  while ((waited < HEALTH_TIMEOUT)); do
    if curl -fsS -o /dev/null --max-time 30 "$url"; then
      ok=$((ok + 1))
      ((ok >= 3)) && { echo "$label is healthy"; return 0; }
    else
      ok=0
    fi
    sleep 10
    waited=$((waited + 10))
  done
  die "$label did not become healthy within ${HEALTH_TIMEOUT}s (check the Render logs)"
}

cmd_backend() {
  load_env; require RENDER_BACKEND_DEPLOY_HOOK BACKEND_URL
  deploy_service backend "$RENDER_BACKEND_DEPLOY_HOOK" "$BACKEND_URL/api/v1/health"
}

cmd_frontend() {
  load_env; require RENDER_FRONTEND_DEPLOY_HOOK FRONTEND_URL
  deploy_service frontend "$RENDER_FRONTEND_DEPLOY_HOOK" "$FRONTEND_URL/healthz"
}

cmd_smoke() {
  load_env; require FRONTEND_URL
  log "smoke test: the API through the frontend"
  curl -fsS --max-time 60 "$FRONTEND_URL/api/v1/health"; echo
}

cmd_bootstrap() {
  load_env; require NEON_DATABASE_URL_DIRECT ADMIN_EMAIL ADMIN_NAME; require_direct
  cd "$ROOT/backend"
  log "creating the admin $ADMIN_EMAIL (asks for a password)"
  DATABASE_URL="$NEON_DATABASE_URL_DIRECT" uv run python -m app.cli create-admin --email "$ADMIN_EMAIL" --name "$ADMIN_NAME"
  local dir="${VIGNETTES_DIR:-}"
  [[ -z "$dir" || "$dir" = /* ]] || dir="$ROOT/$dir"
  if [[ -n "$dir" && -d "$dir" ]]; then
    log "importing vignettes from $dir"
    DATABASE_URL="$NEON_DATABASE_URL_DIRECT" uv run python -m app.cli import-vignettes \
      --dir "$dir" --whatifs "$ROOT/scripts/elicitation/chip_whatifs.json" --admin-email "$ADMIN_EMAIL"
  else
    echo "no vignettes imported (VIGNETTES_DIR '${VIGNETTES_DIR:-}' is not a directory)"
  fi
}

case "${1:-all}" in
  all)       cmd_check; cmd_migrate; cmd_backend; cmd_frontend; cmd_smoke ;;
  check)     cmd_check ;;
  migrate)   cmd_migrate ;;
  backend)   cmd_backend ;;
  frontend)  cmd_frontend ;;
  smoke)     cmd_smoke ;;
  bootstrap) cmd_bootstrap ;;
  *)         sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
