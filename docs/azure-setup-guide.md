# Azure setup guide: step by step, and how to keep it cheap

Follow the steps in order and tick them off. Each step says why it is there. The technical side
(files, architecture, how the 503 works) is in [deployment.md](deployment.md).

```
visitor --https--> Azure VM (Caddy > nginx > API, worker, Postgres)
                      '--Tailscale--> your PC (Ollama + LanguageTool, with the GPU)
GitHub Actions --Tailscale SSH--> Azure VM      (only when you press "Run workflow")
```

Prices below are from memory and change by region. Check each one in the
[Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/) before you rely on it.
The Azure and Tailscale pages also get renamed now and then; the names here are what I expect to see.

## The rules that keep $100 enough

1. **One VM, started only when someone needs it.** A stopped (deallocated) VM costs no compute.
2. **Create nothing else.** No Azure database, container registry, Bastion, load balancer, NAT
   gateway, Log Analytics, Backup or Defender. The images live on GitHub, the database in a
   container on the VM.
3. **Budget alerts first**, before the VM exists (step 1).
4. **Everything in one resource group**, so that deleting the group ends all billing (step 12).

| What | About | Running 24/7 | Switched off (deallocated) |
|---|---|---|---|
| VM B2s (2 vCPU, 4 GB) | $0.04 to 0.05 per hour | $30 to 38 per month | $0 |
| Disk, Standard SSD 30 GB | | $2 to 3 per month | the same |
| Static public IP (Standard) | | about $4 per month | the same |
| **Total** | | **about $36 to 45 per month** | **about $6 per month** |

So $100 lasts about 2 months if the VM never stops, and many months if it runs a few hours a day
(8 h a day is about $12 + $6 per month). Outbound traffic for a handful of users is negligible.

## 1. Cost safety first

- [ ] In the Azure portal open **Subscriptions** and check that your subscription is *Azure for
      Students* and how much credit is left. As far as I recall this offer has a spending cap: when the
      credit is gone the subscription is disabled instead of billing a card. Confirm that on its
      overview page, because it is the real safety net.
- [ ] **Cost Management + Billing > Budgets > Add**: scope = the subscription, amount = your credit
      (100), reset period monthly or "billing period", and alerts at **20, 50 and 80 %** of the budget by
      e-mail. If Budgets is not offered for your subscription type, put "check Cost analysis" in your
      calendar once a week instead.
- [ ] Check which **regions and VM sizes** your subscription allows (creating the VM in step 2 shows
      only the allowed ones). Pick a region near you, for example West Europe.

## 2. Create the resources

Everything goes in one resource group. Use the portal; each item is one screen.

- [ ] **Resource group** `rag-rg`, in your region.
- [ ] **Public IP address** `rag-ip`: SKU **Standard**, assignment **Static**, **DNS name label**
      `<something-unique>`. The name of your site is then `<label>.<region>.cloudapp.azure.com`; write it
      down, it is `DOMAIN` later. (A static IP keeps its name while the VM is off.)
      For this project: `DOMAIN=psyknowhow.belgiumcentral.cloudapp.azure.com` (label `psyknowhow`,
      region Belgium Central), so `APP_URL` is `https://psyknowhow.belgiumcentral.cloudapp.azure.com`.
      The IP, the NSG and the VM must all be in the same region (the student subscription only
      allows a few, and only some have a 4 GB VM size).
- [ ] **Network security group** `rag-nsg` with these inbound rules and no others:

  | Port | Source | For |
  |---|---|---|
  | 80 and 443 | Any | the site (80 is only for the certificate and the redirect) |
  | 22 | **My IP address** | first setup only; you delete this rule in step 7 |

- [ ] **Virtual machine** `rag-vm`:
  - Image: **Ubuntu Server 24.04 LTS**, x64. Size: **Standard_B2s** (or the cheapest 2 vCPU / 4 GB size
    your subscription allows; do not go below 4 GB, the images and Postgres need it).
  - Authentication: SSH public key. Username `azureuser`. (`ssh-keygen -t ed25519` if you have no key;
    paste the `.pub` file.)
  - Disk: **Standard SSD**, 30 GB (delete-with-VM on).
  - Networking: use the public IP and NSG above. **Delete public IP when VM is deleted: off.**
  - Management: **Enable auto-shutdown** at a time after you normally stop (for example 23:00), with
    your time zone. This is the safety net for forgetting. **Boot diagnostics: off.** Everything else
    off (Backup, Defender, Monitor, Log Analytics).
- [ ] Open the VM's page and check that the public IP is the static one and the DNS name works:
      `ssh azureuser@<label>.<region>.cloudapp.azure.com`.

