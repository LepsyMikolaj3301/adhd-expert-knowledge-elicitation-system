---
title: How to deploy to the Azure VM
diataxis: how-to
---

# How to deploy to the Azure VM

Language: **English** · [Polski](../pl/how-to/deploy-to-azure-vm.md)

Use this to set up the Azure VM once, publish the PC's Ollama and LanguageTool to it, deploy a release, and start, stop and back up the VM with the scripts in `infra/`.

## Prerequisites

- An Ubuntu 24.04 VM named `rag-vm` in resource group `rag-rg`, in the Azure subscription named `Azure for Students` (the names are fixed in `infra/azure/vm.sh`).
- Ports 80 and 443 open to the internet for the VM; Caddy requests its TLS certificate for `DOMAIN` itself (`infra/azure/Caddyfile`).
- On your PC (WSL or Linux): the Azure CLI `az`, logged in with `az login` (`infra/azure/vm.sh` stops with an error otherwise), plus Docker and Tailscale for the compute services (`infra/ts-serve.sh`).
- Container images for the backend and the frontend at `${REGISTRY}/backend:<tag>` and `${REGISTRY}/frontend:<tag>` (`infra/azure/docker-compose.yml`). The workflow in `.github/workflows/deploy.yml` builds and pushes them (see step 7).

## Steps

1. Start the VM from your PC and wait until it runs. The app is up about two minutes later (comment in `infra/azure/vm.sh`).

   ```bash
   infra/azure/vm.sh start
   ```

2. On the first boot only, copy `infra/azure` to the VM and run the setup script as root. It adds swap, installs Docker and Tailscale, creates `/opt/rag`, copies the compose files and `deploy.sh` and `backup.sh` there, and links the daily backup into `/etc/cron.daily` (`infra/azure/setup-vm.sh`). The script can be run again.

   ```bash
   scp -r infra/azure <user>@<vm-ip>:rag-setup
   ssh <user>@<vm-ip> 'sudo bash rag-setup/setup-vm.sh'
   ```

3. On the VM, finish what the script leaves to you (printed at its end): log out and in again so the `docker` group applies, join the tailnet, and create `.env` from the template.

   ```bash
   sudo tailscale up --ssh --advertise-tags=tag:vm
   cp /opt/rag/env.example /opt/rag/.env && nano /opt/rag/.env
   ```

   Fill in `DOMAIN` (public name of the VM), `REGISTRY` (`ghcr.io/<github-owner-in-lowercase>/<repo-name>`), `PC_HOST` (the Tailscale IP of your PC) and `POSTGRES_PASSWORD`. To generate a password, `infra/azure/env.example` suggests:

   ```bash
   openssl rand -base64 24 | tr -d '/+='
   ```

   The other keys (`CLASSIFIER_MODEL`, `ENHANCE_MODEL`, `ENVIRONMENT`, `COOKIE_SECURE`, `SESSION_TTL_HOURS`) have defaults in the template; see [Runtime and deployment](../reference/runtime-and-deploy.md).

4. On your PC, pull the models that the VM backend uses into Ollama: the models named in `CLASSIFIER_MODEL` and `ENHANCE_MODEL` (`ollama pull`, as `infra/azure/env.example` says) and `bge-m3` for embeddings (comment on the `worker` service in `docker-compose.yml`).

5. On your PC, start the compute services and publish their ports to the tailnet. Use this instead of plain `docker compose up` whenever `ollama` or `languagetool` are built or recreated (`infra/ts-serve.sh`).

   ```bash
   infra/ts-serve.sh up
   ```

   If the containers already run and the VM does not reach them, run `infra/ts-serve.sh fix`.

