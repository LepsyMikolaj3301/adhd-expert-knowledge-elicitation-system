---
title: Środowisko uruchomieniowe i wdrożenie
diataxis: reference
---

# Środowisko uruchomieniowe i wdrożenie

Język: **Polski** · [English](../../eng/reference/runtime-and-deploy.md)

Strona opisuje pliki, które uruchamiają stos: lokalny plik compose i plik compose maszyny wirtualnej Azure, pliki Dockerfile, metadane pakietu backendu, konfigurację bazy danych i migracje, loader promptów wraz z plikami promptów oraz skrypty z katalogu `scripts/`.

## Stos lokalny: `docker-compose.yml`

### Usługi

| Usługa | Profil | Obraz lub build | Porty hosta | Rola |
|---|---|---|---|---|
| `ollama` | brak | `ollama/ollama:latest` | `127.0.0.1:11434` | Serwer LLM; wolumen modeli to `${OLLAMA_DATA_PATH:-ollama-data}`; rezerwacja GPU (`driver: nvidia`, `count: all`) jest aktywna w pliku |
| `languagetool` | brak | `erikvl87/languagetool:6.8` | `127.0.0.1:8010` | Sprawdzanie gramatyki; `Java_Xms` 512m, `Java_Xmx` 1g |
| `postgres` | brak | `pgvector/pgvector:pg16` | `5432` | Baza danych; dane w wolumenie `postgres-data`; sprawdzenie stanu `pg_isready` |
| `dev` | brak | build `.devcontainer/Dockerfile` | brak | Przestrzeń robocza dewelopera, `command: sleep infinity`, repozytorium zamontowane w `/workspace`, rezerwacja GPU, `PYTHONPATH=/workspace/backend` |
| `pgadmin` | `tools` | `dpage/pgadmin4:latest` | `${PGADMIN_HOST_PORT:-5050}` -> 80 | Interfejs webowy Postgresa; tryb serwerowy wyłączony, hasło główne wyłączone |
| `migrate` | `app` | build `backend/Dockerfile` | brak | Jednorazowe `alembic upgrade head`; czeka na `postgres` w stanie healthy |
| `rag-backend` | `app` | build `backend/Dockerfile` | `8000` | API; czeka na `postgres` w stanie healthy, na zakończenie `migrate` oraz na start `ollama` |
| `worker` | `app` | build `backend/Dockerfile` | brak | `python -m app.jobs.worker`; montuje `./prompts` w `/workspace/prompts` i `./config` w `/workspace/config`, oba tylko do odczytu; czeka na `postgres`, `migrate`, `ollama`, `languagetool` |
| `frontend` | `app` | build `./frontend`, target `dev` | `5173` | Serwer deweloperski Vite; `VITE_API_PROXY_TARGET=http://rag-backend:8000`; `node_modules` w nazwanym wolumenie |
| `playwright` | `browser` | `mcr.microsoft.com/playwright/mcp:latest` | brak (`expose: 8931`) | Przeglądarka headless dla Playwright MCP; polecenie `--host 0.0.0.0 --port 8931 --allowed-hosts *` |
| `frontend-preview` | `preview` | build `./frontend` z `infra/frontend.Dockerfile` | `8080` | Produkcyjny obraz nginx; `PORT=8080`, `API_UPSTREAM_URL=http://rag-backend:8000`, `API_HOST=rag-backend` |

Nazwane wolumeny: `frontend-node-modules`, `ollama-data`, `postgres-data`, `pgadmin-data`, `uv-cache`, `hf-cache`, `claude-config`.

### Polecenia startowe

| Polecenie | Uruchamia |
|---|---|
| `docker compose up -d` | `ollama`, `languagetool`, `postgres`, `dev` |
| `docker compose --profile app up` | dodaje `migrate`, `rag-backend`, `worker`, `frontend` |
| `docker compose --profile tools up -d pgadmin` | dodaje `pgadmin` |
| `docker compose --profile app --profile browser up -d` | dodaje `playwright` |
| `docker compose --profile preview up -d --build frontend-preview` | `frontend-preview` (szuka backendu przy każdym żądaniu; nic nie porządkuje kolejności startu) |

Przewodnik krok po kroku znajduje się w [Uruchomienie stosu lokalnie](../tutorials/run-the-stack-locally.md).

## Stos maszyny wirtualnej Azure: `infra/azure/docker-compose.yml`

Stos działa bez Ollamy i LanguageTool: backend łączy się z nimi na maszynie `PC_HOST` (`http://${PC_HOST}:11434` i `http://${PC_HOST}:8010`). Limity pamięci sumują się do około 2 GB, co jest dobrane do maszyny wirtualnej z 4 GB.

