# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

WORKDIR /app

# Copy the whole monorepo so uv can resolve workspace members (apps/api depends on
# transitive workspace pieces via `[tool.uv.sources]`).
COPY pyproject.toml uv.lock ./
COPY apps ./apps

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package yupay --no-dev

ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app/apps/api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz',timeout=2).status==200 else 1)"

# Drop root: the service only reads /app and the venv; nothing is written
# locally at runtime (logs go to stdout, tmp files to /tmp).
RUN groupadd --system app && useradd --system --gid app --no-create-home app
USER app

CMD ["uvicorn", "yupay.main:app", "--host", "0.0.0.0", "--port", "8000"]
