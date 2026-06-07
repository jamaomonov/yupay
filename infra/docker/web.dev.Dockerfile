# syntax=docker/dockerfile:1.7
#
# Dev image for the public Next.js storefront.
#
# Runs `next dev` (not the production `next build`/`next start`), so edits in
# `apps/web/src` and `packages/*/src` — bind-mounted by docker-compose.yml —
# hot-reload in the browser without rebuilding the image. Anonymous volumes
# mask `node_modules`, keeping the pnpm install baked into this image alive
# across the bind-mounts.
#
# The production image lives in `web.Dockerfile` (next build + next start) and
# is consumed by docker-compose.prod.yml via the GHCR tag.

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

# 2) Copy sources. compose overlays bind-mounts on top of these at runtime; the
#    initial COPY exists so the image is usable without a mount too.
COPY apps/web apps/web
COPY packages packages

EXPOSE 3000

# Plain `next dev` (no --turbo): webpack's watcher honours WATCHPACK_POLLING,
# which is what makes file changes on a Docker bind-mount (macOS) reach the
# dev server reliably.
CMD ["pnpm", "--filter", "@yupay/web", "exec", "next", "dev", "-p", "3000"]