| Usługa | Profil | Obraz | Porty | Limity | Sprawdzenie stanu |
|---|---|---|---|---|---|
| `caddy` | brak | `caddy:2-alpine` | `80`, `443` | 64m, 0,5 CPU | brak; czeka na `frontend` w stanie healthy |
| `frontend` | brak | `${REGISTRY}/frontend:${IMAGE_TAG:-latest}` | nieopublikowane | 64m, 0,5 CPU | `wget` na `http://127.0.0.1:8080/healthz` co 15 s |
| `rag-backend` | brak | `${REGISTRY}/backend:${IMAGE_TAG:-latest}` | nieopublikowane | 512m, 1,0 CPU | Python `urlopen` na `http://127.0.0.1:8000/api/v1/health` co 15 s |
| `worker` | brak | ten sam obraz backendu; polecenie `python -m app.jobs.worker` | brak | 512m, 1,0 CPU | przechodzi, gdy `/tmp/worker-alive` został zmodyfikowany w ciągu 60 s |
| `migrate` | brak | ten sam obraz backendu; polecenie `alembic upgrade head` | brak | 384m | brak; `restart: "no"` |
| `postgres` | brak | `pgvector/pgvector:pg16` | nieopublikowane | 768m, 1,0 CPU | `pg_isready -U rag -d rag` co 5 s |
| `cli` | `tools` | ten sam obraz backendu; entrypoint `python -m app.cli` | brak | 384m | brak; montuje `./import` w `/import` tylko do odczytu |

- `rag-backend` i `worker` czekają na `postgres` w stanie healthy i na zakończenie `migrate`; `migrate` czeka na `postgres` w stanie healthy.
- Postgres startuje z `shared_buffers=128MB`, `max_connections=30`, `work_mem=8MB`.
- Wspólna kotwica `logging` (json-file, `max-size` 10m, `max-file` 3) obejmuje siedem usług: `caddy`, `frontend` i `postgres` ustawiają ją bezpośrednio, a `rag-backend`, `worker`, `migrate` i `cli` dziedziczą ją z `x-backend`.
- Wolumeny: `postgres-data`, `caddy-data` (certyfikat TLS), `caddy-config`.
- Jednorazowe polecenia `cli` to `create-admin`, `import-vignettes` i `recompute-agreement`; komentarze w pliku compose pokazują `docker compose --profile tools run --rm cli create-admin --email ... --name ...` oraz `... cli import-vignettes --dir /import/vignettes --whatifs /import/chip_whatifs.json --admin-email ...`. Same polecenia są wypisane w [Backend core API](backend-core-api.md).

Środowisko usług z obrazem backendu (`x-backend`):

| Zmienna | Wartość |
|---|---|
| `DATABASE_URL` | `postgresql://rag:${POSTGRES_PASSWORD}@postgres:5432/rag` |
| `ENVIRONMENT` | `${ENVIRONMENT:-production}` |
| `COOKIE_SECURE` | `${COOKIE_SECURE:-true}` |
| `SESSION_TTL_HOURS` | `${SESSION_TTL_HOURS:-12}` |
| `OLLAMA_BASE_URL` | `http://${PC_HOST}:11434` |
| `LANGUAGETOOL_URL` | `http://${PC_HOST}:8010` |
| `CLASSIFIER_MODEL`, `ENHANCE_MODEL` | `${...:-qwen3.5:9b}` |
| `REQUIRE_COMPUTE` | `"true"` (na stałe w pliku) |

`frontend` otrzymuje `PORT=8080`, `API_UPSTREAM_URL=http://rag-backend:8000` i `API_HOST=rag-backend`.

### `infra/azure/Caddyfile`

Adres witryny `{$DOMAIN}`; dyrektywy `encode gzip` i `reverse_proxy frontend:8080`. Caddy sam żąda certyfikatu TLS; komentarz stwierdza, że porty 80 i 443 muszą być otwarte na internet.

### `infra/azure/env.example`

| Klucz | Wartość w szablonie |
|---|---|
| `DOMAIN` | pusty; publiczna nazwa maszyny wirtualnej |
| `REGISTRY` | `ghcr.io/owner/repo` |
| `IMAGE_TAG` | `latest` |
| `PC_HOST` | pusty; adres IP w Tailscale komputera, na którym działają Ollama i LanguageTool |
| `POSTGRES_PASSWORD` | pusty |
| `CLASSIFIER_MODEL`, `ENHANCE_MODEL` | `qwen3.5:9b` |
| `ENVIRONMENT`, `COOKIE_SECURE`, `SESSION_TTL_HOURS` | `production`, `true`, `12` |

### Skrypty maszyny wirtualnej

