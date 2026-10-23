FROM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS backend
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/tests ./tests
RUN uv sync --frozen --no-dev && \
    useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
USER app
EXPOSE 8000
CMD ["uvicorn", "routing_guides.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM backend AS production
ENV CREDENTIALS_MODE=environment
COPY --from=frontend /web/dist /app/static
