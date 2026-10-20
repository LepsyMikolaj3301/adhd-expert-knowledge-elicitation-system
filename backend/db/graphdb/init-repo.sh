#!/bin/sh
# Creates the GraphDB repository if it does not exist yet. Safe to re-run.
set -eu

: "${GRAPHDB_URL:?GRAPHDB_URL is required}"
: "${GRAPHDB_REPOSITORY:?GRAPHDB_REPOSITORY is required}"

if curl -sf "$GRAPHDB_URL/rest/repositories/$GRAPHDB_REPOSITORY" >/dev/null; then
    echo "GraphDB repository '$GRAPHDB_REPOSITORY' already exists, skipping."
    exit 0
fi

config=/tmp/repo-config.ttl
sed "s/__REPO_ID__/$GRAPHDB_REPOSITORY/" /init/repo-config.ttl > "$config"

curl -sf -X POST "$GRAPHDB_URL/rest/repositories" -F "config=@$config"
echo "Created GraphDB repository '$GRAPHDB_REPOSITORY'."
