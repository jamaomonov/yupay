# YuPay

> Multi-currency online storefront for digital top-ups, in-game currency, software licenses,
> and voucher codes. Two surfaces: SEO web storefront + Telegram Mini App.

---

## Read this first

- **[AGENTS.md](./AGENTS.md)** — onboarding, conventions, and the Definition of Done.
  Mandatory reading for any human or AI agent working in this repo.
- **[docs/architecture/overview.md](./docs/architecture/overview.md)** — system overview.
- **[docs/onboarding/local-setup.md](./docs/onboarding/local-setup.md)** — getting a local stack running.

---

## Stack at a glance

| Area     | Choice                                                                                          |
| -------- | ----------------------------------------------------------------------------------------------- |
| Backend  | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, Postgres-queue workers, Redis |
| Frontend | Next.js 15 (App Router, RSC), TypeScript strict, Tailwind v4, shadcn/ui                         |
| Mini App | `@telegram-apps/sdk-react` v3                                                                   |
| Data     | PostgreSQL 16, Redis 7, MinIO                                                                   |
| Monorepo | pnpm workspaces + Turborepo + uv workspace + Makefile                                           |
| Infra    | Docker Compose, Caddy 2, Prometheus + Grafana + Loki, Sentry SaaS                               |
| CI/CD    | GitHub Actions + GHCR + SSH deploy                                                              |

---

## Repository layout

```
yupay/
├── apps/        # api, worker, scheduler, bot, web, miniapp
├── packages/    # ui, api-client, i18n, telegram, analytics, utils, configs
├── infra/       # Dockerfiles, Caddy, Prometheus, Grafana, Loki, backups
├── docs/        # architecture, decisions (ADRs), runbooks, api, onboarding
├── scripts/     # bootstrap, gen-api, seed, release
├── .github/     # CI workflows, PR templates
└── Makefile     # single entrypoint for all common tasks
```

---

## Common commands

```bash
make bootstrap       # install all deps + pre-commit + gen-api
make dev             # full stack via docker-compose
make dev-api         # only the FastAPI app (foreground)
make dev-web         # only the public web (foreground)
make dev-miniapp     # only the Telegram Mini App (foreground)
make test            # all tests (Python + TS)
make lint            # ruff + mypy + eslint + tsc + prettier
make gen-api         # regenerate openapi.json + TS api-client
make migrate         # alembic upgrade head
make logs service=api
```

All targets are documented in the `Makefile` and in `AGENTS.md` § "How to run things".

---

## Security

Found a vulnerability? Please read [SECURITY.md](./SECURITY.md). Do not file public issues for
security reports.
