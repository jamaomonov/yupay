# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS base
RUN corepack enable && corepack prepare pnpm@9 --activate
WORKDIR /app

FROM base AS deps
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

FROM base AS builder
ARG VITE_API_BASE_URL
ARG VITE_TELEGRAM_BOT_USERNAME
ARG VITE_TELEGRAM_SUPPORT_USERNAME
ARG VITE_COMPANY_NAME
ARG VITE_COMPANY_REGISTRATION
ARG VITE_COMPANY_SINCE
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_TELEGRAM_BOT_USERNAME=${VITE_TELEGRAM_BOT_USERNAME}
ENV VITE_TELEGRAM_SUPPORT_USERNAME=${VITE_TELEGRAM_SUPPORT_USERNAME}
ENV VITE_COMPANY_NAME=${VITE_COMPANY_NAME}
ENV VITE_COMPANY_REGISTRATION=${VITE_COMPANY_REGISTRATION}
ENV VITE_COMPANY_SINCE=${VITE_COMPANY_SINCE}
COPY --from=deps /app /app
COPY . .
RUN pnpm --filter @yupay/miniapp build

FROM nginx:alpine AS runner
COPY --from=builder /app/apps/miniapp/dist /usr/share/nginx/html
COPY infra/docker/miniapp-nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
