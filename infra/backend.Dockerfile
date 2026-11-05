# syntax=docker/dockerfile:1
#
# Production image of the API (what Render runs). The dev image is backend/Dockerfile.
# Build context: the repo root, because the uv workspace lockfile lives there:
#
#   docker build -f infra/backend.Dockerfile -t rag-backend .
#   docker run --rm -p 9000:9000 -e PORT=9000 -e ENVIRONMENT=production -e DATABASE_URL=... rag-backend
#
# Migrations are not run here: infra/deploy.sh runs them against the database's direct URL.

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/
# Only this member's runtime dependencies: no dev, notebook or script groups.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package rag-backend --no-default-groups

FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production
RUN groupadd --system app && useradd --system --gid app --create-home app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app backend /workspace/backend
USER app
WORKDIR /workspace/backend
# Render sets PORT (default 10000). It terminates TLS, so trust its X-Forwarded-* headers.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
