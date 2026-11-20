# ADHD expert knowledge elicitation system

A web platform that collects written answers from experts to case vignettes, has the answers proofread and peer-reviewed, and turns the approved ones into searchable knowledge units. It has a Vue single-page app (shown as "PsyKnowHow"), a FastAPI backend under `/api/v1`, a background worker that runs the slow steps, a PostgreSQL database with pgvector, and Ollama and LanguageTool for language models and grammar checks.

## Quick start

The local stack runs with Docker Compose from the repository root. The `ollama` service reserves NVIDIA GPUs, so the host needs them.

```bash
cp .env.example .env
docker compose --profile app up -d --build rag-backend frontend
curl http://localhost:8000/api/v1/health
```

The first command copies the local defaults, the second builds and starts the API, the web app and the services they depend on, and the third calls the health endpoint of the API. The web app is at `http://localhost:5173`. The tutorial adds an admin account and a sign-in.

## Documentation

- [Documentation index](docs/index.md)
- [Tutorial: run the stack locally](docs/tutorials/run-the-stack-locally.md)
- [About the architecture](docs/explanation/architecture.md)

## Sources in code

- `backend/pyproject.toml` - backend name rag-backend, description and dependencies
- `frontend/package.json` - frontend scripts and Node engine
- `frontend/src/site.ts` - SITE_NAME shown in the web app
- `backend/app/main.py` - API title, prefix and health endpoint
- `docker-compose.yml` - services, profiles, ports and the GPU reservation of ollama
- `.env.example` - local defaults copied to .env
