#!/usr/bin/env bash
# First boot of the Ubuntu 24.04 VM, once, as root. Safe to run again.
#
#   scp -r infra/azure <user>@<vm-ip>:rag-setup
#   ssh <user>@<vm-ip> 'sudo bash rag-setup/setup-vm.sh'
#
# It installs Docker and Tailscale, adds 2 GB of swap, turns on security updates, copies this folder to
# /opt/rag (where deploy.sh and the compose file live) and installs the daily database backup.
# What it does not do: `tailscale up` and .env (both need you; see docs/azure-setup-guide.md).
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run it with sudo" >&2; exit 1; }
owner="${SUDO_USER:-root}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> swap (2 GB): the 4 GB VM has no disk swap by default"
if ! swapon --show | grep -q /swapfile; then
  [[ -f /swapfile ]] || { fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null; }
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
echo 'vm.swappiness=10' > /etc/sysctl.d/99-rag.conf
sysctl -q -p /etc/sysctl.d/99-rag.conf

echo "==> Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
usermod -aG docker "$owner"

echo "==> Tailscale"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled

echo "==> security updates, anacron (runs the daily backup after a boot, see below)"
apt-get install -y -qq unattended-upgrades anacron >/dev/null

echo "==> /opt/rag"
install -d -o "$owner" -g "$owner" /opt/rag /opt/rag/import
if [[ "$here" != /opt/rag ]]; then
  cp -a "$here"/docker-compose.yml "$here"/Caddyfile "$here"/env.example "$here"/deploy.sh \
        "$here"/backup.sh /opt/rag/
  chown "$owner:$owner" /opt/rag/*
fi
chmod +x /opt/rag/deploy.sh /opt/rag/backup.sh

echo "==> daily database backup (anacron: also after a boot)"
ln -sf /opt/rag/backup.sh /etc/cron.daily/rag-backup  # a link: a new backup.sh from a deploy is used at once

cat <<DONE

Done. Next (docs/azure-setup-guide.md, step 6):
  1. log out and in again (the docker group)
  2. sudo tailscale up --ssh --advertise-tags=tag:vm
  3. cp /opt/rag/env.example /opt/rag/.env && nano /opt/rag/.env
DONE
