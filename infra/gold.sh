#!/usr/bin/env bash
# Copies the production database (Neon) to files on this machine, and loads a copy into a local database.
#
#   infra/gold.sh pull                 dump Neon into $GOLD_DIR/<UTC time>/, check it, write the answers as JSON lines
#   infra/gold.sh restore <snapshot>   load a snapshot into a NEW local database, rag_gold_<time>
#
# Run it on the host (WSL) where docker compose runs, not in the dev container: pg_dump, pg_restore and
# psql are the ones inside the local postgres container (start it: docker compose up -d postgres), so
# they match its major version. Neon must be the same major version or newer pg_dump refuses.
#
# What a snapshot holds (read-only files, never overwritten, never deleted by this script):
#   prod.dump         pg_dump -Fc of the schemas app and chips. Login sessions and invite links are left
#                     out (their token hashes are of no use later); users and their e-mails are in it.
#   submissions.jsonl one line per submitted case: the raw answers as stored, plus the vignette's text
#   drafts.jsonl      answers not submitted (yet)
#   manifest.txt      when, from where, the migration version and the row count of every table
#   SHA256SUMS        checksums of the four files above
#
# The production database is only read (the dump runs in a read-only session). A snapshot is built in
# <time>.partial and renamed when every check has passed. The only DROP in this script is of the
# throwaway database it created itself (gold_check_<time>).
#
# Settings come from infra/.env.deploy (see infra/.env.deploy.example): NEON_DATABASE_URL_DIRECT, GOLD_DIR
# and optionally GOLD_MIRROR_DIR (a second copy on another disk). `restore` needs none of them.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT/infra/.env.deploy}"
cd "$ROOT"

WARNINGS=0
log() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
warn() { printf '\n!!! WARNING: %s\n' "$*" >&2; WARNINGS=$((WARNINGS + 1)); }

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

# A line of the repository's .env, for the local database user.
env_value() { [[ -f "$ROOT/.env" ]] && { grep -E "^$1=" "$ROOT/.env" | tail -1 | cut -d= -f2- || true; } || true; }
LOCAL_USER="$(env_value POSTGRES_USER)"; LOCAL_USER="${LOCAL_USER:-rag}"
LOCAL_PASSWORD="$(env_value POSTGRES_PASSWORD)"; LOCAL_PASSWORD="${LOCAL_PASSWORD:-rag}"

# --- local database (the compose postgres container) -------------------------------------------

local_pg() { docker compose exec -T postgres "$@"; }
lpsql() { local_pg psql -U "$LOCAL_USER" -v ON_ERROR_STOP=1 "$@"; }

need_local() {
  command -v docker >/dev/null || die "docker not found: run this on the host (WSL), not in the dev container"
  docker compose ps --status running --services 2>/dev/null | grep -qx postgres \
    || die "the local postgres container is not running (docker compose up -d postgres)"
}

# --- production (Neon): read-only ---------------------------------------------------------------

# Runs a tool of the postgres container against Neon. The URL goes in through the environment, and
# the session is read-only whatever the tool does.
neon_tool() {
  local tool="$1"; shift
  docker compose exec -T -e "PGURL=$NEON_DATABASE_URL_DIRECT" -e "PGOPTIONS=-c default_transaction_read_only=on" \
    postgres sh -c 'tool="$1"; shift; exec "$tool" "$PGURL" "$@"' sh "$tool" "$@"
}
npsql() { neon_tool psql -v ON_ERROR_STOP=1 "$@"; }

# --- what to compare and what to write ----------------------------------------------------------

# "schema.table rows" for every table of the two schemas the application owns.
read -r -d '' COUNTS_SQL <<'SQL' || true
SELECT schemaname || '.' || tablename || ' ' ||
       (xpath('/row/c/text()', query_to_xml(
          format('SELECT count(*) AS c FROM %I.%I', schemaname, tablename), false, true, '')))[1]::text
FROM pg_tables WHERE schemaname IN ('app', 'chips') ORDER BY 1
SQL

read -r -d '' SUBMISSIONS_SQL <<'SQL' || true
SELECT row_to_json(t) FROM (
  SELECT s.assignment_id, s.submitted_at, s.payload_format, s.vignette_hash, s.payload,
         a.state AS assignment_state, v.code AS vignette_code, vv.version AS vignette_version,
         vv.framing, vv.question_ids, vv.q4_whatif, vv.variant, vv.text AS vignette_text
  FROM app.submissions s
  JOIN app.assignments a ON a.id = s.assignment_id
  JOIN app.vignette_versions vv ON vv.id = a.vignette_version_id
  JOIN app.vignettes v ON v.id = vv.vignette_id
  ORDER BY s.submitted_at, s.assignment_id) t
SQL

