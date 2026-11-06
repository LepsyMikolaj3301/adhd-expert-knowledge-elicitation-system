# Build context is the repo root (see docker-compose.yml): the uv workspace lockfile lives there.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-pol libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Keep the venv outside the bind-mounted source tree.
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

# Only this member's runtime deps: no dev/notebook/script groups.
COPY --chown=$USERNAME:$USERNAME pyproject.toml uv.lock ./
COPY --chown=$USERNAME:$USERNAME backend/pyproject.toml backend/
RUN uv sync --frozen --package rag-backend --no-default-groups

COPY --chown=$USERNAME:$USERNAME backend backend
# The worker reads the classifier prompt and the embedding settings (project_root in settings.py).
COPY --chown=$USERNAME:$USERNAME prompts prompts
COPY --chown=$USERNAME:$USERNAME config config

WORKDIR /workspace/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
