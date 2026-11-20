---
title: Jak wdrożyć na maszynie wirtualnej Azure
diataxis: how-to
---

# Jak wdrożyć na maszynie wirtualnej Azure

Język: **Polski** · [English](../../how-to/deploy-to-azure-vm.md)

Skorzystaj z tej strony, aby jednorazowo skonfigurować maszynę wirtualną Azure, opublikować na niej Ollamę i LanguageTool z komputera PC, wdrożyć wydanie oraz uruchamiać, zatrzymywać i archiwizować maszynę skryptami z `infra/`.

## Wymagania wstępne

- Maszyna wirtualna z Ubuntu 24.04 o nazwie `rag-vm` w grupie zasobów `rag-rg`, w subskrypcji Azure o nazwie `Azure for Students` (nazwy są zapisane na stałe w `infra/azure/vm.sh`).
- Porty 80 i 443 otwarte na internet dla maszyny; Caddy samodzielnie żąda certyfikatu TLS dla `DOMAIN` (`infra/azure/Caddyfile`).
- Na Twoim komputerze PC (WSL lub Linux): Azure CLI `az`, zalogowane przez `az login` (w przeciwnym razie `infra/azure/vm.sh` kończy działanie z błędem), a także Docker i Tailscale dla usług obliczeniowych (`infra/ts-serve.sh`).
- Obrazy kontenerów backendu i frontendu pod adresami `${REGISTRY}/backend:<tag>` i `${REGISTRY}/frontend:<tag>` (`infra/azure/docker-compose.yml`). Workflow w `.github/workflows/deploy.yml` buduje je i wypycha (zob. krok 7).

## Kroki

1. Uruchom maszynę ze swojego komputera PC i poczekaj, aż zacznie działać. Aplikacja jest dostępna po około dwóch minutach (komentarz w `infra/azure/vm.sh`).

   ```bash
   infra/azure/vm.sh start
   ```

2. Tylko przy pierwszym uruchomieniu skopiuj `infra/azure` na maszynę i uruchom skrypt konfiguracyjny jako root. Dodaje on swap, instaluje Dockera i Tailscale, tworzy `/opt/rag`, kopiuje tam pliki compose oraz `deploy.sh` i `backup.sh` i podpina codzienną kopię zapasową w `/etc/cron.daily` (`infra/azure/setup-vm.sh`). Skrypt można uruchomić ponownie.

   ```bash
   scp -r infra/azure <user>@<vm-ip>:rag-setup
   ssh <user>@<vm-ip> 'sudo bash rag-setup/setup-vm.sh'
   ```

3. Na maszynie dokończ to, co skrypt zostawia Tobie (wypisane na jego końcu): wyloguj się i zaloguj ponownie, aby zaczęła obowiązywać grupa `docker`, dołącz do tailnetu i utwórz `.env` z szablonu.

   ```bash
   sudo tailscale up --ssh --advertise-tags=tag:vm
   cp /opt/rag/env.example /opt/rag/.env && nano /opt/rag/.env
   ```

   Uzupełnij `DOMAIN` (publiczna nazwa maszyny), `REGISTRY` (`ghcr.io/<github-owner-in-lowercase>/<repo-name>`), `PC_HOST` (adres IP Tailscale Twojego komputera PC) i `POSTGRES_PASSWORD`. Do wygenerowania hasła `infra/azure/env.example` podpowiada:

   ```bash
   openssl rand -base64 24 | tr -d '/+='
   ```

   Pozostałe klucze (`CLASSIFIER_MODEL`, `ENHANCE_MODEL`, `ENVIRONMENT`, `COOKIE_SECURE`, `SESSION_TTL_HOURS`) mają wartości domyślne w szablonie; zob. [Runtime i wdrożenie](../reference/runtime-and-deploy.md).

4. Na komputerze PC pobierz do Ollamy modele, których używa backend na maszynie: modele wskazane w `CLASSIFIER_MODEL` i `ENHANCE_MODEL` (`ollama pull`, jak podaje `infra/azure/env.example`) oraz `bge-m3` dla embeddingów (komentarz przy usłudze `worker` w `docker-compose.yml`).

5. Na komputerze PC uruchom usługi obliczeniowe i opublikuj ich porty w tailnecie. Używaj tego zamiast zwykłego `docker compose up` za każdym razem, gdy `ollama` lub `languagetool` są budowane albo tworzone od nowa (`infra/ts-serve.sh`).

   ```bash
   infra/ts-serve.sh up
   ```

   Jeśli kontenery już działają, a maszyna ich nie osiąga, uruchom `infra/ts-serve.sh fix`.