## 3. Starting, stopping, and what a stop costs

- **Stop**: portal > the VM > **Stop** (it says "Stopped (deallocated)"), or
  `az vm deallocate -g rag-rg -n rag-vm`. Shutting down from inside Linux does **not** stop the
  billing; only "deallocated" does.
- **Start**: portal > **Start**, or `az vm start -g rag-rg -n rag-vm`. After about two minutes
  everything is back by itself: Docker, Tailscale and the containers start at boot, and the
  certificate is kept in a volume.
- **Deploy needs the VM on.** If the Deploy workflow says the VM does not answer, start it first.
- You pay for the disk and the IP while it is off (about $6 a month), nothing else.

## 4. Tailscale: the private line between the VM, your PC and GitHub

Ollama has no password, so it must never be reachable from the internet. Tailscale is a free private
network ("tailnet") that only your own machines join.

- [ ] Create a free account at tailscale.com and install it on **your PC** (step 5 says where).
- [ ] **Access controls** (the policy file): replace the content with the following. Put your PC's
      Tailscale IP (`tailscale ip -4` on the PC, starts with `100.`) where it says `PC_IP`, and your
      Linux user on the VM (`azureuser`) in `ssh`. Save.

  ```json
  {
    "tagOwners": {
      "tag:vm": ["autogroup:admin"],
      "tag:ci": ["autogroup:admin"]
    },
    "acls": [
      // your own devices can reach everything
      { "action": "accept", "src": ["autogroup:member"], "dst": ["*:*"] },
      // the VM may ask your PC for Ollama and LanguageTool, and nothing else
      { "action": "accept", "src": ["tag:vm"], "dst": ["PC_IP:11434,8010"] },
      // GitHub's runner may open an SSH connection to the VM
      { "action": "accept", "src": ["tag:ci"], "dst": ["tag:vm:22"] }
    ],
    "ssh": [
      {
        "action": "accept",
        "src": ["autogroup:member", "tag:ci"],
        "dst": ["tag:vm"],
        "users": ["azureuser"]
      }
    ]
  }
  ```

- [ ] **Settings > OAuth clients > Generate**: scope **Auth Keys: Write**, tag `tag:ci`. Copy the
      client ID and the secret now (the secret is shown once). They go to GitHub in step 8.

## 5. Your PC: Ollama and LanguageTool

The compose file of this repo already has both services. The VM only needs to reach their ports.

- [ ] **Install Tailscale where Docker runs.** If you use Docker Desktop on Windows, install the
      Windows app. If Docker runs inside WSL2 (as in the dev container), install Tailscale **inside
      WSL**: enable systemd (`/etc/wsl.conf`: `[boot]` `systemd=true`, then `wsl --shutdown`), run
      `curl -fsSL https://tailscale.com/install.sh | sh` and `sudo tailscale up`. Use one of the two,
      not both, because each is a separate machine in the tailnet.
- [ ] `tailscale ip -4` gives the PC's address; this is `PC_HOST` for the VM, and `PC_IP` in step 4.
- [ ] In the repo's `.env` add `OLLAMA_KEEP_ALIVE=30m` so the models stay loaded between requests.
- [ ] `docker compose up -d ollama languagetool`, then pull what the VM will ask for:

  ```bash
  docker compose exec ollama ollama pull qwen3.5:9b     # CLASSIFIER_MODEL and ENHANCE_MODEL
  docker compose exec ollama ollama pull bge-m3         # embeddings
  ```

- [ ] Let the tailnet in. The compose file publishes both ports on `127.0.0.1` only (not your LAN),
      and Tailscale forwards its own ports to them. Run this where Tailscale runs (Windows, or
      WSL), once; `--bg` keeps it across reboots, and it doesn't care whether Docker or Tailscale
      starts first:

  ```bash
  tailscale serve --bg --tcp 11434 tcp://localhost:11434
  tailscale serve --bg --tcp 8010 tcp://localhost:8010
  tailscale serve status    # shows both
  ```

