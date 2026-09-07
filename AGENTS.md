# AGENTS.md — Briefing for AI Agents Working on YuPay

> If you are an AI agent (Claude Code, Codex, Cursor, Copilot, Aider, etc.) reading this for
> the first time, **read this entire file before making any changes**. It is the contract
> between you and the project. A task is only complete when it satisfies the **Definition of
> Done** at the end of this file.
>
> Humans contributing to the project follow the same rules.

---

## 1. Project Identity

**YuPay** is a multi-currency online storefront for digital top-ups, in-game currency,
software licenses, gift cards, and voucher codes. It serves customers in Uzbekistan, Russia,
and the wider CIS, with planned expansion to global English-speaking markets. The product
exists in two surfaces:

- **Public web storefront** (`apps/web`) — SEO-driven, guest-friendly checkout.
- **Telegram Mini App** (`apps/miniapp`) — mobile, in-chat, frictionless.

**Business model.** YuPay buys digital goods from upstream suppliers at wholesale and resells
them with a margin. Customers pay via international cards (Stripe, PayPal), domestic
processors (Click, Payme, Uzcard, Humo for Uzbekistan; YooKassa, SBP, Tinkoff for Russia), and
stablecoins (USDT TRC-20/ERC-20). An internal wallet with a double-entry ledger powers
cashback, referrals, and promo codes. Order fulfillment is automated via supplier APIs and an
internal voucher-code warehouse.

**Scale targets.** 1,000–5,000 orders/day, ~200 RPS peak, three locales (RU / EN / UZ),
single-VPS deployment that must remain horizontally splittable without rewrites.

---

## 2. Tech stack at a glance

