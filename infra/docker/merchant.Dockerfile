# syntax=docker/dockerfile:1.7
#
# Production image for the B2B cabinet (reseller.yupay.uz).
#
# Mirrors web.Dockerfile. The dependency layer copies every workspace manifest
# because pnpm resolves the whole workspace graph before it can install one
# app — omitting one makes the install fail, not merely install less.

FROM node:22-alpine AS base
RUN corepack enable && corepack prepare pnpm@9 --activate
WORKDIR /app

FROM base AS deps
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY apps/miniapp/package.json apps/miniapp/package.json
COPY apps/admin/package.json apps/admin/package.json
COPY apps/partners/package.json apps/partners/package.json
COPY apps/merchant/package.json apps/merchant/package.json
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

FROM base AS builder
COPY --from=deps /app /app
COPY . .
# Next inlines NEXT_PUBLIC_* into the client bundle at build time, so these have
# to be here and not only at runtime.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN pnpm --filter @yupay/merchant build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY --from=builder /app /app
EXPOSE 3004
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost:3004/ || exit 1
CMD ["pnpm", "--filter", "@yupay/merchant", "start"]