| Skrypt | Uruchamiany na | Co robi |
|---|---|---|
| `infra/azure/vm.sh start\|stop\|status` | komputer dewelopera (wymaga `az`, zalogowanego) | `az vm start`, `az vm deallocate` albo samo zapytanie o stan zasilania maszyny `rag-vm` w grupie zasobów `rag-rg`, w subskrypcji o nazwie `Azure for Students`; wypisuje `rag-vm: <state>` |
| `infra/azure/setup-vm.sh` | maszyna wirtualna, jako root | Dodaje plik `/swapfile` o rozmiarze 2 GB i `vm.swappiness=10`; instaluje Dockera i Tailscale, jeśli brakuje; instaluje `unattended-upgrades` i `anacron`; tworzy `/opt/rag` i `/opt/rag/import`; kopiuje tam `docker-compose.yml`, `Caddyfile`, `env.example`, `deploy.sh`, `backup.sh`; dowiązuje `/opt/rag/backup.sh` do `/etc/cron.daily/rag-backup` |
| `infra/azure/deploy.sh [IMAGE_TAG]` | maszyna wirtualna, w `/opt/rag` | Wymaga `.env`; przy tagu pasującym do `^[A-Za-z0-9._-]+$` zapisuje `IMAGE_TAG` w `.env`; uruchamia `docker compose pull --quiet`, potem `docker compose up -d --remove-orphans`; czeka do 180 s na każdą z usług `rag-backend`, `worker` i `frontend`, aż zgłoszą stan healthy (przy błędzie wypisuje ostatnie 40 linii logu); uruchamia `docker image prune -f`; wypisuje `docker compose ps` |
| `infra/azure/backup.sh` | maszyna wirtualna, jako root (codziennie) | Uruchamia `docker compose exec -T postgres pg_dump -U rag -Fc rag` w `${RAG_DIR:-/opt/rag}` do `/var/backups/rag/rag-<date>.dump` (katalog z uprawnieniami 700); loguje do dziennika pod tagiem `rag-backup`; kasuje pliki `rag-*.dump` starsze niż 7 dni |
| `infra/ts-serve.sh up [service...]\|fix\|status` | komputer dewelopera (WSL) | Resetuje `tailscale serve`, uruchamia `docker compose up -d` (odtwarza `ollama` i `languagetool`, gdy nie odpowiadają na `127.0.0.1`), czeka, aż odpowiedzą `:11434/api/version` i `:8010/v2/languages`, po czym udostępnia porty TCP 11434 i 8010 przez `tailscale serve --bg --tcp`; `fix` odtwarza obie usługi i udostępnia je ponownie; `status` wypisuje `tailscale serve status` i kod HTTP każdego lokalnego portu |

Kolejność kroków opisuje [Jak wdrożyć na maszynę wirtualną Azure](../how-to/deploy-to-azure-vm.md).

## Obrazy

| Plik | Baza | Kontekst builda | Uwagi |
|---|---|---|---|
| `backend/Dockerfile` | `python:3.12-slim` | katalog główny repozytorium | Obraz deweloperski; pakiety apt `git`, `ca-certificates`, `tesseract-ocr` (`eng`, `pol`), `libgl1`, `libglib2.0-0`; `uv sync --frozen --package rag-backend --no-default-groups` do `/opt/venv`; użytkownik `vscode` (uid 1000); kopiuje `backend`, `prompts`, `config`; `EXPOSE 8000`; `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` |
| `infra/backend.Dockerfile` | `python:${PYTHON_VERSION}-slim` (3.12) | katalog główny repozytorium | Produkcyjny obraz API, dwa etapy; `uv sync ... --no-editable`; użytkownik systemowy `app`; `ENVIRONMENT=production`, `PORT=8000`; `CMD` uruchamia uvicorn na `${PORT}` z `--proxy-headers --forwarded-allow-ips='*'`, bez reloadu; migracje nie są uruchamiane w obrazie |
| `frontend/Dockerfile` | `node:${NODE_VERSION}-slim` (24) | `frontend/` | Obraz deweloperski, etap `dev`; użytkownik `node`; `EXPOSE 5173`; `CMD npm install && exec npm run dev` |
| `infra/frontend.Dockerfile` | build `node:${NODE_VERSION}-slim` (24), uruchomienie `nginx:1.28-alpine` | `frontend/` | `npm ci`, `npm run build`; kopiuje `nginx/default.conf.template` i `dist`; wartości domyślne `PORT=8080`, `API_UPSTREAM_URL=http://rag-backend:8000`, `API_HOST=rag-backend`, `NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1` |

`docker build -f infra/backend.Dockerfile -t rag-backend .` buduje produkcyjny obraz API; `docker build -f infra/frontend.Dockerfile -t rag-frontend frontend/` buduje produkcyjny obraz webowy. Oba polecenia są zapisane w nagłówkach plików Dockerfile.

## Pakiety Pythona

