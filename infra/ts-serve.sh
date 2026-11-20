#!/usr/bin/env bash
# Runs ON YOUR PC (WSL). Publishes Ollama and LanguageTool to the Azure VM through `tailscale serve`.
#
# Why this exists: with WSL mirrored networking, Docker Desktop cannot publish 127.0.0.1:11434 / :8010
# while `tailscale serve` already holds those ports, so the VM gets nothing. Docker has to bind first,
# serve second.
#
#   infra/ts-serve.sh up [service...]   docker compose up -d (recreating ollama + languagetool), then serve
#   infra/ts-serve.sh fix               same, for when the containers are already running
#   infra/ts-serve.sh status            serve rules, local ports, and what the VM sees (if reachable)
#
# Use `up` instead of `docker compose up` whenever ollama or languagetool get (re)built or recreated.
set -euo pipefail

PORTS=(11434 8010)
SERVICES=(ollama languagetool)

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

TS=$(command -v tailscale || true)
[ -n "$TS" ] || TS="/mnt/c/Program Files/Tailscale/tailscale.exe"
[ -x "$TS" ] || die "tailscale not found"
command -v docker >/dev/null || die "docker not found (is Docker Desktop running?)"
cd "$(dirname "$0")/.."

serve_off() { "$TS" serve reset; }
serve_on()  { for p in "${PORTS[@]}"; do "$TS" serve --bg --tcp "$p" "tcp://localhost:$p" >/dev/null; done; }
recreate()  { docker compose up -d --force-recreate "${SERVICES[@]}"; }

wait_local() {  # wait until Docker really answers on the loopback ports, else serve has nothing to forward to
  local i
  for i in $(seq 1 30); do
    curl -fs -m 2 -o /dev/null "http://127.0.0.1:11434/api/version" \
      && curl -fs -m 2 -o /dev/null "http://127.0.0.1:8010/v2/languages" && return 0
    sleep 2
  done
  die "ollama/languagetool do not answer on 127.0.0.1 after 60 s (docker compose logs ollama languagetool)"
}

case "${1:-}" in
  up)
    shift
    echo "==> serve off (frees ${PORTS[*]})"; serve_off
    echo "==> docker compose up"
    docker compose up -d "$@"
    # compose only recreates what changed; a container left from before the serve reset may have no
    # loopback listener, so force-recreate the two when they are not answering.
    if ! curl -fs -m 3 -o /dev/null http://127.0.0.1:11434/api/version \
       || ! curl -fs -m 3 -o /dev/null http://127.0.0.1:8010/v2/languages; then recreate; fi
    wait_local
    echo "==> serve on"; serve_on
    ;;
  fix)
    echo "==> serve off"; serve_off
    echo "==> recreate ${SERVICES[*]}"; recreate
    wait_local
    echo "==> serve on"; serve_on
    ;;
  status) ;;
  *) die "usage: $0 up [service...] | fix | status" ;;
esac

"$TS" serve status
for p in "${PORTS[@]}"; do
  printf 'local :%s -> %s\n' "$p" "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$p/")"
done
