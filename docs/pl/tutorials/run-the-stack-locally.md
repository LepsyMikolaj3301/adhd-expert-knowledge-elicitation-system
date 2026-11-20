---
title: Uruchomienie stosu lokalnie
diataxis: tutorial
---

# Uruchomienie stosu lokalnie

Język: **Polski** · [English](../../tutorials/run-the-stack-locally.md)

W tym samouczku uruchamiasz bazę danych, magazyn obiektów, API i aplikację webową za pomocą Docker Compose, wysyłasz pierwsze żądanie do API, tworzysz konto administratora i logujesz się do aplikacji webowej. Jak te części współpracują, opisuje strona [Architektura](../explanation/architecture.md).

## Zanim zaczniesz

- Docker z wtyczką Compose (`docker compose`). Każde polecenie poniżej uruchamiasz z katalogu głównego repozytorium, w którym leży `docker-compose.yml`.
- Host, który potrafi uruchomić usługę `ollama`: plik rezerwuje dla niej wszystkie karty NVIDIA (`docker-compose.yml:16-23`), a usługa `rag-backend` czeka na start `ollama`. Usługa `dev` ma taką samą rezerwację i komentarz, że wymaga NVIDIA Container Toolkit (`docker-compose.yml:135-142`).
- Wolne porty hosta 5432 (Postgres), 9000 i 9001 (MinIO), 11434 (Ollama), 8000 (API) i 5173 (aplikacja webowa) (`docker-compose.yml:7`, `38`, `77-79`, `183`, `249`).

Ten samouczek nie uruchamia ani usługi `worker`, ani LanguageTool, więc nie musisz pobierać żadnego modelu Ollama.

## 1. Utwórz plik środowiska

```bash
cp .env.example .env
```

Usługa `rag-backend` czyta `.env` przez `env_file` (`docker-compose.yml:184-185`), więc plik musi istnieć. Szablon zawiera lokalne wartości domyślne: użytkownika, hasło i bazę Postgresa `rag`, `ENVIRONMENT=development` oraz `COOKIE_SECURE=false` (`.env.example:1-4`, `13`, `16`). Zostaw go bez zmian.

## 2. Uruchom API i aplikację webową

```bash
docker compose --profile app up -d --build rag-backend frontend
```

Compose buduje obrazy `backend/Dockerfile` i `frontend/Dockerfile` (cel `dev`) i uruchamia obie usługi razem z tym, od czego zależą: `postgres`, `minio`, `minio-init`, `ollama` i `migrate` (`docker-compose.yml:159-206`, `243-258`).

- `postgres` przy pierwszym starcie wykonuje `backend/db/init.sql` (`docker-compose.yml:45`).
- `minio-init` tworzy bucket S3 i użytkownika aplikacji, po czym kończy działanie (`docker-compose.yml:93-110`).
- `migrate` wykonuje `alembic upgrade head`, po czym kończy działanie (`docker-compose.yml:159-174`).
- `rag-backend` startuje dopiero po zakończeniu `migrate` i `minio-init` (`docker-compose.yml:197-206`).

Pierwsze budowanie trwa dłuższą chwilę: obraz API instaluje zależności Pythona przez `uv sync`, a kontener frontendu wykonuje `npm install`, zanim uruchomi Vite (`backend/Dockerfile:29`, `frontend/Dockerfile:17`).

## 3. Sprawdź działające usługi

```bash
docker compose --profile app ps -a
```

Widzisz `postgres`, `minio`, `ollama`, `rag-backend` i `frontend` jako działające, a `migrate` i `minio-init` jako zakończone, bo obie to usługi jednorazowe (`restart: "no"`, `docker-compose.yml:110`, `174`).

Jeśli `frontend` nie jest jeszcze gotowy, śledź jego log, aż Vite poda swój adres:

```bash
docker compose --profile app logs -f frontend
```

## 4. Wyślij pierwsze żądanie

```bash
curl http://localhost:8000/api/v1/health
```

API odpowiada obiektem JSON:

```json
{"status":"ok"}
```

Obsługuje je funkcja `health` w `backend/app/main.py:49-51`. Prefiks API to `/api/v1`.

Otwórz w przeglądarce `http://localhost:8000/api/v1/docs`. FastAPI udostępnia tam interaktywną dokumentację wszystkich endpointów (`backend/app/main.py:40`).

