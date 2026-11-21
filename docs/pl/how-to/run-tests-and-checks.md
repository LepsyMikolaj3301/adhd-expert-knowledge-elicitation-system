---
title: Jak uruchomić testy i sprawdzenia
diataxis: how-to
---

# Jak uruchomić testy i sprawdzenia

Język: **Polski** · [English](../../eng/how-to/run-tests-and-checks.md)

Skorzystaj z tej strony, gdy chcesz uruchomić testy backendu, testy frontendu, lintery lub sprawdzenia typów, z bazą danych albo bez niej.

## Wymagania wstępne

- `uv` po stronie Pythona oraz Node `^22.18.0 || >=24.12.0` z npm dla frontendu (`frontend/package.json:64-66`). Python to `>=3.12` (`pyproject.toml:5`).
- Dla testów oznaczonych `integration`: działający Postgres z pgvector. Usługa compose `postgres` go zapewnia i publikuje port 5432 (`docker-compose.yml:35-38`). Uruchom ją poleceniem `docker compose up -d postgres`.

## Backend

1. Zainstaluj pakiety workspace'u wyłącznie z grupą `dev`. Domyślne grupy pobierają też notebooki i zależności skryptów (`.github/workflows/ci.yml:21-22`).

   ```bash
   uv sync --frozen --no-default-groups --all-packages --group dev
   ```

2. Uruchom testy, które nie potrzebują bazy danych, modelu ani sieci. W tych testach wszystko, co komunikuje się z Ollamą, jest podmienione (`.github/workflows/ci.yml:26-34`).

   ```bash
   uv run --no-sync pytest -m "not integration" tests/unit tests/scripts tests/test_*.py packages/expert-knowledge-core/tests packages/expert-knowledge-rag/tests
   ```

   Aby uruchomić testy z pokryciem dla `backend/app` i obu pakietów, dodaj opcje wskazane w `pyproject.toml:68-72`:

   ```bash
   uv run pytest -m "not integration" --cov --cov-report=term-missing
   ```

3. Uruchom testy, które potrzebują Postgresa.

   ```bash
   uv run pytest -m integration
   ```

   Źródło bazy danych zależy od katalogu z testami:

   - `tests/api` (każdy test w tym katalogu jest oznaczony `integration` przez `tests/api/conftest.py:38-42`). Testy łączą się z serwerem z `DATABASE_URL`, który przy nieustawionej zmiennej ma wartość domyślną `postgresql://rag:rag@localhost:5432/rag` (`backend/app/settings.py:8`). Każde uruchomienie tworzy własną bazę `rag_<pid>_test`, stosuje migracje Alembic i na końcu usuwa bazę (`tests/api/conftest.py:1-6`, `31-33`, `75-84`). Aby użyć własnej bazy, ustaw `TEST_DATABASE_URL`; jej nazwa musi kończyć się na `_test`, w przeciwnym razie uruchomienie zatrzymuje się z komunikatem "refusing to run against a non-test database" (`tests/api/conftest.py:30-35`).
   - `tests/integration` (regresja wyszukiwania). Testy w trakcie uruchomienia wykonują ingestię wypełnionych winiet z `tests/fixtures/scale_answers`, więc wymagają `DATABASE_URL` z Postgresem, który odpowiada na `SELECT '[1,2]'::vector`, oraz Ollamy z `bge-m3` (`tests/integration/conftest.py:31-52`). Bez nich testy są pomijane, chyba że uruchomienie wybiera je przez `-m regression` albo `-m scale`: wtedy kończą się błędem (`tests/integration/conftest.py:24-28`). W kontenerze dev zmienna wskazuje Postgresa z compose (`docker-compose.yml:121`). Na hoście wyeksportuj ją, na przykład z wartością z `.env.example:9`.
   - `packages/expert-knowledge-rag/tests/integration` wymaga `DATABASE_URL` i pliku `scripts/db/chips_schema.sql`; testy na odpowiedziach silver wymagają też Ollamy z `bge-m3`. Bez nich testy są pomijane (`packages/expert-knowledge-rag/tests/integration/conftest.py:108-118`, `152-162`).

4. Wybierz testy jakości wyszukiwania za pomocą ich znaczników (`pyproject.toml:59-63`). Działają tylko lokalnie; CI uruchamia `-m "not integration"`.

   ```bash
   uv run pytest -m regression
   ```

   - `tests/fixtures/scale_answers` zawiera tylko to, co istnieje przed ingestią: dokumenty chips 32 ekspertów po korekcie, ich twierdzenia (claims), powiązania zdań nadane przez klasyfikator, opisy ról i 40 pytań oznaczonych twierdzeniami SYN-001 i SYN-002 (`scripts/db/chips_fixture.py:1-21`). Wektory nie są przechowywane.
   - Testy `regression` z `tests/integration/test_retrieval_regression.py` i `tests/integration/test_ingest_e2e.py` wykonują ingestię odpowiedzi SYN-001 i SYN-002 (198 jednostek) do tymczasowego schematu; około 30 s. Regresja wyszukiwania sprawdza progi bezwzględne i wynik bazowy w `tests/fixtures/retrieval_regression/baseline.json`, który podaje skrót fixture i model embeddingów; inny skrót lub model kończy się błędem, dopóki nie zapiszesz nowego wyniku bazowego przez `UPDATE_RETRIEVAL_BASELINE=1 uv run pytest -m regression -s`.
   - Testy `scale` (`tests/integration/test_scale_regression.py:35`) wykonują ingestię wszystkich 32 ekspertów (1830 jednostek); około 2 minut. Nowy wynik bazowy zapisuje `UPDATE_SCALE_BASELINE=1 uv run pytest -m scale -s`. Testy `scale` mają też znacznik `regression`; wyłącz je opcją `-m "regression and not scale"`.

