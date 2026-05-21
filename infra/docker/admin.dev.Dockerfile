# syntax=docker/dockerfile:1.7
#
# Dev image for the Admin SPA.
#
# Mirrors infra/docker/miniapp.dev.Dockerfile — runs ``vite dev`` so source
# edits hot-reload through the bind-mounted ``apps/admin`` + ``packages/``
# directories. Production image lives in ``admin.Dockerfile`` (nginx +
# static ``dist/``).

FROM node:22-alpine

RUN corepack enable && corepack prepare pnpm@9 --activate
WORKDIR /app

# 1) Install dependencies — copy only manifests first so the layer caches well.
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY apps/miniapp/package.json apps/miniapp/package.json
COPY apps/admin/package.json apps/admin/package.json
COPY packages/ui/package.json packages/ui/package.json
COPY packages/api-client/package.json packages/api-client/package.json
COPY packages/i18n/package.json packages/i18n/package.json
COPY packages/telegram/package.json packages/telegram/package.json
COPY packages/utils/package.json packages/utils/package.json
COPY packages/analytics/package.json packages/analytics/package.json
COPY packages/config-eslint/package.json packages/config-eslint/package.json
COPY packages/config-tsconfig/package.json packages/config-tsconfig/package.json
COPY packages/config-tailwind/package.json packages/config-tailwind/package.json

RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile=false

# 2) Copy sources. compose overlays bind-mounts on top of these at runtime.
COPY apps/admin apps/admin
COPY packages packages

EXPOSE 5173

CMD ["pnpm", "--filter", "@yupay/admin", "dev"]