| Plik | Zawartość |
|---|---|
| `backend/pyproject.toml` | Pakiet `rag-backend` 0.1.0, `requires-python >=3.12`, `[tool.uv] package = false`; zależności `fastapi>=0.115`, `uvicorn[standard]>=0.32`, `asyncpg>=0.30`, `pgvector>=0.3`, `pydantic-settings>=2.6`, `httpx>=0.27`, `numpy>=2.0`, `sqlalchemy[asyncio]>=2.0`, `alembic>=1.14`, `argon2-cffi>=23.1`, `email-validator>=2.2`, `pyyaml>=6.0`, `wordfreq>=3.1`, `expert-knowledge-core`, `expert-knowledge-rag` (oba `workspace = true`) |
| `pyproject.toml` | Wirtualny workspace `rag-workspace` 0.0.0; członkowie `backend` i `packages/*`; `default-groups = ["dev", "notebooks", "scripts"]`; grupy `dev` (pytest, pre-commit, ruff, ty, pytest-asyncio, pytest-cov), `notebooks` (ipykernel, ipywidgets, jupyterlab), `scripts` (prompt-toolkit, pyyaml, langchain-ollama), `experiments` (pusta); ruff `line-length = 100`, reguły `E, F, I, UP, B, ASYNC, SIM`; pytest `testpaths`, `pythonpath`, `asyncio_mode = "auto"` i znaczniki `integration`, `regression`, `scale` |

Polecenia testowe opisuje [Jak uruchomić testy i kontrole](../how-to/run-tests-and-checks.md).

## Konfiguracja bazy danych

Usługa `postgres` nie montuje żadnego pliku SQL; tabele pochodzą z poniższych migracji Alembica, a migracja 0003 tworzy rozszerzenie `vector`.

### Alembic

| Plik | Zawartość |
|---|---|
| `backend/alembic.ini` | `script_location = %(here)s/migrations`; `file_template = %%(rev)s_%%(slug)s`; logowanie na stderr |
| `backend/migrations/env.py` | Tworzy schemat `app`, jeśli go brak; autogenerate obejmuje wyłącznie schemat `app` (`include_name`); tabela wersji jest przechowywana w schemacie `app`; URL z opcji `sqlalchemy.url` lub z `settings.database_url`, konwertowany przez `to_async_url` |

Schemat `chips` nie jest generowany automatycznie; schemat `chips` tworzy migracja 0003 zwykłym SQL.

### Migracje

Rewizje tworzą jeden łańcuch od `0001` (`down_revision = None`) do `0011`.

| Rewizja | Plik | Zawartość |
|---|---|---|
| 0001 | `0001_initial.py` | Schemat `app`: sekwencja `user_pseudonym_seq` i tabele `users`, `audit_events`, `auth_sessions`, `invites`, `vignettes`, `vignette_versions`, `assignments`, `answer_drafts`, `jobs`, `review_requests`, `submissions`, `knowledge_units`, `unit_decisions` |
| 0002 | `0002_citations.py` | Dodaje `assignments.locked_highlights`; usuwa klucz `quoted_fragments` z `answer_drafts.payload` |
| 0003 | `0003_pipeline.py` | Dodaje `answer_findings`, kolumny jednostek w `knowledge_units`, nullowalne `review_requests.requested_by`; tworzy rozszerzenie `vector` i schemat `chips` z `experts`, `vignettes`, `elicitation_sessions`, `cue_keys`, `highlights`, `answer_sentences`, `finding_units`, `finding_unit_sentences`, `unit_cues`, `review_events` |
| 0004 | `0004_review_rounds.py` | Dodaje `review_round` do `assignments` i `knowledge_units`; dopuszcza status jednostki `superseded` i wartość decyzji `request_changes`; usuwa `knowledge_units.question_id` |
| 0005 | `0005_open_review.py` | Otwarta recenzja: usuwa stan `admin_review`, zamiast `review_requests` tworzy `review_participants`, usuwa `assignments.required_approvals`; dodaje `unit_comments`, `submission_votes`, `users.activity_seen_at` i indeks audytu po akcji |
| 0006 | `0006_proofread.py` | Przepływ korekty: usuwa `assignments.gate_passed_at` i `locked_highlights`; dodaje `proofread_rounds`, `answer_revisions`, `answer_comments`, `answer_votes`, `answer_decisions`; ustawia kolejność stanów przydziału (`processing` po `peer_review`); `expert_check` i `building_units` nie są stanami |
| 0007 | `0007_patient_summary.py` | Dodaje `vignette_versions.patient_summary` (tekst, domyślnie pusty) |
| 0008 | `0008_unit_removal.py` | Dopuszcza status jednostki `removed` i rodzaj zadania `refit`; ustawia `jobs.assignment_id` jako nullowalne |
| 0009 | `0009_drop_synthetic.py` | Usuwa `users.is_synthetic` wraz z jego ograniczeniem check oraz `is_synthetic` z `chips.experts`, `chips.elicitation_sessions`, `chips.finding_units` |
| 0010 | `0010_drop_i3.py` | Usuwa `knowledge_units.embed_text_combined` oraz `chips.finding_units.embed_text_combined`, `embedding_combined`, `sparse_combined` (usunięty tekst I3); downgrade dodaje kolumny z powrotem puste |
| 0011 | `0011_fragment_agreement.py` | Dodaje `chips.fragment_groups`, `chips.fragment_group_members` (dane pochodne: eksperci, którzy zaznaczyli ten sam fragment) i `chips.finding_units.embedding_model` (istniejące wiersze dostają `bge-m3`); downgrade niczego nie usuwa |

