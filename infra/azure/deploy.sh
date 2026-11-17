#!/usr/bin/env bash
# Runs ON THE VM, in the folder that holds docker-compose.yml and .env (/opt/rag).
#
#   ./deploy.sh [IMAGE_TAG]   pull the images, migrate, restart what changed, wait until healthy
#
# IMAGE_TAG (for example sha-1a2b3c4) is written to .env, so a reboot starts the same release.
# Without it, the tag already in .env is deployed again (that is also how to pick up `latest`).
# The migrations run first, as the `migrate` service the API and the worker wait for: keep each one
# compatible with the release still running (add first, remove in a later release).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ -f .env ]] || die ".env not found in $PWD (copy env.example and fill it in)"

tag="${1:-}"
if [[ -n "$tag" ]]; then
  [[ "$tag" =~ ^[A-Za-z0-9._-]+$ ]] || die "odd image tag: $tag"
  if grep -q '^IMAGE_TAG=' .env; then
    sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=$tag|" .env
  else
    echo "IMAGE_TAG=$tag" >> .env
  fi
fi

echo "==> pulling images"
docker compose pull --quiet
echo "==> starting (migrations first)"
docker compose up -d --remove-orphans

# `up -d` returns when the containers are started, not healthy.
wait_healthy() {
  local service="$1" waited=0 id status
  id="$(docker compose ps -q "$service")"
  [[ -n "$id" ]] || die "$service is not running"
  while ((waited < 180)); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$id")"
    [[ "$status" == healthy ]] && { echo "$service is healthy"; return 0; }
    sleep 3
    waited=$((waited + 3))
  done
  docker compose logs --tail 40 "$service" || true
  die "$service did not become healthy within 180 s"
}
wait_healthy rag-backend
wait_healthy worker
wait_healthy frontend

echo "==> removing images nothing uses"
docker image prune -f >/dev/null
docker compose ps