5. Sprawdź styl i typy backendu.

   ```bash
   uv run --no-sync ruff check backend
   uv run --no-sync ruff format --check backend
   uv run --no-sync ty check backend
   ```

   Ruff używa długości linii 100 oraz zestawów reguł E, F, I, UP, B, ASYNC i SIM (`pyproject.toml:45-51`). Hooki pre-commit uruchamiają te same sprawdzenia Ruff i ty dla `backend/` przy commicie (`.pre-commit-config.yaml:12-28`).

6. Aby uruchomić jeden plik lub jeden test, przekaż jego ścieżkę do pytest.

   ```bash
   uv run pytest tests/unit/test_db_url.py
   ```

## Frontend

Uruchamiaj te polecenia z katalogu `frontend/`.

1. Zainstaluj zablokowane zależności.

   ```bash
   npm ci
   ```

2. Uruchom lintery bez przepisywania plików, tak jak robi to CI (`.github/workflows/ci.yml:50-51`).

   ```bash
   npx oxlint .
   npx eslint .
   ```

   `npm run lint` uruchamia oba z `--fix`, więc może zmieniać pliki (`frontend/package.json:15-17`). `npm run format` zapisuje formatowanie Prettier w `src/` (`frontend/package.json:18`).

3. Sprawdź typy.

   ```bash
   npm run type-check
   ```

   Skrypt to `vue-tsc --build` (`frontend/package.json:13`).

4. Uruchom testy jednostkowe jednorazowo.

   ```bash
   npm run test:unit -- --run
   ```

   Specyfikacje leżą w `frontend/src/__tests__/*.spec.ts`. Vitest uruchamia je w jsdom i pomija `e2e/**` (`frontend/vitest.config.ts:8-10`). Bez `--run` skrypt uruchamia zwykły `vitest` (`frontend/package.json:10`). Zadanie CI nie uruchamia dla tych testów żadnej bazy danych ani usługi API (`.github/workflows/ci.yml:36-54`).

   Aby uruchomić jedną specyfikację, dodaj jej ścieżkę:

   ```bash
   npm run test:unit -- --run src/__tests__/router.spec.ts
   ```

5. Jeśli chcesz uzyskać pokrycie, uruchom `npm run test:cov`. Skrypt wykonuje `vitest run --coverage --maxWorkers=2`. Raport obejmuje `src/**` bez `src/api/schema.d.ts` i `src/__tests__/**` i jest wypisywany jako `text-summary` oraz `text` (`frontend/package.json:11`; `frontend/vitest.config.ts:12-17`).

6. Sprawdź, czy aplikacja się buduje.

   ```bash
   npm run build-only
   ```

   `npm run build` uruchamia równolegle `type-check` i `build-only` (`frontend/package.json:8`).

## Sprawdź wynik

pytest zgłasza pominięte testy jako pominięte, z powodem podanym w plikach conftest wskazanych powyżej: brak bazy danych lub brak snapshotu oznacza pominięcie, a nie błąd.

## Zobacz także

- [Runtime i wdrożenie](../reference/runtime-and-deploy.md) - usługa Postgres, porty i zmienne środowiskowe
- [Uruchomienie stosu lokalnie](../tutorials/run-the-stack-locally.md) - uruchomienie usług compose
- [Aplikacja frontendowa](../reference/frontend-app.md) - co obejmują testy frontendu

## Źródła w kodzie

- `pyproject.toml:1-77` - grupa dev, Ruff, ty, znaczniki pytest, testpaths, polecenie z pokryciem
- `backend/pyproject.toml:1-30` - pakiet backendu i źródła workspace'u
- `.github/workflows/ci.yml:1-54` - polecenia sprawdzeń backendu i frontendu
- `.pre-commit-config.yaml:12-28` - hooki Ruff i ty
- `docker-compose.yml:35-51` - usługa postgres i opublikowany port
- `backend/app/settings.py:8` - domyślny DATABASE_URL
- `tests/api/conftest.py:1-84` - własna baza testowa, TEST_DATABASE_URL, znacznik integration, pominięcie, gdy Postgres jest nieosiągalny
- `tests/integration/conftest.py:27-105` - wymaganie DATABASE_URL, snapshoty silver i scale
- `packages/expert-knowledge-rag/tests/integration/conftest.py:120-127` - wymaganie DATABASE_URL i chips_schema.sql
- `tests/integration/test_scale_regression.py:26` - znacznik scale
- `tests/unit/test_db_url.py:1-14` - przykład pliku testowego uruchamianego osobno
- `frontend/package.json:6-19,64-66` - skrypty npm i wersje Node
- `frontend/vitest.config.ts:1-20` - jsdom, wykluczone katalogi, ustawienia pokrycia