`alembic upgrade head` to `command` usługi `migrate` w obu plikach compose.

## Klucze konfiguracji

### `Settings` backendu (`backend/app/settings.py`)

| Klucz | Typ | Wartość domyślna | Opis |
|---|---|---|---|
| `DATABASE_URL` | str | `postgresql://rag:rag@localhost:5432/rag` | DSN Postgresa |
| `OLLAMA_BASE_URL` | str | `http://localhost:11434` | Endpoint Ollamy |
| `REQUIRE_COMPUTE` | bool | `false` | Gdy true, żądanie, które dodałoby zadanie do kolejki, najpierw pyta maszynę obliczeniową i odpowiada 503 `compute_unavailable`, jeśli ta nie jest gotowa |
| `CLASSIFIER_MODEL` | str | `qwen3.5:9b` | Model, który przypisuje zdania bez cytatu (prompt `Expert_sentence_targets.v1`) |
| `ENHANCE_MODEL` | str | `qwen3.5:9b` | Model, który zamienia fragmenty w zdania (prompt `Answer_enhance.v2`); pusta wartość wyłącza ulepszanie |
| `OLLAMA_REQUEST_TIMEOUT` | float | `600` | Liczba sekund, jaką może trwać jedna odpowiedź Ollamy |
| `LANGUAGETOOL_URL` | str | `http://localhost:8010` | Sprawdzanie gramatyki |
| `LANGUAGETOOL_LANGUAGE` | str | `en-US` | Język LanguageTool |
| `LANGUAGETOOL_TIMEOUT` | float | `60` | Sekundy |
| `PROJECT_ROOT` (pole `project_root`) | Path | dwa poziomy nad `backend/app` (katalog główny repozytorium; w obrazach `/workspace`) | Katalog zawierający `prompts/` i `config/` |
| `ENVIRONMENT` | `development` lub `production` | `development` | Każda inna wartość zatrzymuje aplikację przy starcie; `production` wymusza ciasteczko tylko dla HTTPS |
| `COOKIE_SECURE` | bool | `false` | Ciasteczko sesji tylko dla HTTPS |
| `SESSION_TTL_HOURS` | int | `12` | Czas życia sesji |

### Klucze compose i `.env.example`

| Klucz | Wartość domyślna | Używany przez |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `rag`, `rag`, `rag` | `postgres` oraz `DATABASE_URL` budowany dla `dev`, `migrate`, `rag-backend`, `worker` |
| `OLLAMA_DATA_PATH` | nieustawiony (nazwany wolumen `ollama-data`) | montowanie modeli `ollama` |
| `OLLAMA_LOAD_TIMEOUT`, `OLLAMA_KEEP_ALIVE` | `5m`, `5m` | środowisko `ollama` |
| `PGADMIN_HOST_PORT`, `PGADMIN_EMAIL`, `PGADMIN_PASSWORD` | `5050`, `admin@local.dev`, wartość deweloperska w pliku | `pgadmin` |
| `VITE_API_PROXY_TARGET` | `http://rag-backend:8000` w compose | `dev`, `frontend` |

Usługi `dev`, `rag-backend` i `worker` czytają `.env` przez `env_file`; `DATABASE_URL`, `OLLAMA_BASE_URL` i `LANGUAGETOOL_URL` są nadpisywane w pliku compose nazwami hostów z sieci wewnętrznej (`rag-backend` nadpisuje dwie pierwsze).

## Loader promptów: `backend/app/prompts.py`

`scripts/elicitation/prompt_loader.py` reeksportuje z niego `PROMPTS_DIR`, `Prompt`, `PromptError` i `load_prompt`.

### `load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt`

Czyta `<prompts_dir>/<name>.md`; `name` to nazwa pliku bez rozszerzenia, na przykład `Synthetic_expert_answer.v1`. Plik zaczyna się od front matter `---\n` (`key: value` w każdej linii, dzielone na pierwszym dwukropku; wartości zaczynające się od `{` lub `[` są parsowane jako YAML i pozostają ciągami znaków, gdy parsowanie się nie powiedzie), a dalej zawiera sekcje `# System` i `# User` albo sekcję `# Template`. `id` i `version` są czytane z front matter. Zgłasza `PromptError`, gdy brakuje front matter, linia front matter nie ma dwukropka albo nie istnieje ani sekcja `# User`, ani `# Template`; brak klucza `id` lub `version` zgłasza `KeyError`.

