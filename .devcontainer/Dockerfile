# Dev image for the whole monorepo: every workspace member + all default dependency groups.
# Build context is the repo root (see docker-compose.yml).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

ARG USERNAME=vscode
ARG USER_UID=1000
RUN groupadd --gid $USER_UID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_UID --create-home --shell /bin/bash $USERNAME \
    && install -d -o $USERNAME -g $USERNAME /opt/venv /workspace

USER $USERNAME
WORKDIR /workspace

# Manifests only, so this layer is cached until dependencies change. Add new members here.
COPY --chown=$USERNAME:$USERNAME pyproject.toml uv.lock ./
COPY --chown=$USERNAME:$USERNAME backend/pyproject.toml backend/
RUN uv sync --frozen --all-packages
