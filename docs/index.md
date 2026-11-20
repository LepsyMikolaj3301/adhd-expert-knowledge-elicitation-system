---
title: Documentation
diataxis: index
---

# Documentation

Language: **English** · [Polski](pl/index.md)

The documentation of the expert knowledge platform: a web app and API that collect expert answers to case vignettes, have them proofread and peer-reviewed, and turn the approved ones into searchable knowledge units. The pages are grouped by type.

## Tutorials

- [Run the stack locally](tutorials/run-the-stack-locally.md) - start the database, object store, API and web app with Docker Compose, make a first API request, create an admin account and sign in.

## How-to guides

- [How to run tests and checks](how-to/run-tests-and-checks.md) - run the backend tests, the frontend tests, the linters and the type checks, with or without a database.
- [How to deploy to the Azure VM](how-to/deploy-to-azure-vm.md) - set up the Azure VM once, publish the PC's Ollama and LanguageTool to it, deploy a release, and start and stop the VM and back up its database with the scripts in `infra/`.

## Reference

- [Backend core and API surface](reference/backend-core-api.md) - the FastAPI app under `/api/v1`, settings, database and error plumbing, auth, users, home, audit, the readiness probe, the Ollama clients, the prompt loader and the operator CLI.
- [Backend assignments and jobs](reference/backend-assignments-jobs.md) - the per-expert workflow routes, the state machine, the answer payloads, the Postgres job queue, the job handlers and the worker process.
- [Backend peer reviews](reference/backend-reviews.md) - the review routes, the access rules for submissions and the tables for participants, comments, votes and decisions.
- [Backend vignettes and knowledge](reference/backend-vignettes-knowledge.md) - the admin endpoints for vignette versions and the question set, and for knowledge units, with their validation rules.
- [Backend indexing and proofread](reference/backend-indexing-proofread.md) - the indexing configuration and embedder, and the proofreading, linking and edit-and-submit steps for an answer.
- [Packages expert-knowledge-core and expert-knowledge-rag](reference/packages.md) - BM25 sparse vectors, note packing, retrieval constants, and the read-only retrievers and chains over the `chips` schema.
- [Chunking and corpus configuration](reference/chunking.md) - the semantic chunker of the corpus scripts and the keys of `config/chunking.yaml`, `config/indexing.yaml` and `config/sources.yaml`.
- [Frontend app shell](reference/frontend-app.md) - bootstrap, routes, route guard, session handler, API client, stores, views, constants and the Vite, Vitest and ESLint configuration.
- [Frontend components and answering helpers](reference/frontend-components.md) - the Vue components with their props and events, and the TypeScript modules behind the answering and review screens.
- [Runtime and deployment](reference/runtime-and-deploy.md) - the local and Azure VM compose files, the Dockerfiles, database setup and migrations, the prompt files and the scripts.

## Explanation

- [About the architecture](explanation/architecture.md) - the system at three levels (context, containers, components) and the values that must agree between the parts.
- [About the assignment lifecycle](explanation/assignment-lifecycle.md) - how the state machine, the Postgres job queue and the admin-closed review carry an assignment from assignment to ingestion.
- [About retrieval and indexing](explanation/retrieval-and-indexing.md) - why literature chunks and expert findings are two stores that share one BM25 implementation and one embedder.

## Sources in code

- `backend/pyproject.toml` - backend package metadata: name rag-backend, dependencies, workspace libraries
- `frontend/package.json` - frontend package metadata, scripts and Node engine
- `docker-compose.yml` - local stack that the tutorial and the reference pages describe