### `Prompt`

Zamrożona dataclass: `id: str`, `version: int`, `meta: dict`, `system: str | None`, `user: str` (cały surowy prompt dla pliku `# Template`).

### `Prompt.fill(**variables) -> Prompt`

Usuwa podpowiedź `(e.g. ...)` po placeholderze, zachowuje tekst między `{{IF_VARIANT}}` a `{{END_IF}}` tylko wtedy, gdy `IF_VARIANT` jest prawdziwe, podstawia `{{VAR}}` (nazwy `[A-Z0-9_]+`) i przycina wynik. Zgłasza `PromptError` dla brakującej zmiennej i dla zmiennej, której szablon nie używa.

### Stałe

| Nazwa | Wartość |
|---|---|
| `PROMPTS_DIR` | `settings.project_root / "prompts"` |
| `PromptError` | podklasa `ValueError` |

### Pliki promptów

Backend ładuje dwa prompty: `Expert_sentence_targets.v1` (`backend/app/knowledge/classifier.py`, stała `PROMPT`) i `Answer_enhance.v2` (`backend/app/proofread/enhance.py`, stała `PROMPT`). Pozostałe pliki służą skryptom.

| Rodzina | Pliki (id, wersja) | Cel we front matter |
|---|---|---|
| Teksty person | `Persona_base_fewshot.v1.md` (`persona_base_fewshot`), `Persona_claude.v1.md`, `Persona_claude.v2.md` (`persona_claude`) | model bazowy z surowym uzupełnianiem; Claude |
| Syntetyczne odpowiedzi ekspertów | `Synthetic_expert_answer.v1.md` do `v5.md` (`synthetic_expert_answer`, wersje 1-5) | v1-v3 Claude; v4 Claude (silver) albo model lokalny (bronze); v5 lokalne modele instruct, po jednym na eksperta |
| Persony ekspertów | `expert_personas/E21.v1.md` do `E32.v1.md` (12 plików, `expert_persona`, wersja 1) | model wskazany w każdym pliku |
| Wyszukiwanie jednostek eksperta | `Expert_unit_keys.v1.md`, `Expert_unit_queries.v1.md`, `Expert_unit_pooling.v1.md` (`expert_unit_keys`, `expert_unit_queries`, `expert_unit_pooling`) | model lokalny; Claude; Claude |
| Klasyfikacja zdań | `Expert_sentence_targets.v1.md` (`expert_sentence_targets`) | lokalny model instruct, tryb JSON |
| Ulepszanie odpowiedzi | `Answer_enhance.v1.md`, `Answer_enhance.v2.md` (`answer_enhance`), `Enhance_fidelity_judge.v1.md` (`enhance_fidelity_judge`) | lokalny model instruct; lokalny model instruct; Claude |

## Skrypty

Uruchamiaj z katalogu głównego repozytorium (`scripts/README.md`). Skrypty w jednym katalogu importują się nawzajem po nazwie modułu.

### `scripts/db/`

| Plik | Przeznaczenie |
|---|---|
| `psql.sh` | `psql` w kontenerze `postgres` (albo przez `DATABASE_URL`, gdy brak `docker`); `overview` wypisuje rozszerzenia, rozmiary tabel i szacowane liczby wierszy oraz indeksy schematu `public`; pozostałe argumenty trafiają do `psql` |
| `chips_backup.py` | Tworzy kopię zapasową, sprawdza, odtwarza i opróżnia tabele schematu `chips` przez binarny COPY |
| `chips_schema.sql` | Tabele testu chips z placeholderem `{schema}` |
| `chips_fixture.py` | `export`, `check` i `seed` wypełnionych winiet z `tests/fixtures/scale_answers/`; buduje z nich jednostki, embeduje je i seeduje schemat dla testów integracyjnych |
| `explore_chips.sql` | Przegląd samych SELECT-ów schematu `chips` i tabel `app`, które go zasilają |
| `load_chips_pg.py` | Ładuje zbudowane jednostki chips do schematu (domyślnie `chips_eval`) |
| `seed_silver_reviews.py` | Dane deweloperskie: odpowiedzi silver złożone przez dwóch ekspertów i ocenione w recenzji koleżeńskiej przez dwóch kolejnych |

### `scripts/rag/`