6. On the VM, deploy. The script pulls the images, starts the stack (the `migrate` service runs the migrations first) and waits up to 180 s each for `rag-backend`, `worker` and `frontend` to be healthy (`infra/azure/deploy.sh`).

   ```bash
   cd /opt/rag
   ./deploy.sh <IMAGE_TAG>
   ```

   The tag is written to `.env`, so a reboot starts the same release. Without an argument the tag already in `.env` is deployed again, which also picks up `latest`. If a service does not become healthy, the script prints its last 40 log lines and exits with an error.

7. To deploy from GitHub instead of the VM shell, run the `Deploy` workflow manually (Actions, Deploy, Run workflow). It optionally runs CI, builds and pushes both images tagged `sha-<7 characters of the commit>` and `latest`, copies `docker-compose.yml`, `Caddyfile`, `env.example`, `deploy.sh` and `backup.sh` to `/opt/rag` over Tailscale SSH, runs `/opt/rag/deploy.sh <tag>` and requests `/api/v1/health` and `/` of `APP_URL`. The inputs `run_tests` and `deploy` switch the CI run and the VM step off (`.github/workflows/deploy.yml`). The VM must be running first.

8. After the first deploy, create the admin user with the one-shot `cli` service (comment in `infra/azure/docker-compose.yml`).

   ```bash
   cd /opt/rag
   docker compose --profile tools run --rm cli create-admin --email <email> --name <name>
   ```

   To import vignettes, put the files under `/opt/rag/import` and run `docker compose --profile tools run --rm cli import-vignettes --dir /import/vignettes --whatifs /import/chip_whatifs.json --admin-email <email>`.

9. Back up the database. The daily backup runs from `/etc/cron.daily` (anacron runs it after a boot too). To dump it by hand, run the script as root on the VM:

   ```bash
   sudo /opt/rag/backup.sh
   ```

   The dump lands in `/var/backups/rag/rag-<date>.dump`; dumps older than 7 days are deleted. If a backup fails, read the journal:

   ```bash
   journalctl -t rag-backup
   ```

10. To stop the VM, deallocate it from your PC. Only the `deallocated` state stops compute billing (`infra/azure/vm.sh`).

    ```bash
    infra/azure/vm.sh stop
    ```

## Check the result

- `infra/azure/vm.sh status` prints `rag-vm: <power state>`.
- `./deploy.sh` prints `<service> is healthy` for `rag-backend`, `worker` and `frontend`, then `docker compose ps`.
- The smoke test of the workflow requests `${{ vars.APP_URL }}/api/v1/health` and `${{ vars.APP_URL }}/` (`.github/workflows/deploy.yml`); the workflow reads `APP_URL` from the GitHub `vars` context.
- Caddy serves the site at `DOMAIN` and proxies to `frontend`, so `curl -fsS https://<DOMAIN>/api/v1/health` requests the health endpoint of `rag-backend` through Caddy and nginx.
- `infra/ts-serve.sh status` prints the `tailscale serve` rules and the HTTP code of local ports 11434 and 8010.

## See also

- [Runtime and deployment](../reference/runtime-and-deploy.md): compose services, limits, environment keys and the scripts.
- [Backend core API](../reference/backend-core-api.md): the `create-admin` and `import-vignettes` commands.
- [Architecture](../explanation/architecture.md)

## Sources in code

- `infra/azure/vm.sh` - start, stop and status of the VM, fixed names
- `infra/azure/setup-vm.sh` - first-boot setup and the follow-up commands it prints
- `infra/azure/env.example` - environment keys and the password-generation command
- `infra/azure/deploy.sh` - deploy script, tag handling, health waits
- `infra/azure/backup.sh` - daily dump, retention, journal tag
- `infra/azure/docker-compose.yml` - services, health checks, `cli` one-shot commands
- `infra/azure/Caddyfile` - TLS for DOMAIN, ports 80 and 443
- `infra/ts-serve.sh` - publishing Ollama and LanguageTool through tailscale serve
- `docker-compose.yml` - the compute services on the PC and the bge-m3 requirement
- `.github/workflows/deploy.yml` - build, push and deploy workflow
