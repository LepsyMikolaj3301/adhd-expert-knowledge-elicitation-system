#!/usr/bin/env bash
# Dump every SysON project (SysML v2 REST API) to models/<project>/elements.json
set -euo pipefail
BASE="${SYSON_URL:-http://localhost:8080}/api/rest"
OUT="$(dirname "$0")/models"

curl -sf "$BASE/projects" >/dev/null || { echo "SysON nie odpowiada pod ${SYSON_URL:-http://localhost:8080} - uruchom: docker compose up -d" >&2; exit 1; }

curl -sf "$BASE/projects" | python3 -c '
import sys, json
for p in json.load(sys.stdin): print(p["@id"], p["name"], sep="\t")
' | while IFS=$'\t' read -r id name; do
  dir="$OUT/${name//\//_}"
  mkdir -p "$dir"
  commit=$(curl -sf "$BASE/projects/$id/branches" | python3 -c '
import sys, json; print(json.load(sys.stdin)[0]["head"]["@id"])')
  curl -sf "$BASE/projects/$id/commits/$commit/elements" \
    | python3 -c 'import sys, json; json.dump(sorted(json.load(sys.stdin), key=lambda e: e["@id"]), sys.stdout, indent=2, ensure_ascii=False)' \
    > "$dir/elements.json"
  echo "exported $name -> $dir/elements.json"
done