| Plik | Przeznaczenie |
|---|---|
| `judge_generations.py` | Ocena przebiegu generowania ekspertów przez LLM jako sędziego (`eval_expert_generation.py`, `eval_chip_generation.py`) |
| `rag_common.py` | Pomocniki wspólne dla skryptów notatek ekspertów: embedder zapytań i ustawienia BM25 z `config/indexing.yaml`, `OllamaChat`, `write_json`, rubryka sędziego-klinicysty i jej parsery |
| `eval_expert_units.py` | Porównuje sposoby indeksowania odpowiedzi ekspertów, w pamięci |
| `expert_retrieval.py` | Elementy składowe wspólne dla `eval_expert_units.py` i `eval_expert_generation.py` |
| `expert_metrics.py` | Metryki wyszukiwania, tylko numpy |
| `eval_expert_generation.py` | Odpowiada na pytania z notatek ekspertów lokalnym modelem 9B |
| `chat_expert.py` | Czat z generatorem notatek ekspertów i ocena odpowiedzi przez człowieka |
| `try_expert_rag.py` | Uruchamia pakiet `expert-knowledge-rag` od początku do końca: wyszukuje w Postgresie, generuje, zapisuje do oceny |
| `chip_retrieval.py` | Wyszukiwanie wśród jednostek chips |
| `eval_chip_units.py` | Jednostki chips na tle punktu odniesienia B1, tylko wyszukiwanie, w pamięci |
| `eval_chip_generation.py` | Odpowiedzi z notatek chips i z notatek B1 lokalnym modelem |
| `eval_scale_retrieval.py` | Wyszukiwanie w miarę wzrostu liczby ekspertów na winietę, na schemacie `chips_scale` |
| `eval_style_diversity.py` | Jak bardzo różnie piszą eksperci fixture'a skali, przed korektą i po niej |

### `scripts/elicitation/`

| Plik | Przeznaczenie |
|---|---|
| `make_fixtures.py` | Buduje syntetyczne ElicitationDocuments i twierdzenia referencyjne |
| `llm_clients.py` | Źródła generowania tekstu za jednym interfejsem: `OllamaGenerator`, `FileGenerator`, `InboxGenerator`, `CachedGenerator` |
| `prompt_loader.py` | Reeksportuje loader z `backend/app/prompts.py` |
| `leak_terms.py` | Słowa, których winieta nie może zawierać (`LEAK_TERMS`) |
| `export_schema.py` | Zapisuje schemat JSON ElicitationDocument w `data/schemas/elicitation_document.schema.json` |
| `elicitation_schema.py` | Schemat sesji przekazywanej przez platformę webową (`ElicitationDocument`, `ReferenceClaim`) |
| `elicitation_units.py` | Zamienia odpowiedzi ekspertów w jednostki możliwe do wyszukania, bez wywołań modelu |
| `make_unit_keys.py` | Klucze wyszukiwania dla jednostek eksperta lokalnym modelem |
| `chips_schema.py` | Dokumenty chips: wyróżnienia, przełączniki kierunku, chipy `⟦hN⟧` |
| `make_chip_fixtures.py` | Fixture'y chips: wspólne winiety, potem odpowiedzi ekspertów |
| `classify_sentence_targets.py` | Krok 3 potoku chips: lokalny model przypisuje zdania bez chipa |
| `chip_findings.py` | Odpowiedzi chips do jednostek fragmentów, bez modeli; reeksportuje `backend/app/knowledge/findings.py` |
| `build_chip_units.py` | Dokumenty chips i etykiety klasyfikatora do jednostek, kluczy wskazówek i embeddingów |
| `make_scale_fixtures.py` | Lokalny fixture skali: 32 ekspertów, 24 winiety; etapy `seed`, `vignettes`, `answers`, `proofread`, `build` |
| `export_scale_answers.py` | Zapisuje wszystkie odpowiedzi fixture'a skali w jednym pliku JSON (domyślnie `data/exports/scale_answers.json`) |
| `eval_enhance.py` | Porównuje `Answer_enhance` v1 i v2 przy dwóch zestawach kontroli odpowiedzi |

## Źródła w kodzie

