#!/usr/bin/env bash
# Runs ON YOUR PC (WSL or Linux, with the Azure CLI logged in). Nothing starts the VM but this
# script (or the portal): no schedule, no start at logon.
#
#   infra/azure/vm.sh start    start rag-vm and wait until it runs (the app is up ~2 min later)
#   infra/azure/vm.sh stop     deallocate rag-vm (only "deallocated" stops compute billing)
#   infra/azure/vm.sh status   print the power state
set -euo pipefail

RG=rag-rg
VM=rag-vm
SUB='Azure for Students'   # by name, so the wrong default subscription is never used

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
command -v az >/dev/null || die "Azure CLI (az) not found"
az account get-access-token --subscription "$SUB" -o none 2>/dev/null \
  || die "Azure login missing or expired: run 'az login'"

state() {
  az vm get-instance-view -g "$RG" -n "$VM" --subscription "$SUB" -o tsv \
    --query "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus | [0]" | tr -d '\r'
}

case "${1:-}" in
  start)  echo "==> starting $VM";     az vm start      -g "$RG" -n "$VM" --subscription "$SUB" ;;
  stop)   echo "==> deallocating $VM"; az vm deallocate -g "$RG" -n "$VM" --subscription "$SUB" ;;
  status) ;;
  *) die "usage: $0 start|stop|status" ;;
esac
echo "$VM: $(state)"
