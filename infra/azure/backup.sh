#!/usr/bin/env bash
# Dumps the database to /var/backups/rag, keeping 7 days. Installed by setup-vm.sh into
# /etc/cron.daily, which anacron also runs after a boot, so a VM that is switched off at night still
# gets its backup the next time it is on. Restore: notes/azure-setup-guide.md.
set -euo pipefail

BACKUPS=/var/backups/rag
APP="${RAG_DIR:-/opt/rag}"
install -d -m 700 "$BACKUPS"
cd "$APP"
out="$BACKUPS/rag-$(date +%F).dump"
# A failed dump leaves no .part behind and says so in the journal: journalctl -t rag-backup
trap 'rm -f "$out.part"; logger -t rag-backup -p user.err "backup FAILED: $out"' ERR
docker compose exec -T postgres pg_dump -U rag -Fc rag > "$out.part"
mv "$out.part" "$out"
logger -t rag-backup "backup written: $out"
find "$BACKUPS" -name 'rag-*.dump' -mtime +7 -delete
