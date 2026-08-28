# syntax=docker/dockerfile:1.7
#
# Dev image for the partner site. Runs `next dev` so edits in
# `apps/partners/src` and `packages/*/src` — bind-mounted by
# docker-compose.yml — reload without rebuilding.
#
# The production image is `partners.Dockerfile`.

FROM node:22-alpine

RUN corepack enable && corepack prepare pnpm@9 --activate
WORKDIR /app

COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY apps/miniapp/package.json apps/miniapp/package.json
COPY apps/admin/package.json apps/admin/package.json
COPY apps/partners/package.json apps/partners/package.json
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

COPY apps/partners apps/partners
COPY packages packages

EXPOSE 3003

# Plain `next dev` (no --turbo): webpack's watcher honours WATCHPACK_POLLING,
# which is what makes a bind-mounted file change on macOS reach the dev server.
CMD ["pnpm", "--filter", "@yupay/partners", "exec", "next", "dev", "-p", "3003"]