- `docker-compose.yml` - lokalne usługi, profile, porty, środowisko, wolumeny
- `backend/Dockerfile` - deweloperski obraz API
- `backend/pyproject.toml` - pakiet backendu i zależności
- `backend/alembic.ini` - ustawienia alembica
- `backend/migrations/env.py` - środowisko alembica, zakres schematu
- `backend/migrations/versions/0001_initial.py` - tabele schematu app
- `backend/migrations/versions/0002_citations.py` - locked_highlights, usunięcie klucza z payload
- `backend/migrations/versions/0003_pipeline.py:1-120,161` - findings, schemat chips, rozszerzenie vector
- `backend/migrations/versions/0004_review_rounds.py:1-10` - rundy recenzji
- `backend/migrations/versions/0005_open_review.py:1-19` - otwarta recenzja
- `backend/migrations/versions/0006_proofread.py:1-24` - przepływ korekty
- `backend/migrations/versions/0007_patient_summary.py` - kolumna patient summary
- `backend/migrations/versions/0008_unit_removal.py` - status removed, rodzaj refit
- `backend/migrations/versions/0009_drop_synthetic.py` - usunięcie flagi synthetic
- `backend/app/settings.py` - klucze Settings i wartości domyślne
- `backend/app/prompts.py` - loader promptów
- `backend/app/knowledge/classifier.py:20,42` - stała promptu klasyfikatora i jej użycie
- `backend/app/proofread/enhance.py:24,96` - stała promptu ulepszania i jej użycie
- `pyproject.toml` - workspace, grupy, ruff, pytest
- `.env.example` - lokalny szablon środowiska
- `infra/backend.Dockerfile` - produkcyjny obraz API
- `infra/frontend.Dockerfile` - produkcyjny obraz webowy
- `frontend/Dockerfile` - deweloperski obraz webowy
- `infra/azure/docker-compose.yml` - stos maszyny wirtualnej
- `infra/azure/Caddyfile` - reverse proxy z TLS
- `infra/azure/env.example` - szablon środowiska maszyny wirtualnej
- `infra/azure/deploy.sh` - skrypt wdrożenia na maszynie wirtualnej
- `infra/azure/backup.sh` - skrypt zrzutu bazy danych
- `infra/azure/setup-vm.sh` - konfiguracja maszyny wirtualnej przy pierwszym starcie
- `infra/azure/vm.sh` - start, stop i status maszyny wirtualnej
- `infra/ts-serve.sh` - Tailscale serve dla Ollamy i LanguageTool
- `prompts/Answer_enhance.v2.md` - id, wersja i cel we front matter (pozostałe pliki promptów mają ten sam układ)
- `scripts/README.md` - zasady uruchamiania i mapa katalogów
- `scripts/db/chips_backup.py:1` - docstring modułu
- `scripts/db/chips_schema.sql:1-7` - komentarz nagłówkowy
- `scripts/db/chips_fixture.py:1-21` - docstring modułu
- `scripts/db/explore_chips.sql:1-6` - komentarz nagłówkowy
- `scripts/db/load_chips_pg.py:1-8` - docstring modułu
- `scripts/db/psql.sh:1-39` - wrapper psql i overview
- `scripts/db/seed_silver_reviews.py:1-2` - docstring modułu
- `scripts/elicitation/build_chip_units.py:1-6` - docstring modułu
- `scripts/elicitation/chip_findings.py:1-6` - docstring modułu
- `scripts/elicitation/chips_schema.py:1-6` - docstring modułu
- `scripts/elicitation/classify_sentence_targets.py:1-6` - docstring modułu
- `scripts/elicitation/elicitation_schema.py:1-6` - docstring modułu
- `scripts/elicitation/elicitation_units.py:1-6` - docstring modułu
- `scripts/elicitation/eval_enhance.py:1-8` - docstring modułu
- `scripts/elicitation/export_scale_answers.py:1-6` - docstring modułu
- `scripts/elicitation/export_schema.py:1-6` - docstring modułu
- `scripts/elicitation/leak_terms.py:1-6` - docstring modułu
- `scripts/elicitation/llm_clients.py:1-6` - docstring modułu
- `scripts/elicitation/make_chip_fixtures.py:1-6` - docstring modułu
- `scripts/elicitation/make_fixtures.py:1-8` - docstring modułu
- `scripts/elicitation/make_scale_fixtures.py:1-12` - docstring modułu
- `scripts/elicitation/make_unit_keys.py:1-6` - docstring modułu
- `scripts/elicitation/prompt_loader.py:1-5` - reeksport
- `scripts/rag/chat_expert.py:1` - docstring modułu
- `scripts/rag/chip_retrieval.py:1` - docstring modułu
- `scripts/rag/eval_chip_generation.py:1` - docstring modułu
- `scripts/rag/eval_chip_units.py:1` - docstring modułu
- `scripts/rag/eval_expert_generation.py:1` - docstring modułu
- `scripts/rag/eval_expert_units.py:1` - docstring modułu
- `scripts/rag/eval_scale_retrieval.py:1-8` - docstring modułu
- `scripts/rag/eval_style_diversity.py:1-6` - docstring modułu
- `scripts/rag/expert_metrics.py:1` - docstring modułu
- `scripts/rag/expert_retrieval.py:1` - docstring modułu
- `scripts/rag/judge_generations.py:1-25` - docstring modułu
- `scripts/rag/rag_common.py:1-8,25-45,90-100` - docstring modułu, pomocniki, rubryka sędziego
- `config/indexing.yaml` - ustawienia embeddera i BM25 czytane przez rag_common
- `scripts/rag/try_expert_rag.py:1-6` - docstring modułu
