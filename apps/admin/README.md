# @yupay/admin

Backoffice SPA — React 19 + Vite + TypeScript. Not Next.js by design: SEO is
irrelevant, hydration cost is wasted, and a plain SPA keeps the deploy/CDN story tiny.

## Stack

- **Vite 5** (build), **React 19** (UI), **TypeScript strict**.
- **React Router v7** data API (routing + loaders + actions).
- **TanStack Query v5** (server state, caching, optimistic updates).
- **react-hook-form + zod** (forms, schema validation).
- **Tailwind v4** + `@yupay/ui` (shared design system).
- **Zustand** (auth slice; the rest of state lives in TanStack Query).

## Auth

Telegram Login Widget → backend `POST /api/v1/auth/telegram/widget` → access JWT
stored in `localStorage`. Admin endpoints require `admin` in `users.roles` —
non-admin users get 403. See
[ADR-0010](../../docs/decisions/0010-admin-auth-via-telegram-roles.md).

## Bootstrapping the first admin

After the first Telegram login, run on the API container:

```bash
docker compose exec api python -m yupay.scripts.grant_admin --tg-id <YOUR_TG_ID>
```

The next request from the admin SPA reflects the new role (no re-login required —
the role check runs per-request against the DB).

## Running locally

```bash
make dev                # full stack
# then open
open http://localhost:3002
```

Vite dev server proxies `/api/*` to the backend on `:8000`.

## Routes

| Path            | What                                |
| --------------- | ----------------------------------- |
| `/login`        | Telegram Login Widget               |
| `/`             | Dashboard (placeholder)             |
| `/categories`   | Categories list/edit                |
| `/brands`       | Brands list/edit/create             |
| `/brands/:id`   | Brand detail + products             |
| `/products`     | Products list                       |
| `/products/:id` | Product detail + form-schema editor |
| `/skus`         | SKUs list with per-product filter   |