- [ ] Check that the PC answers: `curl http://<PC address>:11434/api/tags` and
      `curl http://<PC address>:8010/v2/languages`. (The same two requests are made by the API before it
      queues a job. If your PC is off or a model is missing, the user gets "The computer that checks
      answers is not ready" and nothing is queued.)

## 6. The VM, first boot

- [ ] From the repo on your PC copy the folder and run the setup (this uses the public SSH rule of
      step 2, for the last time):

  ```bash
  scp -r infra/azure azureuser@<DOMAIN>:rag-setup
  ssh azureuser@<DOMAIN> 'sudo bash rag-setup/setup-vm.sh'
  ```

  It installs Docker and Tailscale, adds 2 GB of swap, turns on security updates, and installs the
  daily database backup in `/opt/rag`.
- [ ] Log in again (so the `docker` group applies) and join the tailnet:
      `sudo tailscale up --ssh --advertise-tags=tag:vm` (open the link it prints and approve).
- [ ] `cp /opt/rag/env.example /opt/rag/.env && nano /opt/rag/.env` and fill in:
      `DOMAIN`, `REGISTRY` (`ghcr.io/<github-user-lowercase>/<repository>`), `PC_HOST` (step 5),
      `POSTGRES_PASSWORD` (`openssl rand -base64 24 | tr -d '/+='`). Then `chmod 600 /opt/rag/.env`.
- [ ] Let the VM pull your images. Either make the two packages public on GitHub after the first
      build (Packages > the package > Settings > Change visibility), or log in once with a token:
      GitHub > Settings > Developer settings > Personal access tokens (classic) > scope
      `read:packages`, then `echo <token> | docker login ghcr.io -u <github-user> --password-stdin`.

## 7. Close the SSH port

- [ ] Check that Tailscale SSH works from your PC: `ssh azureuser@<VM name in the tailnet>` (the
      machine name shown in the Tailscale admin page).
- [ ] Azure portal > `rag-nsg` > delete the **port 22** rule. From now on the VM has only 80 and 443
      open to the internet.

## 8. GitHub: secrets and the Deploy workflow

- [ ] Repository > Settings > **Secrets and variables > Actions**:
  - Secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET` (step 4).
  - Variables: `VM_HOST` (the VM's name in the tailnet), `VM_USER` (`azureuser`), `APP_URL`
    (`https://<DOMAIN>`, no trailing slash).
- [ ] Settings > **Environments** > New `azure` (optionally add yourself as a required reviewer, so
      that every deploy asks you to confirm).
- [ ] Actions > **CI** > Run workflow once. It should be green. Fix what it reports before deploying.

## 9. First deploy

- [ ] Start the VM and your PC's Ollama and LanguageTool.
- [ ] Actions > **Deploy** > Run workflow. Options: *Run the CI checks first* (leave on; turn off to
      skip) and *Deploy to the VM* (turn off to only build and push the images, for example for the
      first run if you want to make the packages public before the VM pulls).
- [ ] When it is green, `https://<DOMAIN>` shows the login page. The first start takes a minute: the
      certificate is requested when the first visitor arrives.

## 10. First data

On the VM, in `/opt/rag`:

```bash
# the first admin (asks for a password)
docker compose --profile tools run --rm cli create-admin --email you@example.com --name "Your Name"
```

To import the vignettes, copy them from your PC (the folder and the what-ifs file) and import:

```bash
scp -r data/fixtures_chips/synthetic/silver/vignettes scripts/elicitation/chip_whatifs.json \
    azureuser@<VM name in the tailnet>:/opt/rag/import/
docker compose --profile tools run --rm cli import-vignettes \
    --dir /import/vignettes --whatifs /import/chip_whatifs.json --admin-email you@example.com
```

## 11. Day to day

| I want to | Do |
|---|---|
| Use the app | Start the VM (step 3), start Ollama and LanguageTool on the PC, open the link. |
| Stop paying | Stop (deallocate) the VM. |
| Ship a change | `git push` to main, then Actions > Deploy > Run workflow. |
| See what happens | `cd /opt/rag && docker compose logs -f --tail 100 rag-backend worker` |
| Restart everything | `cd /opt/rag && ./deploy.sh` (pulls and starts what is in `.env`). |
| See the memory use | `docker stats --no-stream` (the limits are in `docker-compose.yml`). |
| Back up | Automatic: a dump in `/var/backups/rag` each day the VM is on, last 7 kept. |
| Copy a backup home | `ssh azureuser@<VM> 'sudo cat /var/backups/rag/rag-<date>.dump' > rag.dump` |
| Restore a backup | `docker compose exec -T postgres pg_restore -U rag -d rag --clean --if-exists < rag-<date>.dump` |

**"The computer that checks answers is not ready"** (503 `compute_unavailable`): the VM cannot use your
PC. Check that the PC is on and awake, that Tailscale runs on it (`tailscale status`), that
`docker compose up -d ollama languagetool` is running, and that the model it names was pulled. Nothing
was changed or queued, so the user can simply try again.

**Jobs that were already queued** when the PC went away are tried three times and then marked failed;
an admin can retry them from the app once the PC is back.

## 12. Tear it all down

Azure portal > Resource groups > `rag-rg` > **Delete resource group**. That removes the VM, disk, IP
and network, and ends all billing. Download a backup first (step 11). Then remove the VM from the
Tailscale admin page.