6. Na maszynie wykonaj wdrożenie. Skrypt pobiera obrazy, uruchamia stos (usługa `migrate` najpierw wykonuje migracje) i czeka do 180 s na każdą z usług `rag-backend`, `worker` i `frontend`, aż zgłoszą dobry stan (`infra/azure/deploy.sh`).

   ```bash
   cd /opt/rag
   ./deploy.sh <IMAGE_TAG>
   ```

   Tag jest zapisywany w `.env`, więc po restarcie maszyny startuje to samo wydanie. Bez argumentu wdrażany jest ponownie tag już zapisany w `.env`, co pobiera też `latest`. Jeśli któraś usługa nie osiągnie dobrego stanu, skrypt wypisuje jej ostatnie 40 linii logu i kończy działanie z błędem.

7. Aby wdrożyć z GitHuba zamiast z powłoki maszyny, uruchom ręcznie workflow `Deploy` (Actions, Deploy, Run workflow). Opcjonalnie uruchamia on CI, buduje i wypycha oba obrazy z tagami `sha-<7 characters of the commit>` i `latest`, kopiuje `docker-compose.yml`, `Caddyfile`, `env.example`, `deploy.sh` i `backup.sh` do `/opt/rag` przez Tailscale SSH, uruchamia `/opt/rag/deploy.sh <tag>` i wysyła żądania do `/api/v1/health` oraz `/` pod `APP_URL`. Wejścia `run_tests` i `deploy` wyłączają uruchomienie CI i krok na maszynie (`.github/workflows/deploy.yml`). Maszyna musi już działać w chwili uruchomienia workflow.

8. Po pierwszym wdrożeniu utwórz użytkownika administratora jednorazową usługą `cli` (komentarz w `infra/azure/docker-compose.yml`).

   ```bash
   cd /opt/rag
   docker compose --profile tools run --rm cli create-admin --email <email> --name <name>
   ```

   Aby zaimportować winiety, umieść pliki w `/opt/rag/import` i uruchom `docker compose --profile tools run --rm cli import-vignettes --dir /import/vignettes --whatifs /import/chip_whatifs.json --admin-email <email>`.

9. Wykonaj kopię zapasową bazy danych. Codzienna kopia uruchamia się z `/etc/cron.daily` (anacron uruchamia ją także po restarcie). Aby wykonać zrzut ręcznie, uruchom skrypt jako root na maszynie:

   ```bash
   sudo /opt/rag/backup.sh
   ```

   Zrzut trafia do `/var/backups/rag/rag-<date>.dump`; zrzuty starsze niż 7 dni są usuwane. Jeśli kopia się nie powiedzie, przeczytaj dziennik:

   ```bash
   journalctl -t rag-backup
   ```

10. Aby zatrzymać maszynę, zdealokuj ją ze swojego komputera PC. Tylko stan `deallocated` zatrzymuje naliczanie opłat za moc obliczeniową (`infra/azure/vm.sh`).

    ```bash
    infra/azure/vm.sh stop
    ```

## Sprawdź wynik

- `infra/azure/vm.sh status` wypisuje `rag-vm: <power state>`.
- `./deploy.sh` wypisuje `<service> is healthy` dla `rag-backend`, `worker` i `frontend`, a następnie `docker compose ps`.
- Test dymny workflow wysyła żądania do `${{ vars.APP_URL }}/api/v1/health` i `${{ vars.APP_URL }}/` (`.github/workflows/deploy.yml`); workflow czyta `APP_URL` z kontekstu `vars` GitHuba.
- Caddy obsługuje witrynę pod `DOMAIN` i przekazuje ruch do `frontend`, więc `curl -fsS https://<DOMAIN>/api/v1/health` wysyła żądanie do endpointu sprawdzenia stanu `rag-backend` przez Caddy i nginx.
- `infra/ts-serve.sh status` wypisuje reguły `tailscale serve` oraz kod HTTP lokalnych portów 11434 i 8010.

## Zobacz także

- [Runtime i wdrożenie](../reference/runtime-and-deploy.md): usługi compose, limity, klucze środowiska i skrypty.
- [Backend core API](../reference/backend-core-api.md): polecenia `create-admin` i `import-vignettes`.
- [Architektura](../explanation/architecture.md)

## Źródła w kodzie

- `infra/azure/vm.sh` - uruchamianie, zatrzymywanie i status maszyny, nazwy zapisane na stałe
- `infra/azure/setup-vm.sh` - konfiguracja przy pierwszym uruchomieniu i polecenia dalszych kroków, które wypisuje
- `infra/azure/env.example` - klucze środowiska i polecenie generujące hasło
- `infra/azure/deploy.sh` - skrypt wdrożenia, obsługa tagu, oczekiwanie na dobry stan usług
- `infra/azure/backup.sh` - codzienny zrzut, retencja, tag dziennika
- `infra/azure/docker-compose.yml` - usługi, sprawdzenia stanu, jednorazowe polecenia `cli`
- `infra/azure/Caddyfile` - TLS dla DOMAIN, porty 80 i 443
- `infra/ts-serve.sh` - publikowanie Ollamy i LanguageTool przez tailscale serve
- `docker-compose.yml` - usługi obliczeniowe na komputerze PC i wymaganie bge-m3
- `.github/workflows/deploy.yml` - workflow budowania, wypychania i wdrożenia
