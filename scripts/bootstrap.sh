#!/usr/bin/env bash
# One-shot dev setup. Idempotent.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[bootstrap] enabling corepack + pnpm@9"
corepack enable
corepack prepare pnpm@9 --activate

echo "[bootstrap] pnpm install"
pnpm install --frozen-lockfile=false

echo "[bootstrap] uv sync"
uv sync || echo "uv not installed; install from https://docs.astral.sh/uv/"

echo "[bootstrap] pre-commit install"
pre-commit install || echo "pre-commit not installed; install with: uv tool install pre-commit"

echo "[bootstrap] generate OpenAPI client (if api is scaffolded)"
make gen-api || true

echo "[bootstrap] done"
