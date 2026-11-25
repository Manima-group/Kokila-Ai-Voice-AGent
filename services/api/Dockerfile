# syntax=docker/dockerfile:1.7
# Base images are referenced by tag; pin to verified digests before release (docs/known-issues.md KI-03).
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.12-slim-bookworm AS runtime
RUN groupadd --system --gid 10001 kokila && useradd --system --uid 10001 --gid kokila --no-create-home kokila
WORKDIR /app
COPY --from=build --chown=kokila:kokila /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8000
# Same image serves: API (default), worker (`celery -A app.worker.celery_app worker -B`), migrations
# (`sh -c "alembic upgrade head && python -m app.cli bootstrap"`).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "20"]
