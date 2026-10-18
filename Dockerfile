# The API image: the package and its locked dependencies only. No SoccER data, web app or tests; on Railway
# the API serves engine output seeded into Postgres (scripts/seed_db.py).
FROM python:3.13-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim-bookworm
RUN useradd --system --create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
RUN chown app /app
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
# One worker: the narrative queue and the cache in front of Postgres live in the process.
CMD ["sh", "-c", "exec uvicorn filmroom.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
