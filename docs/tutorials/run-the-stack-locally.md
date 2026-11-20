---
title: Run the stack locally
diataxis: tutorial
---

# Run the stack locally

Language: **English** · [Polski](../pl/tutorials/run-the-stack-locally.md)

In this tutorial you start the database, the object store, the API and the web app with Docker Compose, make your first request to the API, create an admin account and sign in to the web app. For how the parts fit together, see [Architecture](../explanation/architecture.md).

## Before you start

- Docker with the Compose plugin (`docker compose`). Every command below runs from the repository root, where `docker-compose.yml` lives.
- A host that can run the `ollama` service: the file reserves all NVIDIA GPUs for it (`docker-compose.yml:16-23`), and the `rag-backend` service waits for `ollama` to start. The `dev` service has the same reservation and a comment that it needs the NVIDIA Container Toolkit (`docker-compose.yml:135-142`).
- Free host ports 5432 (Postgres), 9000 and 9001 (MinIO), 11434 (Ollama), 8000 (API) and 5173 (web app) (`docker-compose.yml:7`, `38`, `77-79`, `183`, `249`).

This tutorial starts neither the `worker` service nor LanguageTool, so you do not need to pull any Ollama model.

## 1. Create the environment file

```bash
cp .env.example .env
```

The `rag-backend` service reads `.env` through `env_file` (`docker-compose.yml:184-185`), so the file has to exist. The template holds the local defaults: Postgres user, password and database `rag`, `ENVIRONMENT=development` and `COOKIE_SECURE=false` (`.env.example:1-4`, `13`, `16`). Leave it unchanged.

## 2. Start the API and the web app

```bash
docker compose --profile app up -d --build rag-backend frontend
```

Compose builds the images `backend/Dockerfile` and `frontend/Dockerfile` (target `dev`) and starts the two services together with what they depend on: `postgres`, `minio`, `minio-init`, `ollama` and `migrate` (`docker-compose.yml:159-206`, `243-258`).

- `postgres` runs `backend/db/init.sql` on its first start (`docker-compose.yml:45`).
- `minio-init` creates the S3 bucket and the app user, then exits (`docker-compose.yml:93-110`).
- `migrate` runs `alembic upgrade head`, then exits (`docker-compose.yml:159-174`).
- `rag-backend` starts only after `migrate` and `minio-init` have completed (`docker-compose.yml:197-206`).

The first build takes a while: the API image installs the Python dependencies with `uv sync`, and the frontend container runs `npm install` before it starts Vite (`backend/Dockerfile:29`, `frontend/Dockerfile:17`).

## 3. Look at the running services

```bash
docker compose --profile app ps -a
```

You see `postgres`, `minio`, `ollama`, `rag-backend` and `frontend` as running, and `migrate` and `minio-init` as exited, because both are one-shot services (`restart: "no"`, `docker-compose.yml:110`, `174`).

If `frontend` is not ready yet, follow its log until Vite reports its address:

```bash
docker compose --profile app logs -f frontend
```

## 4. Make your first request

```bash
curl http://localhost:8000/api/v1/health
```

The API answers with a JSON object:

```json
{"status":"ok"}
```

The handler is `health` in `backend/app/main.py:49-51`. The API prefix is `/api/v1`.

Open `http://localhost:8000/api/v1/docs` in a browser. FastAPI serves the interactive documentation of all endpoints there (`backend/app/main.py:40`).

The web app reaches the API through its own port. Vite forwards every path under `/api` to the API container, so the same request works against port 5173:

```bash
curl http://localhost:5173/api/v1/health
```

It returns the same `{"status":"ok"}` (`frontend/vite.config.ts:22-28`; `VITE_API_PROXY_TARGET` in `docker-compose.yml:251`).

## 5. Create an admin account

```bash
docker compose --profile app exec rag-backend python -m app.cli create-admin --email <your-email> --name "<your name>"
```

The command asks for a password. It must have 12 to 1024 characters (`backend/app/auth/schemas.py:3-4`). Reserved domains such as `.local` and `.test` are refused as email addresses (`backend/app/cli.py:68-75`). On success the command prints `Created admin` followed by a pseudonym (`backend/app/cli.py:88`).

## 6. Sign in to the web app

Open `http://localhost:5173/login`. The page has the heading "Sign in", an Email field and a Password field (`frontend/src/views/LoginView.vue:34-54`). Enter the email and password from step 5 and press "Sign in".

The app sends your credentials to `POST /api/v1/auth/login`, which sets an HTTP-only `session` cookie (`backend/app/auth/router.py:12-16`; `backend/app/auth/service.py:44-53`). Because `COOKIE_SECURE` is `false` and the environment is `development`, the cookie works over plain HTTP. After a successful login the app leaves the sign-in page (`frontend/src/views/LoginView.vue:24-25`).

Then open `http://localhost:5173/api/v1/me` in the same browser. The API returns your user as JSON, taken from the session cookie (`backend/app/auth/router.py:39-41`).

## 7. Stop the stack

```bash
docker compose --profile app down
```

Compose stops and removes the containers. The named volumes, among them `postgres-data`, stay, so your admin account exists at the next start (`docker-compose.yml:289-297`).

## What you have built

You run Postgres with pgvector, MinIO, Ollama, the FastAPI API and the Vite dev server of the web app, and you have made an API request, created an admin and signed in. To run the checks of the code, see [How to run tests and checks](../how-to/run-tests-and-checks.md). Ports, environment variables and images are listed in [Runtime and deploy](../reference/runtime-and-deploy.md); the endpoints in [Backend core API](../reference/backend-core-api.md); the web app in [Frontend app](../reference/frontend-app.md). To run the stack on the Azure VM, see [How to deploy to the Azure VM](../how-to/deploy-to-azure-vm.md). All pages are listed in the [documentation index](../index.md).

## Sources in code

- `docker-compose.yml:1-297` - services, profiles, ports, dependencies, one-shot services, volumes
- `.env.example:1-20` - local defaults copied to .env
- `backend/Dockerfile:29-38` - dependency install and the uvicorn command of the API image
- `frontend/Dockerfile:9-17` - dev image that runs npm install and npm run dev
- `frontend/vite.config.ts:22-28` - /api proxy to the API
- `backend/app/main.py:19-51` - API prefix, docs URL, health endpoint
- `backend/app/cli.py:65-89` - create-admin command
- `backend/app/auth/schemas.py:1-12` - password length limits and login body
- `backend/app/auth/router.py:12-41` - login and me endpoints
- `backend/app/auth/service.py:44-53` - session cookie attributes
- `frontend/src/views/LoginView.vue:20-57` - sign-in form and redirect after login