read -r -d '' DRAFTS_SQL <<'SQL' || true
SELECT row_to_json(t) FROM (
  SELECT d.assignment_id, a.state AS assignment_state, u.pseudonym AS expert_pseudonym,
         v.code AS vignette_code, vv.version AS vignette_version,
         d.version AS draft_version, d.updated_at, d.payload
  FROM app.answer_drafts d
  JOIN app.assignments a ON a.id = d.assignment_id
  JOIN app.users u ON u.id = a.expert_id
  JOIN app.vignette_versions vv ON vv.id = a.vignette_version_id
  JOIN app.vignettes v ON v.id = vv.vignette_id
  WHERE NOT EXISTS (SELECT 1 FROM app.submissions s WHERE s.assignment_id = d.assignment_id)
  ORDER BY d.updated_at, d.assignment_id) t
SQL

# Left out of the dump: login tokens, of no use later. Not compared either.
NOT_DUMPED="app.auth_sessions app.invites"

# An absolute path outside the repository (a checkout or `git clean` must not be able to reach it).
safe_dir() {
  local label="$1" dir="${2/#\~/$HOME}"
  [[ "$dir" = /* ]] || die "$label must be an absolute path (or start with ~/): $dir"
  dir="$(realpath -m "$dir")"
  case "$dir/" in
    "$ROOT"/*) die "$label ($dir) is inside the repository: pick a folder outside it" ;;
  esac
  printf '%s' "$dir"
}

count_of() { awk -v k="$2" '$1 == k { print $2 }' <<<"$1"; }

# --- pull ---------------------------------------------------------------------------------------

TMPDB=""
cleanup() {
  if [[ -n "$TMPDB" ]]; then
    lpsql -d postgres -c "DROP DATABASE IF EXISTS \"$TMPDB\" WITH (FORCE)" >/dev/null 2>&1 || true
  fi
}

copy_to_mirror() {
  local snapshot="$1" name="$2" mirror
  mirror="$(safe_dir GOLD_MIRROR_DIR "$GOLD_MIRROR_DIR")" || return 1
  mkdir -p "$mirror" || return 1
  [[ ! -e "$mirror/$name" && ! -e "$mirror/$name.partial" ]] || { echo "already there: $mirror/$name" >&2; return 1; }
  cp -r "$snapshot" "$mirror/$name.partial" || return 1
  (cd "$mirror/$name.partial" && sha256sum --quiet -c SHA256SUMS) || return 1
  mv "$mirror/$name.partial" "$mirror/$name" || return 1
  chmod -R a-w "$mirror/$name" 2>/dev/null || true   # some mounts (Windows drives) ignore it
  echo "mirrored and verified: $mirror/$name"
}

cmd_pull() {
  load_env; require NEON_DATABASE_URL_DIRECT GOLD_DIR
  [[ "$NEON_DATABASE_URL_DIRECT" != *-pooler* ]] || die "NEON_DATABASE_URL_DIRECT has a -pooler host; dumps need the direct string"
  need_local
  local gold; gold="$(safe_dir GOLD_DIR "$GOLD_DIR")"
  mkdir -p "$gold"

  local ts name part out
  ts="$(date -u +%Y%m%dT%H%M%SZ)"; name="$ts"
  part="$gold/$name.partial"; out="$gold/$name"
  [[ ! -e "$part" && ! -e "$out" ]] || die "$out already exists (wait a second and run again)"

  log "checking versions"
  local src_ver loc_ver
  src_ver="$(npsql -At -c 'SHOW server_version_num' || true)"
  [[ -n "$src_ver" ]] || die "can't reach Neon with NEON_DATABASE_URL_DIRECT"
  loc_ver="$(lpsql -d postgres -At -c 'SHOW server_version_num')"
  ((src_ver / 10000 <= loc_ver / 10000)) \
    || die "Neon is Postgres $((src_ver / 10000)) but the local pg_dump is $((loc_ver / 10000)): create the Neon project as Postgres $((loc_ver / 10000)), or upgrade the postgres image"
  local extra
  extra="$(npsql -At -c "SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname NOT IN ('app','chips','pg_catalog','information_schema')" || true)"
  [[ -z "$extra" ]] || warn "Neon has tables outside app and chips, which are NOT dumped: $(tr '\n' ' ' <<<"$extra")"

  mkdir "$part"
  log "dumping app and chips from Neon (read-only) into $part"
  local exclude=()
  for table in $NOT_DUMPED; do exclude+=("--exclude-table-data=$table"); done
  neon_tool pg_dump -Fc --no-owner --no-privileges --schema=app --schema=chips "${exclude[@]}" >"$part/prod.dump"
  [[ -s "$part/prod.dump" ]] || die "the dump is empty"

  log "restoring it into a throwaway local database, to prove the file works"
  TMPDB="gold_check_${ts,,}"
  trap cleanup EXIT
  lpsql -d postgres -c "CREATE DATABASE \"$TMPDB\"" >/dev/null
  lpsql -d "$TMPDB" -c 'CREATE EXTENSION IF NOT EXISTS vector' >/dev/null
  local_pg pg_restore -U "$LOCAL_USER" --no-owner --no-privileges --exit-on-error -d "$TMPDB" <"$part/prod.dump"

  log "writing the answers and the manifest from the restored copy"
  lpsql -d "$TMPDB" -At -c "$SUBMISSIONS_SQL" >"$part/submissions.jsonl"
  lpsql -d "$TMPDB" -At -c "$DRAFTS_SQL" >"$part/drafts.jsonl"
  local restored source_now alembic
  restored="$(lpsql -d "$TMPDB" -At -c "$COUNTS_SQL")"
  alembic="$(lpsql -d "$TMPDB" -At -c 'SELECT version_num FROM app.alembic_version')"
  {
    echo "# created   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# source    $(sed -E 's#^[a-z]+://[^@]*@([^/?]+).*#\1#' <<<"$NEON_DATABASE_URL_DIRECT") (postgres $((src_ver / 10000)))"
    echo "# alembic   $alembic"
    echo "# not dumped: $NOT_DUMPED"
    echo "$restored"
  } >"$part/manifest.txt"

  log "checking the copy against Neon and the last snapshot"
  source_now="$(npsql -At -c "$COUNTS_SQL")"
  local table rows now
  while read -r table rows; do
    [[ " $NOT_DUMPED " != *" $table "* ]] || continue
    now="$(count_of "$source_now" "$table")"
    # Rows may have arrived since the dump, never gone.
    if ((${now:-0} < rows)); then
      warn "$table has ${now:-0} rows on Neon but ${rows} in the dump: something was deleted on Neon after the dump"
    fi
  done <<<"$restored"
  local prev old new
  prev="$(ls -1d "$gold"/[0-9]*T*Z 2>/dev/null | sort | tail -1 || true)"
  new="$(count_of "$restored" app.submissions)"
  if [[ -n "$prev" && -f "$prev/manifest.txt" ]]; then
    old="$(awk '$1 == "app.submissions" { print $2 }' "$prev/manifest.txt")"
    if ((${new:-0} < ${old:-0})); then
      warn "submissions went DOWN since the last snapshot ($(basename "$prev")): $old -> $new. Do not delete that snapshot."
    fi
  fi

  (cd "$part" && sha256sum prod.dump submissions.jsonl drafts.jsonl manifest.txt >SHA256SUMS && sha256sum --quiet -c SHA256SUMS)
  mv "$part" "$out"
  chmod -R a-w "$out"

  if [[ -n "${GOLD_MIRROR_DIR:-}" ]]; then
    log "copying to the mirror"
    copy_to_mirror "$out" "$name" || warn "the mirror copy FAILED: the snapshot exists only in $out"
  else
    warn "no GOLD_MIRROR_DIR: this snapshot exists in one place only"
  fi

  log "done: $out"
  echo "submissions: ${new:-0}   drafts: $(wc -l <"$out/drafts.jsonl")   migration: $alembic"
  if ((WARNINGS > 0)); then
    echo "finished with $WARNINGS warning(s), see above" >&2
    exit 1
  fi
}

# --- restore ------------------------------------------------------------------------------------

cmd_restore() {
  local snap="${1:-}"
  [[ -d "$snap" ]] || die "usage: infra/gold.sh restore <snapshot directory>"
  need_local
  snap="$(realpath "$snap")"
  (cd "$snap" && sha256sum --quiet -c SHA256SUMS) || die "$snap fails its checksums: use another copy of the snapshot"

  local db; db="rag_gold_$(basename "$snap")"; db="${db,,}"
  [[ "$db" =~ ^rag_gold_[0-9]{8}t[0-9]{6}z$ ]] || die "the folder name ($(basename "$snap")) is not a snapshot time like 20261106T101500Z"
  if [[ -n "$(lpsql -d postgres -At -c "SELECT 1 FROM pg_database WHERE datname = '$db'")" ]]; then
    die "the database $db already exists, so nothing was changed. It is the same snapshot; use it, or drop it yourself first."
  fi

  log "restoring $snap into the new database $db"
  lpsql -d postgres -c "CREATE DATABASE \"$db\"" >/dev/null
  lpsql -d "$db" -c 'CREATE EXTENSION IF NOT EXISTS vector' >/dev/null
  local_pg pg_restore -U "$LOCAL_USER" --no-owner --no-privileges --exit-on-error -d "$db" <"$snap/prod.dump" \
    || die "the restore failed part way: $db is left as it is for you to look at (drop it before trying again)"

  local now line table rows bad=0
  now="$(lpsql -d "$db" -At -c "$COUNTS_SQL")"
  while read -r table rows; do
    [[ -n "$table" && "$table" != "#"* ]] || continue
    if [[ "$(count_of "$now" "$table")" != "$rows" ]]; then
      echo "MISMATCH $table: manifest $rows, restored $(count_of "$now" "$table")" >&2
      bad=1
    fi
  done < <(grep -v '^#' "$snap/manifest.txt")
  ((bad == 0)) || die "row counts differ from the manifest (see above)"
  grep -E '^# ' "$snap/manifest.txt" || true
  grep -E '^app\.(users|vignettes|assignments|submissions|answer_drafts) ' "$snap/manifest.txt" || true
  echo
  echo "restored as $db. Connect with:"
  echo "  DATABASE_URL=postgresql://$LOCAL_USER:$LOCAL_PASSWORD@localhost:5432/$db"
  echo "Your development database (rag) was not touched."
}

case "${1:-}" in
  pull)    cmd_pull ;;
  restore) shift; cmd_restore "${1:-}" ;;
  *)       sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