| Area                | Choice                                                                                                                                                                      |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend             | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, `uv`                                                                                                      |
| Background work     | Postgres-native queue (FOR UPDATE SKIP LOCKED + LISTEN/NOTIFY) consumed by apps/worker; Dramatiq retired 2026-08; Temporal remains the deferred option for multi-step sagas |
| Bot                 | aiogram 3                                                                                                                                                                   |
| Data                | PostgreSQL 16, Redis 7, MinIO (S3-compatible)                                                                                                                               |
| Frontend            | Next.js 15 (App Router, RSC), TypeScript 5.6+ strict, Tailwind v4, shadcn/ui, TanStack Query v5, Zustand, react-hook-form + zod, next-intl v4                               |
| Admin SPA           | Vite 5 + React 19 + React Router 7 (data API). No SSR — see ADR-0010                                                                                                        |
| Mini App            | `@telegram-apps/sdk-react` v3                                                                                                                                               |
| API client          | `@hey-api/openapi-ts` generated from FastAPI's OpenAPI 3.1 schema                                                                                                           |
| Monorepo            | pnpm workspaces + Turborepo (TS) + uv workspace (Python) + top-level Makefile                                                                                               |
| Reverse proxy / TLS | Caddy 2 (auto Let's Encrypt)                                                                                                                                                |
| Observability       | Prometheus + Grafana + Loki + Promtail, Sentry SaaS                                                                                                                         |
| Email               | Resend or Postmark (SaaS)                                                                                                                                                   |
| Secrets             | env files + `sops` + `age` (encrypted secrets committed to repo)                                                                                                            |
| Backups             | `pg_dump` → age → rclone → Cloudflare R2                                                                                                                                    |
| CI/CD               | GitHub Actions + GHCR + SSH deploy                                                                                                                                          |
| Tests               | pytest + testcontainers + respx + hypothesis (Py); Vitest + Playwright + Testing Library (TS)                                                                               |
| Lint / format       | ruff, mypy --strict (Py); eslint flat config, prettier, tsc (TS); pre-commit + commitlint + gitleaks                                                                        |

---

## 3. Repository layout

```
yupay/
├── apps/
│   ├── api/          # FastAPI modular monolith
│   ├── worker/       # Postgres-queue fulfilment consumer
│   ├── scheduler/    # Periodic jobs (APScheduler)
│   ├── bot/          # aiogram 3 Telegram bot
│   ├── web/          # Next.js public storefront (SEO)
│   └── miniapp/      # Next.js Telegram Mini App (mobile)
├── packages/
│   ├── ui/           # shadcn-based design system
│   ├── api-client/   # auto-generated typed TS client + WebSocket client
│   ├── i18n/         # ru/en/uz message catalogs
│   ├── telegram/     # Telegram types & client helpers
│   ├── analytics/    # Plausible/PostHog abstraction
│   ├── utils/        # shared TS utilities
│   ├── config-eslint/
│   ├── config-tsconfig/
│   └── config-tailwind/
├── infra/
│   ├── docker/       # Dockerfiles per app
│   ├── caddy/        # Caddyfile.dev / Caddyfile.prod
│   ├── prometheus/  grafana/  loki/  promtail/
│   ├── postgres/init/ # SQL extensions (pgcrypto, citext, pg_trgm)
│   └── backup/       # pg_backup.sh, restore.sh
├── docs/
│   ├── architecture/    overview, module-map, sequence diagrams (Mermaid), C4
│   ├── decisions/       ADRs (MADR template, NNNN-title.md)
│   ├── runbooks/        operational procedures
│   ├── api/             generated OpenAPI + auth/webhook notes
│   ├── onboarding/      humans.md, agents.md (deeper), local-setup, glossary
│   ├── product/         domain glossary, flows
│   └── security/        threat model, PII inventory
├── scripts/             bootstrap, gen-api, seed, release
├── .github/workflows/   ci.yml, build.yml, deploy.yml, codeql.yml, docs.yml
├── AGENTS.md            ← you are here
├── CLAUDE.md            symlink → AGENTS.md
├── README.md  CONTRIBUTING.md  SECURITY.md  LICENSE
├── Makefile             single entrypoint for all common tasks
├── docker-compose.yml   dev
├── docker-compose.prod.yml  single-VPS prod
├── turbo.json  pnpm-workspace.yaml  package.json
├── pyproject.toml  uv.lock  .python-version  .nvmrc
└── .pre-commit-config.yaml  commitlint.config.mjs
```

---

## 4. Where to put new code

| You are adding...                          | It goes in...                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A new backend domain module (e.g. refunds) | `apps/api/src/yupay/modules/<name>/` with `api.py` (public interface), `routes.py`, `service.py`, `models.py`, `schemas.py`, `tests/`. Mount the router in `apps/api/src/yupay/api/v1/__init__.py`                                                                                                                                                                                                                                                                                      |
| A new supplier integration                 | `apps/api/src/yupay/modules/integrations/adapters/<vendor>.py` implementing the `SupplierClient` protocol. Register in `integrations/registry.py`                                                                                                                                                                                                                                                                                                                                       |
| A new payment provider                     | `apps/api/src/yupay/modules/payments/gateways/<provider>.py` implementing the `PaymentGateway` protocol. Mount a webhook route in `apps/api/src/yupay/api/webhooks/<provider>.py`                                                                                                                                                                                                                                                                                                       |
| A new background task                      | There is no task module: work reaches the worker as **database rows**, drained by `apps/worker/src/yupay_worker/consumer.py` (ADR-0064). Model the work as a table with a claimable status, enqueue it in the same transaction as the fact that causes it, and run it from the fulfilment drain path. Recurring work belongs in `apps/scheduler` instead; a genuinely new queue (its own table + channel) extends the consumer. Handlers stay idempotent — a claim can always be re-run |
| A periodic job                             | `apps/scheduler/src/yupay_scheduler/jobs/<name>.py`                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| A reusable UI component                    | `packages/ui/src/components/<Component>/` with `Component.tsx`, `Component.stories.tsx`, `Component.test.tsx`, `index.ts`                                                                                                                                                                                                                                                                                                                                                               |
| A page in web/miniapp                      | `apps/{web,miniapp}/src/app/[locale]/<segment>/page.tsx`. Add `loading.tsx`, `error.tsx`, optionally `metadata.ts`                                                                                                                                                                                                                                                                                                                                                                      |
| Translations                               | `packages/i18n/locales/{ru,en,uz}/<namespace>.json` — **all three locales updated in the same PR**                                                                                                                                                                                                                                                                                                                                                                                      |
| A shared TS utility                        | `packages/utils/src/<feature>.ts`, with tests next to it                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Infra change                               | `infra/<service>/`, update both `docker-compose.yml` and `docker-compose.prod.yml` if applicable                                                                                                                                                                                                                                                                                                                                                                                        |

---

## 5. Where to put documentation (MANDATORY)

> **A PR is incomplete if code changes do not bring corresponding doc changes.** CI's
> `docs-check` step flags suspicious mismatches between touched code paths and touched doc
> paths. When unsure: **document first, code second** — the doc forces the design.

| Change                                                                                            | Required doc update                                                                                                                                         |
| ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New module or boundary change                                                                     | `docs/architecture/module-map.md` + a Mermaid sequence diagram in `docs/architecture/sequence-diagrams/<flow>.mmd` + a `README.md` inside the module folder |
| Architectural decision (new dep, new pattern, new infra service, framework upgrade, library swap) | New ADR at `docs/decisions/NNNN-<title>.md` using the MADR template (`docs/decisions/0000-template.md`)                                                     |
| New operational concern (alert, failure mode, manual step)                                        | New or updated file in `docs/runbooks/`                                                                                                                     |
| New endpoint                                                                                      | Regenerate `docs/api/openapi.json` via `make gen-api` + add notes to `docs/api/README.md` if auth/idempotency/rate-limit details apply                      |
| User-facing flow change                                                                           | Update `docs/product/flows/<flow>.md` with a Mermaid sequence diagram                                                                                       |
| Security-relevant change                                                                          | Update `docs/security/threat-model.md` and `docs/security/pii-handling.md` as needed                                                                        |

---

## 6. Coding standards

### Python

- Format and lint with **ruff** (`line-length = 100`, `target-version = "py312"`).
- Type-check with **mypy --strict**. Every function — including private — has full
  annotations. **No `Any` unless justified with an inline comment.**
- Docstrings: **Google style**, on every public function, class, and module.
- Pydantic v2 only. No mutable dataclasses in the domain layer; use `pydantic.BaseModel`
  (with `model_config = ConfigDict(frozen=True)` for value objects).
- **Async everywhere on the request path.** No `requests`, no `time.sleep`, no sync DB calls.
- No business logic in routers — routers parse and dispatch.
- File length soft limit: **400 LOC**. Split before 500.
- Function length soft limit: **50 LOC**; cyclomatic complexity ≤ 10 (ruff `C901`).

### TypeScript

- `strict: true`, `noUncheckedIndexedAccess: true`, `exactOptionalPropertyTypes: true`.
- **No `any`.** No `as` casts except for narrowing a known-shape JSON or DOM type, with a comment.
- All component props are explicit `interface`s; prefer `type` for unions.
- Exhaustive `switch` with a `never` default-case helper.
- Server Components are the default; `"use client"` only when necessary and as deep in the
  tree as possible.
- File length soft limit: **300 LOC**.

### Naming

- Python: `snake_case` for modules/functions, `PascalCase` for classes, `UPPER_SNAKE` for
  constants.
- TS: `camelCase` for variables/functions, `PascalCase` for components/types, `UPPER_SNAKE`
  for env vars and constants.
- Files: components `PascalCase.tsx`, hooks `useThing.ts`, utilities `kebab-case.ts`.

---

## 7. Commit & PR conventions

- **Conventional Commits** enforced by `commitlint`. Types: `feat`, `fix`, `perf`, `refactor`,
  `docs`, `test`, `build`, `ci`, `chore`, `revert`. Scope is the package or module
  (`feat(api/orders): ...`, `fix(web/checkout): ...`).
- One logical change per PR; aim for **< 400 LOC diff** (excluding generated files).
- PR template requires: summary, screenshots (UI), testing notes, checklist of doc updates,
  breaking-change note, rollback plan.
- Required CI checks: `lint-py`, `lint-ts`, `test-py`, `test-ts`, `openapi-drift`,
  `docs-check`, `commitlint`.
- Squash-merge to `main`. Tag releases with `vMAJOR.MINOR.PATCH`.

---

## 8. Testing rules

- **TDD when designing a new module or fixing a reproducible bug.** Write the failing test
  first, then implement.
- Coverage gates: Python ≥ 80%, TS ≥ 70%. **`payments`, `wallet`, `fulfillment`, supplier
  adapters: ≥ 95%.**
- Locations:
  - Python unit: `apps/api/tests/unit/`
  - Python integration (testcontainers Postgres/Redis): `apps/api/tests/integration/`
  - Python contract (recorded with respx/VCR): `apps/api/tests/contract/`
  - Python load (locust): `apps/api/tests/load/`
  - TS unit: alongside source as `*.test.ts(x)`
  - E2E: `e2e/` at repo root, Playwright
- **No payment or supplier adapter merges without an integration test** covering: success,
  retryable failure, idempotent re-call.
- **Never disable a failing test.** If a test is wrong, fix the test in the same PR and
  explain in the commit body.

---

## 9. Security rules

- All secrets via env vars or Docker secrets; **never committed unencrypted**. Use `sops + age`
  for repo-committed encrypted secrets.
- Webhook endpoints (Stripe, PayPal, suppliers, Telegram) **must** verify signatures **before**
  parsing the body. Raw-body middleware required.
- **Never log PII**: email, phone, full card data, Telegram user ID, IP. Use the structured
  logger's redactor. Order IDs and amounts are OK to log. "IP" means **an address we
  observed a person arriving from** — a customer's, a cabinet operator's, an admin's.
  The carve-out is the mirror image: **an address a third party published to us as a
  destination we should send to**. The test is _who chose the endpoint_, not who is
  behind it — a sole trader self-hosting a webhook on a residential line still chose
  to hand us that address as a delivery target, and nothing in the request path could
  check the difference anyway. Three sites carry one today, all on the outbound
  merchant-webhook path and all recording where a delivery went:
  - `core/outbound.py`'s `outbound.delivered` (`address=pinned`);
  - `merchants/webhook_outcome.py`'s `merchant_webhook.delivered` (`address=`);
  - `AddressNotAllowedError`'s message, which names the refused addresses and reaches
    `merchant_webhook_deliveries.last_error` and the `error=` field of
    `merchant_webhook.attempt_failed` — a refusal is unactionable without them.

  "We recorded a 200 — to which of their hosts?" is the question that log exists to
  answer, and the SSRF client pins one address per attempt so it is answerable. A
  fourth site needs the same shape — an address the counterparty supplied as a
  destination — and a line here.

- All **state-changing** endpoints (`POST`, `PUT`, `PATCH`, `DELETE`) **must** accept an
  `Idempotency-Key` header and persist results keyed by it. The rule protects writes from
  replay, so it does not reach a `POST` that writes nothing: advisory lookups are `POST`
  only to keep an identifier out of the URL — and therefore out of the edge access log,
  which records the full query string — not because they mutate anything. Three such
  endpoints exist today: `POST /catalog/products/{id}/check-player`,
  `POST /gifts/steam-profile` and `POST /merchant/v1/validate/player` (the same
  player check, exposed to a reseller — the identifier it carries is their end
  customer's). If you add a fourth, say in its docstring why it is keyless.
  The one **mutation** exempt from the header is `POST /merchant/v1/orders`, which is
  idempotent on the caller's own `merchant_order_id` instead (spec §9.3): that id is
  minted per _intent_ by the reseller's system rather than per attempt by ours, is what
  a replayed request necessarily carries, and resolves races in
  `uq_orders_idem_merchant`. Accepting a second, weaker key beside it would give
  integrators two ways to be idempotent and one of them wrong. Any future exemption
  needs the same shape — a caller-owned key with a DB uniqueness constraint behind it —
  and a line here.
- All money values stored as `Decimal` (Python) / `string` (TS) in **minor units** (tiyin /
  cents), never floats.
- Auth tokens: short-lived access (15 min EdDSA JWT), rotating refresh (30 days), revocable
  via a server-side hash blocklist.
- Rate limit every public endpoint. In practice this lives **only in FastAPI**
  (slowapi, bucketed per route — see ADR-0028), plus the Redis-backed two-axis
  `ip_guard` on credential endpoints. Caddy's `rate_limit` needs a community module
  and a custom build, so it was declined — the Caddyfile says so at the site block.
  The edge tier is Cloudflare's WAF, configured in its dashboard, not in this repo.
  **The self-authenticating machine surfaces are exempt on purpose**
  (`bootstrap._exempt_self_authenticating_routes` — one audited list): a 429 to an
  acquirer costs money and buys nothing, and `/merchant/v1` already carries its own
  two-axis guard whose 429 is RFC 7807 with `Retry-After`, which the coarse tier's
  is not. Everything on that list authenticates its own caller, so the per-IP limit
  was never the control protecting it.
- `gitleaks` runs pre-commit; CodeQL is wired up but manual-only while the repo is private without GHAS (the scan API rejects it) — switch `codeql.yml` to a weekly cron when the repo goes public or GHAS is purchased.

---

## 10. Performance rules

- Identify and prevent N+1: use `selectinload`/`joinedload` in SQLAlchemy 2; every list
  endpoint must have an integration test that asserts query count.
- **No synchronous external HTTP calls in request handlers.** Always enqueue and respond
  with a pending status; the client subscribes via WebSocket or polls. The rule protects
  the **money path**: a supplier call inside a request handler can leave the supplier paid
  with no record of it, and one slow upstream holds a pool connection somebody's checkout
  needed. Four **advisory pre-purchase lookups** deviate from it, and they are the whole
  list: `GET /admin/integrations/g2b/games/{game_code}/check-player` (ADR-0019, the
  precedent), `POST /catalog/products/{id}/check-player` and
  `POST /merchant/v1/validate/player` (both ADR-0031, which carries the justification and
  the conditions — advisory, off the order path, short timeout, breaker, Redis-cached, its
  own rate-limit bucket), and `POST /gifts/steam-profile`, which calls the Steam Web API
  from its handler with a short-timeout client of its own. **The fourth has no ADR**: it
  predates this list and clears some of ADR-0031's conditions (advisory, off the order
  path, short timeout, Redis-cached, own bucket) but not the breaker. That gap is real and
  is recorded here rather than left to be rediscovered; closing it means either an ADR
  saying why a breaker is unnecessary there, or a breaker. If you add a fifth, it needs an
  ADR entry saying why it clears those conditions and a line here. A rule that does not name its exceptions stops being
  read as a rule: this one was silently deviated from three times before the list existed.
- Cache reads in Redis with explicit TTLs; tag-based invalidation. **Every cache key is
  documented in `docs/architecture/cache-keys.md`.**
- DB indices are added in the same migration as the query that needs them.
- Frontend bundle budget per route: web ≤ **180 KB JS gzipped**, miniapp ≤ **120 KB**.
  ⚠️ **Nothing enforces this today** — there is no bundle step in CI and no analyzer
  wired up, which is why both surfaces drifted over budget unnoticed (measured
  2026-08-26: web 189 KB, miniapp 231 KB). Treat the numbers as a target to measure
  against by hand until a CI check exists; land the check _after_ the miniapp split,
  or it blocks every PR.

---

## 11. i18n rules

- **Never hardcode user-facing strings** in TS or templates. Use `t("namespace.key")`.
- Every new key is added to `ru.json`, `en.json`, `uz.json` in the **same** PR. CI fails if
  any locale is missing a key.
- Plurals via ICU MessageFormat (`next-intl` supports it).
- Currency formatting via `Intl.NumberFormat` with locale + currency; never string-concat.
- Dates via `Intl.DateTimeFormat`; store as ISO 8601 UTC in DB and in transit.

---

## 12. How to run things

All entrypoints live in the root `Makefile`. **Prefer `make` targets over invoking raw tools.**

| Target                                               | What it does                                                         |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| `make bootstrap`                                     | Install all deps (pnpm + uv), set up pre-commit, generate API client |
| `make dev`                                           | Bring up the full dev stack via docker-compose                       |
| `make dev-api` / `make dev-web` / `make dev-miniapp` | Run one app in foreground                                            |
| `make migrate`                                       | `alembic upgrade head` inside the api container                      |
| `make migration name=add_x`                          | Create a new Alembic migration                                       |
| `make test`                                          | Run all tests across Python and TS                                   |
| `make test-py` / `make test-ts` / `make test-e2e`    | Targeted suites                                                      |
| `make lint` / `make lint-fix`                        | Lint everything / autofix                                            |
| `make typecheck`                                     | mypy + tsc                                                           |
| `make gen-api`                                       | Regenerate `docs/api/openapi.json` + `packages/api-client/`          |
| `make build`                                         | Build all Docker images locally                                      |
| `make deploy env=prod`                               | Trigger deploy (only from CI; locally for staging)                   |
| `make logs service=api`                              | Tail a service's logs                                                |
| `make backup` / `make restore file=...`              | DB backup / restore                                                  |

---

## 13. Agent etiquette

- **Ask clarifying questions when:** requirements are ambiguous, two valid approaches differ
  materially, a change crosses module boundaries unexpectedly, or a destructive operation is
  implied.
- **Write an ADR when:** introducing a new dependency, picking between two patterns, changing
  a public contract, or making any decision a future maintainer might second-guess.
- **Update `AGENTS.md`** when: a rule here is contradicted by reality, a new convention emerges,
  or the stack changes.
- **Never** commit secrets, even in tests.
- **Never** disable a failing test or lint rule without a follow-up issue cited in the commit
  body.
- **Never** invent business logic — confirm with the issue, the spec in `docs/product/`, or by
  asking.
- **Never** create files for "summaries", "reports", "analysis", or "findings" unless
  explicitly requested. Put notes in the PR description.
- **Always** run `make lint typecheck test` locally before opening a PR.
- **Always** include a doc update in the same PR as the code change.

---

## 14. Definition of Done

A task is **done** only when **all** of the following are true:

- [ ] All acceptance criteria from the issue/spec are met.
- [ ] Code passes `make lint typecheck test` locally and in CI.
- [ ] New code has tests; coverage gates are met (see §8).
- [ ] OpenAPI schema regenerated; TS client regenerated; no drift.
- [ ] Affected documentation is updated in the same PR (architecture, ADR, runbook, README, as
      applicable).
- [ ] All three locales updated for any new user-facing string.
- [ ] No new `TODO` or `FIXME` without a tracked issue link.
- [ ] No secrets, PII, or large binary blobs committed.
- [ ] PR description completed with summary, testing notes, screenshots (UI), and rollback plan.
- [ ] Conventional Commit message; PR linked to an issue or spec.
- [ ] At least one human reviewer approval before squash-merge to `main`.
