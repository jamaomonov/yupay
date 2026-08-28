# `apps/partners` — landing and panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A partner-facing site on `partners.yupay.uz`: a landing page that sells the programme and takes applications, and a panel where an approved partner reads their earnings and asks for their money.

**Architecture:** A third Next.js app in the monorepo, scaffolded from `apps/web`. The landing is static and indexable; the panel is client-rendered behind a token. Both extend the existing YuPay visual language rather than inventing a second one — same deep-navy surface, same electric-lime accent, same type pairing.

**Tech Stack:** Next.js 15 (App Router), TypeScript strict, Tailwind v4, TanStack Query v5, next-intl v4, react-hook-form + zod, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-27-affiliate-program-design.md`
**Previous plans:** the four `2026-08-2*-affiliate-*.md` files.

**Plan 5 of 7.** Steps 6–7 remain: admin screens, infrastructure.

## Global Constraints

- TypeScript `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`. **No `any`.**
- File length soft limit **300 LOC**.
- **Every user-facing string in `ru`, `en` and `uz` in the same commit.**
- `npx prettier --check .` clean on git-tracked files.
- Commit after every green test run. **Do not push or deploy** without an explicit instruction.
- ⚠️ **A host build of a Next app corrupts a running dev container's bind-mounted `.next`.** Stop the container first; afterwards `rm -rf .next` and restart.

## What the API already provides

All of it, from plan 4, live on this branch:

| Method | Path                                  | Auth                        |
| ------ | ------------------------------------- | --------------------------- |
| POST   | `/api/v1/affiliate/applications`      | public                      |
| POST   | `/api/v1/affiliate/auth/set-password` | token in body               |
| POST   | `/api/v1/affiliate/auth/login`        | public                      |
| POST   | `/api/v1/affiliate/auth/refresh`      | refresh token               |
| POST   | `/api/v1/affiliate/auth/logout`       | refresh token               |
| GET    | `/api/v1/affiliate/me`                | partner                     |
| GET    | `/api/v1/affiliate/stats?period=`     | partner                     |
| GET    | `/api/v1/affiliate/balance`           | partner                     |
| GET    | `/api/v1/affiliate/commissions`       | partner                     |
| GET    | `/api/v1/affiliate/payouts`           | partner                     |
| POST   | `/api/v1/affiliate/payouts`           | partner + `Idempotency-Key` |

## Design decisions

**Extend the brand, do not invent one.** `apps/web/src/app/globals.css` carries a documented palette — `--bg: 232 50% 6%`, electric-lime primary, Unbounded for display, Inter for body, JetBrains Mono for numerals — with a comment explaining why the greys are low-contrast and why `--tx-mute` sits where it does (a measured WCAG fix across 304 occurrences). The partner site copies that file rather than starting a second palette. A partner who has seen the storefront should recognise this immediately.

**The panel is dense and numeric, the landing is not.** They share the palette and diverge in rhythm: the landing gets air, the panel gets tables and monospaced figures. Same brand, different job.

**Money is always rendered by one helper.** Every figure a partner sees is money, and a panel that formats it three different ways looks broken even when the numbers are right.

**Tokens live in memory, not `localStorage`.** The access token is short-lived and the refresh token rotates; keeping either in `localStorage` hands both to any injected script. Memory plus a refresh-on-load is how `apps/web` already does it — follow it rather than differing.

**The landing is prerendered and calls nothing at build time.** It has no data to fetch, so it must not acquire a dependency on the API being up during a build — the storefront's prerender pass already knocks the dev API over, and a second app doing the same would double it.

## File Structure

```
apps/partners/
├── package.json, tsconfig.json, next.config.ts, eslint.config.js, postcss.config.mjs
├── src/
│   ├── app/
│   │   ├── globals.css            copied palette + panel-specific additions
│   │   ├── layout.tsx             fonts, providers
│   │   ├── page.tsx               the landing
│   │   ├── login/page.tsx
│   │   ├── set-password/page.tsx
│   │   └── panel/
│   │       ├── layout.tsx         auth gate + nav
│   │       ├── page.tsx           overview
│   │       ├── codes/page.tsx
│   │       ├── referrals/page.tsx
│   │       └── payouts/page.tsx
│   ├── components/
│   │   ├── landing/               Hero, HowItWorks, Calculator, Faq, ApplyForm
│   │   └── panel/                 StatCard, EarningsChart, CommissionTable, PayoutForm
│   └── lib/
│       ├── api.ts                 fetch wrapper + token refresh
│       ├── auth.tsx               session context
│       └── money.ts               the one formatter
└── messages/                      ru / en / uz
```

---

### Task 1: Scaffold

**Files:** the config files above, `layout.tsx`, `globals.css`, a placeholder `page.tsx`.

- [ ] **Step 1:** copy `apps/web`'s `package.json`, `tsconfig.json`, `next.config.ts`, `eslint.config.js`, `postcss.config.mjs`, renaming to `@yupay/partners` and port **3002** (web is 3000, check what admin/miniapp use and avoid a clash).
- [ ] **Step 2:** copy `apps/web/src/app/globals.css` verbatim. Keep its comments — they record measured accessibility decisions, and a copy that drops them invites someone to "clean up" a contrast fix.
- [ ] **Step 3:** `pnpm install` at the root.
- [ ] **Step 4:** a placeholder page; `pnpm --filter @yupay/partners build` succeeds.
- [ ] **Step 5:** `pnpm --filter @yupay/partners typecheck` and `lint` clean. Commit.

---

### Task 2: Message catalogues

All three locales, all screens, before any component is written — the same order as plan 3, for the same reason.

- [ ] Landing: hero, three steps, calculator labels, FAQ (5 Q&A), form fields and outcomes.
- [ ] Auth: login, set-password, their errors.
- [ ] Panel: nav, stat labels, table headers, payout form, empty states.
- [ ] Verify no locale lags with the node one-liner from plan 3. Commit.

---

### Task 3: The landing

**Files:** `src/app/page.tsx`, `src/components/landing/*`

- [ ] **Hero** — what the programme is, in one sentence, and the two numbers that matter: the discount a partner's audience gets and the cut the partner keeps.
- [ ] **How it works** — three steps: apply, share your code, get paid.
- [ ] **Calculator** — audience size × conversion × average order → monthly earnings. Client-side, no API. **Its defaults must be defensible**: seed the average order from a real figure (~12 000 UZS, measured) rather than a flattering one. A calculator that overpromises is the fastest way to lose a partner after their first payout.
- [ ] **FAQ** — when money arrives, why there is a hold, what the minimum withdrawal is, what happens on a refund, whether the code works for existing customers. Answer the awkward ones; a partner who finds out about the 14-day hold _after_ joining feels tricked.
- [ ] **Apply form** — email, name, contact, channel. `react-hook-form` + `zod`. Answers the same for a new address and a repeat, because the API does.
- [ ] Prerendered, three locales, no API call at build. Tests for the calculator arithmetic and the form's states. Commit.

---

### Task 4: Auth

**Files:** `src/app/login/page.tsx`, `src/app/set-password/page.tsx`, `src/lib/api.ts`, `src/lib/auth.tsx`

- [ ] **`lib/api.ts`** — fetch wrapper that attaches the access token, and on a 401 tries one refresh and replays. One refresh, not a loop.
- [ ] **`lib/auth.tsx`** — context holding the tokens in memory, restoring the session on load from the refresh token.
- [ ] **Login** — one error message for every failure, matching the API, which deliberately does not distinguish a wrong password from an unknown address. **Do not "improve" this in the UI.**
- [ ] **Set-password** — reads `?token=`, posts it, sends the partner to the login page. A used or expired link says so plainly.
- [ ] Tests: the refresh-once behaviour, and that a failed login shows the generic message. Commit.

---

### Task 5: The panel

**Files:** `src/app/panel/*`, `src/components/panel/*`

- [ ] **Layout** — auth gate (no token → `/login`), nav, sign out.
- [ ] **Overview** — available and held balances as two cards, earnings for the four windows, activation counts. **Label the windows "за 30 дней", not "за месяц"** — the API computes rolling windows and the wording must match the arithmetic.
- [ ] **Codes** — each code with its discount and commission percentages, a copy-to-clipboard button for the code and for a ready-made link.
- [ ] **Referrals** — the commission list, paginated, showing status (`held`, `available`, `paid`).
- [ ] **Payouts** — the balance, a request form (amount + card + holder), and the history. The form must state the minimum **before** submission rather than only rejecting after, and must show the card masked in the history because that is all the API returns.
- [ ] Tests for the table states and the payout form's validation. Commit.

---

### Task 6: Wire-up and measurement

- [ ] `pnpm --filter @yupay/partners build` — record the bundle size for the landing and the panel routes, the way plan 3 did.
- [ ] Full lint, typecheck and test across the workspace.
- [ ] `docs/architecture/module-map.md` — add the app.
- [ ] Commit.

---

## Definition of Done for this plan

- [ ] `pnpm --filter @yupay/partners build`, `typecheck`, `lint`, `test` all clean.
- [ ] Every string in all three locales.
- [ ] `npx prettier --check .` clean on tracked files.
- [ ] Bundle sizes measured and reported.
- [ ] The landing prerenders without contacting the API.
- [ ] Nothing pushed or deployed.

## Not in this plan

Admin screens (step 6) — an application still has to be approved by calling the service directly until then. DNS, TLS, Caddy, CI and deploy (step 7): this app runs on localhost only when this plan is done.
