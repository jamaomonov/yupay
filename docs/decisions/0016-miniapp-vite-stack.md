# 0016. Switch the Telegram Mini App from Next.js to Vite + React + wouter

- **Status**: Accepted
- **Date**: 2026-05-17
- **Builds on**: ADR-0010 (admin SPA via Vite, no SSR)
- **Deciders**: founding team
- **Tags**: frontend, miniapp, stack

## Context

The original bootstrap stood up `apps/miniapp` on Next.js 15 because the public
storefront uses Next.js and the assumption was "one stack for both fronts." In
practice the Telegram Mini App has different requirements:

1. **It's never indexed**. The Mini App only ever renders inside Telegram's
   web-view; Google never sees it. SEO/SSR is dead weight.
2. **Cold-start matters more than anything**. Telegram users tap once and
   expect the UI within a second. Next.js's RSC + middleware + route-loader
   pipeline buys nothing here, but adds bundle + boot overhead.
3. **The codebase that already exists** — a polished mock-fronted prototype
   built by the founder in a separate repo — is Vite + React + `wouter` +
   Radix/shadcn + Tailwind v4. Porting it into a Next.js App Router shell
   means rewriting routing, splitting components into "use client" boundaries,
   and pulling apart Radix portals that don't love SSR. Roughly two days of
   busywork for no functional gain.

Per ADR-0010 we already accept Vite for the admin SPA. The "single React
stack" guideline only really applies to surfaces that benefit from SSR.

## Decision

Move `apps/miniapp` to **Vite 6 + React 19 + wouter + Tailwind v4** and pull
the prototype's UI in 1:1 (~1500 LOC across 4 pages + Shell/Header/BottomNav

- 14 shadcn-style components). Drop Next.js, `next-intl`, and the Next-only
  helpers from this app.

### What we lose

- `next-intl` route-aware i18n. The miniapp ships a single locale derived from
  `initData.user.language_code`; we re-pick a tiny i18n helper later when we
  add the second locale. Loss is acceptable because Telegram already gives us
  the locale on the client.
- Image optimisation via `next/image`. Mini apps run on phones with one screen
  size class; we serve pre-sized images and let the browser cache them. We can
  still revisit this when traffic and bandwidth warrant it.
- Server actions and middleware. Not relevant: the miniapp talks to
  `apps/api` from the client like every other client (with `Authorization: tma
<initData>` for HMAC-validated requests).

### What we gain

- **Smaller bundle, faster cold start**. Removing the Next.js runtime saves a
  ~70 KB gz minimum out of the gate, before any tree-shaking on our code.
- **Single, obvious mental model**: `index.html` → `main.tsx` → `<App />` →
  `wouter` route. No client/server split, no `app/` directory conventions.
- **The existing prototype boots directly**. Less time porting, more time
  iterating on the actual mobile UX.
- **Symmetry with `apps/admin`**: same Dockerfile shape (Vite build → nginx
  serve), same env-var passthrough (`VITE_*` build args), same `make`
  targets.

### Stack details

| Concern       | Choice                                                                      |
| ------------- | --------------------------------------------------------------------------- |
| Bundler / dev | Vite 6 + `@vitejs/plugin-react`                                             |
| Router        | `wouter` (matches the prototype)                                            |
| State         | TanStack Query v5 (already on the team)                                     |
| Forms         | `react-hook-form` + `zod`                                                   |
| UI primitives | Radix UI + bespoke shadcn-style components copied into `src/components/ui/` |
| Motion        | `framer-motion`                                                             |
| Style         | Tailwind v4 via `@tailwindcss/vite`                                         |
| Telegram      | `@telegram-apps/sdk-react` (kept)                                           |

The miniapp does **not** import `@yupay/ui` for now. Its visual language —
"Deep Space Dark + Electric Lime" — diverges from the admin's brand-neutral
palette by design (Telegram users expect a richer look). Once both surfaces
stabilise we'll factor the truly-shared components (Button, Card) back into
`@yupay/ui` with a theme prop. Premature unification is a worse loss than
duplication.

### Build / deploy

- New `infra/docker/miniapp.Dockerfile`: `node:22-alpine` builder → Vite build
  → `nginx:alpine` runner serving `/dist`. Mirrors `admin.Dockerfile`.
- `docker-compose.yml` `miniapp` service: passes `VITE_API_BASE_URL` and
  `VITE_TELEGRAM_BOT_USERNAME` as build args. Maps host `3001 → container 80`
  (was `3001 → 3000`).
- `Caddyfile.prod` (when miniapp goes live on `app.yupay.io`): proxies to the
  nginx container on port 80.

### Migration plan

1. Strip the Next.js scaffold from `apps/miniapp/` (one PR, mechanical).
2. Land Vite config, `index.html`, `src/{main,App,index.css}`, port pages and
   components from the prototype.
3. Mock data lives in `src/lib/constants.ts` exactly as in the source, so the
   UI renders without any API. **Real API wiring** lands in a follow-up ADR
   (TBD): replace mocks with TanStack Query calls to `/api/v1/catalog/*`,
   resolve Telegram auth via `/api/v1/auth/telegram/webapp`, hook the
   checkout to `/api/v1/orders`.

## Consequences

- Two of our three React surfaces are now Vite (admin, miniapp). Only the SEO
  storefront stays on Next.js — and it's the one that genuinely needs SSR.
- A second `tsconfig` and `eslint` setup, but both follow the same workspace
  configs we use for admin. Negligible cognitive load.
- We accept temporary code duplication of the Button/Card primitives between
  admin and miniapp. The dedup PR comes after both surfaces' visual languages
  settle.

## What's deferred

- Real API integration (mocks → live data) — separate PR.
- i18n: the miniapp ships Russian-only initially; en/uz arrive when `next-intl`
  is replaced by a lightweight client-only solution (likely `formatjs` or our
  own tiny ICU helper).
- Pulling `@yupay/ui` back in once Button/Card/Sheet stabilise across both
  Vite SPAs.

## Alternatives considered

- **Stay on Next.js, port the prototype manually**: rejected for cost.
  Two engineer-days of routing/portal/RSC adjustments deliver no value.
- **Use Remix or TanStack Router**: more migration overhead than wouter, and
  the prototype already runs on wouter. No reason to spend that budget here.
