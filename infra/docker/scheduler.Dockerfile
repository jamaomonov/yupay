# syntax=docker/dockerfile:1.7
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps ./apps

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package yupay-scheduler --no-dev

ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app/apps/scheduler

CMD ["python", "-m", "yupay_scheduler.main"]
