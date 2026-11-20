---
title: How to run tests and checks
diataxis: how-to
---

# How to run tests and checks

Language: **English** · [Polski](../../pl/how-to/run-tests-and-checks.md)

Use this when you want to run the backend tests, the frontend tests, the linters or the type checks, with or without a database.

## Prerequisites

- `uv` for the Python side and Node `^22.18.0 || >=24.12.0` with npm for the frontend (`frontend/package.json:64-66`). Python is `>=3.12` (`pyproject.toml:5`).
- For the tests marked `integration`: a running Postgres with pgvector. The compose service `postgres` provides one and publishes port 5432 (`docker-compose.yml:35-38`). Start it with `docker compose up -d postgres`.

## Backend

1. Install the packages of the workspace with the `dev` group only. The default groups also pull docling and the notebooks (`.github/workflows/ci.yml:21-22`).

   ```bash
   uv sync --frozen --no-default-groups --all-packages --group dev
   ```

2. Run the tests that need no database, model or network. In these tests everything that talks to Ollama is replaced (`.github/workflows/ci.yml:26-34`).

   ```bash
   uv run --no-sync pytest -m "not integration" tests/unit tests/scripts tests/test_*.py packages/expert-knowledge-core/tests packages/expert-knowledge-rag/tests
   ```

   For a run with coverage over `backend/app` and the two packages, add the options named in `pyproject.toml:68-72`:

   ```bash
   uv run pytest -m "not integration" --cov --cov-report=term-missing
   ```

3. Run the tests that need Postgres.

   ```bash
   uv run pytest -m integration
   ```

   Where the database comes from depends on the test folder:

   - `tests/api` (every test there is marked `integration` by `tests/api/conftest.py:38-42`). The tests connect to the server in `DATABASE_URL`, which defaults to `postgresql://rag:rag@localhost:5432/rag` when the variable is unset (`backend/app/settings.py:8`). Each run creates its own database `rag_<pid>_test`, applies the Alembic migrations and drops the database at the end (`tests/api/conftest.py:1-6`, `31-33`, `75-84`). To use a database of your own, set `TEST_DATABASE_URL`; its name has to end in `_test`, otherwise the run stops with "refusing to run against a non-test database" (`tests/api/conftest.py:30-35`).
   - `tests/integration` (retrieval regression). The fixture needs `DATABASE_URL` to be set and Postgres to answer `SELECT '[1,2]'::vector`; otherwise the tests are skipped (`tests/integration/conftest.py:27-37`). Inside the dev container the variable is set to the compose Postgres (`docker-compose.yml:121`). On the host, export it, for example the value in `.env.example:9`.
   - `packages/expert-knowledge-rag/tests/integration` needs `DATABASE_URL` and the file `scripts/db/chips_schema.sql`; without them the tests are skipped (`packages/expert-knowledge-rag/tests/integration/conftest.py:120-127`).

4. Select the retrieval-quality tests with their markers (`pyproject.toml:62-66`).

   ```bash
   uv run pytest -m regression
   ```

   - The `regression` tests of `tests/integration/test_retrieval_regression.py` read the frozen snapshot in `tests/fixtures/retrieval_silver`. The tests are skipped when `tables.json` is missing from it; the skip message names `python scripts/db/chips_snapshot.py freeze` (`tests/integration/conftest.py:40-45`).
   - The `scale` tests (`tests/integration/test_scale_regression.py:26`) read a 32-expert snapshot under `data/`, or under the path in `SCALE_SNAPSHOT`. That folder is local only. When its files are missing, the tests are skipped with the commands that create it (`tests/integration/conftest.py:80-105`). Exclude them with `-m "not scale"`.

5. Check the style and the types of the backend.

   ```bash
   uv run --no-sync ruff check backend
   uv run --no-sync ruff format --check backend
   uv run --no-sync ty check backend
   ```

   Ruff uses line length 100 and the rule sets E, F, I, UP, B, ASYNC and SIM (`pyproject.toml:45-51`). The pre-commit hooks run the same Ruff and ty checks on `backend/` when you commit (`.pre-commit-config.yaml:12-28`).

6. To run one file or one test, pass its path to pytest.

   ```bash
   uv run pytest tests/unit/test_db_url.py
   ```

## Frontend

Run these from the `frontend/` folder.

1. Install the locked dependencies.

   ```bash
   npm ci
   ```

2. Run the linters without rewriting files, the way CI does (`.github/workflows/ci.yml:50-51`).

   ```bash
   npx oxlint .
   npx eslint .
   ```

   `npm run lint` runs both with `--fix`, so it can change files (`frontend/package.json:15-17`). `npm run format` writes Prettier formatting to `src/` (`frontend/package.json:18`).

3. Check the types.

   ```bash
   npm run type-check
   ```

   The script is `vue-tsc --build` (`frontend/package.json:13`).

4. Run the unit tests once.

   ```bash
   npm run test:unit -- --run
   ```

   The specs are in `frontend/src/__tests__/*.spec.ts`. Vitest runs them in jsdom and skips `e2e/**` (`frontend/vitest.config.ts:8-10`). Without `--run`, the script starts plain `vitest` (`frontend/package.json:10`). The CI job starts no database or API service for these tests (`.github/workflows/ci.yml:36-54`).

   To run one spec, add its path:

   ```bash
   npm run test:unit -- --run src/__tests__/router.spec.ts
   ```

5. If you want coverage, run `npm run test:cov`. The script runs `vitest run --coverage --maxWorkers=2`. The report covers `src/**` without `src/api/schema.d.ts` and `src/__tests__/**` and prints as `text-summary` and `text` (`frontend/package.json:11`; `frontend/vitest.config.ts:12-17`).

6. Check that the app builds.

   ```bash
   npm run build-only
   ```

   `npm run build` runs `type-check` and `build-only` in parallel (`frontend/package.json:8`).

## Check the result

Skipped tests are reported as skipped by pytest, with the reason given in the conftest files cited above: a missing database or a missing snapshot is a skip, not a failure.

## See also

- [Runtime and deploy](../reference/runtime-and-deploy.md) - Postgres service, ports and environment variables
- [Run the stack locally](../tutorials/run-the-stack-locally.md) - start the compose services
- [Frontend app](../reference/frontend-app.md) - what the frontend tests cover

## Sources in code

- `pyproject.toml:1-77` - dev group, Ruff, ty, pytest markers, testpaths, coverage command
- `backend/pyproject.toml:1-30` - backend package and workspace sources
- `.github/workflows/ci.yml:1-54` - backend and frontend check commands
- `.pre-commit-config.yaml:12-28` - Ruff and ty hooks
- `docker-compose.yml:35-51` - postgres service and published port
- `backend/app/settings.py:8` - default DATABASE_URL
- `tests/api/conftest.py:1-84` - own test database, TEST_DATABASE_URL, integration marker, skip when Postgres is unreachable
- `tests/integration/conftest.py:27-105` - DATABASE_URL requirement, silver and scale snapshots
- `packages/expert-knowledge-rag/tests/integration/conftest.py:120-127` - DATABASE_URL and chips_schema.sql requirement
- `tests/integration/test_scale_regression.py:26` - scale marker
- `tests/unit/test_db_url.py:1-14` - example of a test file run alone
- `frontend/package.json:6-19,64-66` - npm scripts and Node engines
- `frontend/vitest.config.ts:1-20` - jsdom, excluded folders, coverage settings
