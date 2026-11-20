#!/usr/bin/env bash
# Open psql in the postgres container (run on the host that runs docker compose).
#   scripts/db/psql.sh              interactive psql
#   scripts/db/psql.sh overview     table sizes, row counts, pgvector info
#   scripts/db/psql.sh -c "SQL"     any extra args go straight to psql
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; [ -f .env ] && . ./.env; set +a
U="${POSTGRES_USER:-rag}"; D="${POSTGRES_DB:-rag}"

# Inside the dev container there is no docker; connect via DATABASE_URL instead.
if command -v docker >/dev/null 2>&1; then
  PSQL=(docker compose exec -e PAGER="less -S" postgres psql -U "$U" -d "$D")
else
  PSQL=(psql "${DATABASE_URL:?DATABASE_URL not set}")
fi

if [ "${1:-}" = overview ]; then
  "${PSQL[@]}" <<'SQL'
\echo '== extensions =='
SELECT extname, extversion FROM pg_extension;
\echo '== tables (size, est. rows) =='
SELECT relname AS table, n_live_tup AS est_rows,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC;
\echo '== indexes =='
SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1, 2;
SQL
else
  "${PSQL[@]}" "$@"
fi