Aplikacja webowa dociera do API przez własny port. Vite przekazuje każdą ścieżkę pod `/api` do kontenera API, więc to samo żądanie działa na porcie 5173:

```bash
curl http://localhost:5173/api/v1/health
```

Zwraca ono to samo `{"status":"ok"}` (`frontend/vite.config.ts:22-28`; `VITE_API_PROXY_TARGET` w `docker-compose.yml:251`).

## 5. Utwórz konto administratora

```bash
docker compose --profile app exec rag-backend python -m app.cli create-admin --email <your-email> --name "<your name>"
```

Polecenie pyta o hasło. Musi ono mieć od 12 do 1024 znaków (`backend/app/auth/schemas.py:3-4`). Zarezerwowane domeny, takie jak `.local` i `.test`, są odrzucane jako adresy e-mail (`backend/app/cli.py:68-75`). Po powodzeniu polecenie wypisuje `Created admin`, a po nim pseudonim (`backend/app/cli.py:88`).

## 6. Zaloguj się do aplikacji webowej

Otwórz `http://localhost:5173/login`. Strona ma nagłówek "Sign in", pole Email i pole Password (`frontend/src/views/LoginView.vue:34-54`). Wpisz e-mail i hasło z kroku 5 i naciśnij "Sign in".

Aplikacja wysyła dane logowania do `POST /api/v1/auth/login`, który ustawia ciasteczko `session` z flagą HTTP-only (`backend/app/auth/router.py:12-16`; `backend/app/auth/service.py:44-53`). Ponieważ `COOKIE_SECURE` ma wartość `false`, a środowisko to `development`, ciasteczko działa przez zwykłe HTTP. Po udanym logowaniu aplikacja opuszcza stronę logowania (`frontend/src/views/LoginView.vue:24-25`).

Następnie otwórz w tej samej przeglądarce `http://localhost:5173/api/v1/me`. API zwraca Twojego użytkownika jako JSON, na podstawie ciasteczka sesji (`backend/app/auth/router.py:39-41`).

## 7. Zatrzymaj stos

```bash
docker compose --profile app down
```

Compose zatrzymuje i usuwa kontenery. Nazwane woluminy, między innymi `postgres-data`, pozostają, więc konto administratora istnieje przy następnym starcie (`docker-compose.yml:289-297`).

## Co masz uruchomione

Działają u Ciebie Postgres z pgvector, MinIO, Ollama, API w FastAPI i serwer deweloperski Vite z aplikacją webową, a Ty wysłałeś żądanie do API, utworzyłeś administratora i zalogowałeś się. Jak uruchomić sprawdzenia kodu, opisuje [Jak uruchomić testy i sprawdzenia](../how-to/run-tests-and-checks.md). Porty, zmienne środowiskowe i obrazy wymienia [Runtime i wdrożenie](../reference/runtime-and-deploy.md); endpointy [Backend core API](../reference/backend-core-api.md); aplikację webową [Aplikacja frontendowa](../reference/frontend-app.md). Jak uruchomić stos na maszynie wirtualnej Azure, opisuje [Jak wdrożyć na maszynie wirtualnej Azure](../how-to/deploy-to-azure-vm.md). Wszystkie strony wymienia [indeks dokumentacji](../index.md).

## Źródła w kodzie

- `docker-compose.yml:1-297` - usługi, profile, porty, zależności, usługi jednorazowe, woluminy
- `.env.example:1-20` - lokalne wartości domyślne kopiowane do .env
- `backend/Dockerfile:29-38` - instalacja zależności i polecenie uvicorn obrazu API
- `frontend/Dockerfile:9-17` - obraz dev, który wykonuje npm install i npm run dev
- `frontend/vite.config.ts:22-28` - proxy /api do API
- `backend/app/main.py:19-51` - prefiks API, adres dokumentacji, endpoint health
- `backend/app/cli.py:65-89` - polecenie create-admin
- `backend/app/auth/schemas.py:1-12` - limity długości hasła i treść żądania logowania
- `backend/app/auth/router.py:12-41` - endpointy login i me
- `backend/app/auth/service.py:44-53` - atrybuty ciasteczka sesji
- `frontend/src/views/LoginView.vue:20-57` - formularz logowania i przekierowanie po zalogowaniu
